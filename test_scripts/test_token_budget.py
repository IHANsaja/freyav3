"""Token and request budgets for background agents on a free-tier Gemini project."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from google.genai import types

from core import agents, quota
from core.registry import ToolContext


def reply(parts, prompt=None):
    """A fake generate_content response."""
    content = types.Content(role="model", parts=parts)
    text = "".join(p.text or "" for p in parts if getattr(p, "text", None))
    meta = NS(prompt_token_count=prompt, total_token_count=(prompt or 0) + 10,
              cached_content_token_count=0, candidates_token_count=10, thoughts_token_count=0)
    return NS(candidates=[NS(content=content)], text=text, usage_metadata=meta)


def call(name="web_search", **args):
    return types.Part(function_call=types.FunctionCall(name=name, args=args or {"query": "x"}))


def result_turn(text):
    return types.Content(role="user", parts=[types.Part(
        function_response=types.FunctionResponse(name="web_search", response={"result": text}))])


class Isolated(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        quota.reset()
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.state_path = Path(state.name) / "quota_state.json"
        patcher = patch.object(quota, "_STATE_PATH", str(self.state_path))
        patcher.start()
        self.addCleanup(patcher.stop)


class EstimateTests(unittest.TestCase):
    def test_counts_text_tool_io_and_declarations(self):
        contents = [types.Content(role="user", parts=[types.Part(text="a" * 400)]), result_turn("b" * 4000)]
        body = quota.estimate_tokens(contents)
        self.assertGreater(body, 1100)          # ~100 + ~1000 tokens
        self.assertLess(body, 1300)
        decl = types.FunctionDeclaration(name="web_search", description="d" * 800)
        cfg = types.GenerateContentConfig(system_instruction="s" * 400,
                                          tools=[types.Tool(function_declarations=[decl])])
        self.assertGreater(quota.estimate_tokens(contents, cfg), body + 290)

    def test_media_parts_are_counted_without_base64_blowup(self):
        part = types.Part(inline_data=types.Blob(mime_type="image/png", data=b"x" * 500_000))
        self.assertEqual(quota.estimate_tokens([types.Content(role="user", parts=[part])]),
                         quota._TOKENS_PER_MEDIA_PART + 4)


class PacingTests(Isolated):
    def test_tpm_window_waits_for_old_tokens_to_expire(self):
        bucket, now = ("p", "m"), 1000.0
        quota._tpm[bucket].append([now - 50, 900])
        self.assertAlmostEqual(quota._tpm_wait(bucket, 1000, 200, now), 10, delta=0.01)
        self.assertEqual(quota._tpm_wait(bucket, 1000, 100, now), 0)
        self.assertEqual(quota._tpm_wait(bucket, 1000, 200, now + 11), 0)   # expired

    def test_oversized_request_is_not_blocked_forever(self):
        self.assertEqual(quota._tpm_wait(("p", "m"), 1000, 5000, 0.0), 0)

    async def test_reservation_becomes_the_reported_prompt_size(self):
        client = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=reply([types.Part(text="ok")], prompt=1234)))))
        cfg = {"_quota_mission": "job", "quota": {"default_rpm": 1e9, "project": "p"}}
        await quota.generate(client, quota_config=cfg, model="m", contents="hello " * 50)
        self.assertEqual(quota._tpm[("p", "m")][-1][1], 1234)
        stats = quota.usage("job")
        self.assertEqual((stats["requests"], stats["input_tokens"], stats["output_tokens"]), (1, 1234, 10))


class DailyTests(Isolated):
    def cfg(self, **q):
        return {"quota": {"default_rpm": 1e9, "project": "p", **q}}

    def daily_429(self):
        exc = RuntimeError("429 RESOURCE_EXHAUSTED")
        exc.response_json = {"error": {"code": 429, "details": [{"violations": [
            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}]}}
        return exc

    async def test_exhausted_model_is_skipped_until_reset_and_survives_restart(self):
        calls = []

        async def generate_content(**kw):
            calls.append(kw["model"])
            if kw["model"] == "gemini-3.5-flash":
                raise self.daily_429()
            return reply([types.Part(text="ok")], prompt=5)

        client = NS(aio=NS(models=NS(generate_content=generate_content)))
        await quota.generate(client, quota_config=self.cfg(), model="gemini-3.5-flash")
        self.assertEqual(calls, ["gemini-3.5-flash", "gemini-3.5-flash-lite"])
        saved = json.loads(self.state_path.read_text())
        self.assertEqual(saved["day"], quota.pacific_day())
        self.assertTrue(saved["models"]["p|gemini-3.5-flash"]["exhausted"])

        quota.reset()                      # a restart: memory gone, file kept
        await quota.generate(client, quota_config=self.cfg(), model="gemini-3.5-flash")
        self.assertEqual(calls[2:], ["gemini-3.5-flash-lite"])    # no wasted request

    async def test_new_pacific_day_clears_exhaustion(self):
        self.state_path.write_text(json.dumps({"day": "2000-01-01", "models": {"p|m": {"exhausted": True}}}))
        self.assertFalse(quota.daily_state("p", "m").get("exhausted"))

    async def test_local_daily_budget_moves_to_fallback(self):
        client = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=reply([types.Part(text="ok")], prompt=5)))))
        cfg = self.cfg(rpd_by_model={"gemini-3.5-flash": 2})
        for _ in range(3):
            await quota.generate(client, quota_config=cfg, model="gemini-3.5-flash")
        models = [c.kwargs["model"] for c in client.aio.models.generate_content.await_args_list]
        self.assertEqual(models, ["gemini-3.5-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"])

    async def test_no_fallback_fails_fast_without_a_request(self):
        client = NS(aio=NS(models=NS(generate_content=AsyncMock())))
        cfg = self.cfg(rpd_by_model={"solo": 1}, fallback_models={})
        quota._roll_day()
        quota._daily["p|solo"] = {"requests": 1, "exhausted": False}
        with self.assertRaisesRegex(quota.QuotaError, "midnight Pacific"):
            await quota.generate(client, quota_config=cfg, model="solo")
        client.aio.models.generate_content.assert_not_awaited()

    def test_messages_name_the_limit(self):
        self.assertIn("midnight Pacific", quota.describe_failure(self.daily_429()))
        minute = RuntimeError("429")
        minute.response_json = {"error": {"details": [{"violations": [{"quotaId": "TokensPerMinute"}]}]}}
        self.assertIn("per-minute", quota.describe_failure(minute))

    def test_pacific_fallback_without_tz_database(self):
        with patch.dict("sys.modules", {"zoneinfo": None}):
            day = quota.pacific_day()
        self.assertRegex(day, r"^\d{4}-\d{2}-\d{2}$")
        self.assertLessEqual(quota.seconds_until_reset(), 86400)


class CompactTests(unittest.TestCase):
    def test_trims_old_results_only_and_leaves_model_turns_untouched(self):
        model_turn = types.Content(role="model", parts=[call()])
        contents = [types.Content(role="user", parts=[types.Part(text="task")]),
                    model_turn, result_turn("A" * 3000),
                    model_turn, result_turn("B" * 3000),
                    model_turn, result_turn("C" * 3000)]
        removed = agents._compact(contents, keep_recent=2, head_chars=300)
        self.assertEqual(removed, 2700)
        old = contents[2].parts[0].function_response.response["result"]
        self.assertTrue(old.startswith("A" * 300) and old.endswith(agents._TRIM_MARK))
        self.assertEqual(contents[4].parts[0].function_response.response["result"], "B" * 3000)
        self.assertIs(contents[1], model_turn)                         # model turns as received
        self.assertEqual(agents._compact(contents, 2, 300), 0)         # idempotent


class ReactLoopTests(Isolated):
    def run_loop(self, responses, config=None, max_steps=8):
        client = NS(aio=NS(models=NS(generate_content=AsyncMock(side_effect=responses))))
        decl = types.FunctionDeclaration(name="web_search", description="search")
        patches = [patch("core.agents.genai.Client", return_value=client),
                   patch("core.agents._declarations", return_value=[decl]),
                   patch("core.agents.registry_dispatch", AsyncMock(return_value="R" * 3000))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        cfg = {"quota": {"default_rpm": 1e9}, **(config or {})}
        coro = agents.react_loop("sys", "task", ["web_search"], "gemini-3.5-flash", cfg,
                                 ToolContext(cfg), max_steps=max_steps)
        return client, coro

    async def test_last_step_asks_for_an_answer_with_tools_off(self):
        client, coro = self.run_loop([reply([call()]), reply([types.Part(text="partial answer")])], max_steps=2)
        self.assertEqual(await coro, "partial answer")
        last = client.aio.models.generate_content.await_args_list[-1].kwargs
        self.assertEqual(last["config"].tool_config.function_calling_config.mode, "NONE")
        self.assertIsNotNone(last["config"].tools)                    # prefix unchanged
        self.assertIn("[BUDGET]", last["contents"][-1].parts[-1].text)

    async def test_task_token_budget_triggers_wrap_up_early(self):
        client, coro = self.run_loop(
            [reply([call()], prompt=90_000), reply([call()], prompt=95_000), reply([types.Part(text="done")])],
            config={"agent_budget": {"max_tokens_per_task": 150_000}})
        self.assertEqual(await coro, "done")
        self.assertEqual(client.aio.models.generate_content.await_count, 3)
        self.assertEqual(client.aio.models.generate_content.await_args_list[2].kwargs["config"]
                         .tool_config.function_calling_config.mode, "NONE")

    async def test_context_budget_trims_old_results_before_sending(self):
        client, coro = self.run_loop(
            [reply([call()], prompt=900), reply([call()], prompt=1700), reply([call()], prompt=2500),
             reply([types.Part(text="done")])],
            config={"agent_budget": {"max_context_tokens": 2000, "keep_recent_results": 1}})
        self.assertEqual(await coro, "done")
        sent = client.aio.models.generate_content.await_args_list[-1].kwargs["contents"]
        results = [p.function_response.response["result"] for c in sent for p in c.parts
                   if getattr(p, "function_response", None)]
        self.assertTrue(all(r.endswith(agents._TRIM_MARK) for r in results[:-1]))
        self.assertEqual(results[-1], "R" * 3000)

    async def test_thinking_level_is_low_by_default_and_dropped_if_unsupported(self):
        client, coro = self.run_loop([RuntimeError("400 thinking_level is not supported"),
                                      reply([types.Part(text="ok")])])
        self.assertEqual(await coro, "ok")
        first, second = [c.kwargs["config"] for c in client.aio.models.generate_content.await_args_list]
        self.assertEqual(first.thinking_config.thinking_level, types.ThinkingLevel.LOW)
        self.assertIsNone(second.thinking_config)


class ConcurrencyTests(unittest.TestCase):
    def test_slots_follow_config(self):
        self.assertEqual(agents._slots({"agent_budget": {"max_concurrent": 3}})._value, 3)
        self.assertEqual(agents._slots({})._value, agents.AGENT_BUDGET["max_concurrent"])

    def test_usage_line(self):
        self.assertEqual(agents._usage_line({"requests": 3, "input_tokens": 41000, "cached_tokens": 12000}),
                         "3 requests, 41,000 input tokens (12,000 cached)")
        self.assertEqual(agents._usage_line({}), "")


if __name__ == "__main__":
    unittest.main()
