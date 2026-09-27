"""Offline tests for the System One (Jev) integration: no network, fake TypeSafe endpoint."""
import asyncio
import json
import os
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS, ModuleType
from unittest.mock import AsyncMock, patch

import httpx
from google.genai import types

from core import systemone

ON = {"system_one": {"enabled": True}}


def fake_api(handler):
    """Route systemone's HTTP client to `handler(request_json) -> (status, body)`."""
    seen = []

    def respond(request: httpx.Request):
        body = json.loads(request.content)
        seen.append(body)
        status, payload = handler(body)
        return httpx.Response(status, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    return patch.object(systemone, "_client", lambda: client), seen


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"})
        self.env.start()
        systemone._down_until = 0.0

    def tearDown(self):
        self.env.stop()
        systemone._down_until = 0.0


class ClientTests(Base):
    async def test_key_is_the_switch(self):
        # Key present → on, with no config at all.
        self.assertTrue(systemone.available())
        self.assertTrue(systemone.enabled({}, "tool_routing"))
        self.assertTrue(systemone.enabled(ON, "tool_routing"))
        # A feature can still be kept on Gemini explicitly.
        self.assertFalse(systemone.enabled(
            {"system_one": {"features": {"tool_routing": False}}}, "tool_routing"))
        # No key (or a blank one) → Gemini only, whatever the config says.
        for blank in ("", "   "):
            with patch.dict(os.environ, {"TYPESAFE_API_KEY": blank}):
                self.assertFalse(systemone.available())
                self.assertFalse(systemone.enabled(ON, "tool_routing"))
                self.assertIn("Gemini only", systemone.describe_status())

    async def test_without_key_every_helper_falls_back_without_calling_jev(self):
        calls = []
        mock, seen = fake_api(lambda b: (calls.append(b), (200, {"answers": {}}))[1])
        with mock, patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            self.assertIsNone(await systemone.noul("s", "q?", {}, "memory_triage"))
            self.assertIsNone(await systemone.choice("s", "q?", {"a": None}, {}, "tool_routing"))
            self.assertIsNone(await systemone.score("s", "q?", ["low", "high"], {}, "approval_risk"))
            self.assertEqual(await systemone.memory_importance(["x", "y"], {}), [None, None])
        self.assertEqual(seen, [])

    async def test_noul_request_shape_and_answer(self):
        mock, seen = fake_api(lambda b: (200, {"answers": {"q": {"type": "noul", "noul": 0.93}}}))
        with mock:
            p = await systemone.noul("state", "Is it?", ON, "x", criteria={"true": "a", "false": "b"})
        self.assertAlmostEqual(p, 0.93)
        self.assertEqual(seen[0]["model"], "jev-latest")
        self.assertEqual(seen[0]["questions"]["q"]["criteria"], {"true": "a", "false": "b"})

    async def test_failure_returns_none_and_opens_breaker(self):
        mock, seen = fake_api(lambda b: (529, {"error": "overloaded"}))
        with mock:
            self.assertIsNone(await systemone.noul("s", "q", ON, "x"))
            self.assertFalse(systemone.enabled(ON, "x"))
            self.assertIsNone(await systemone.noul("s", "q", ON, "x"))
        self.assertEqual(len(seen), 1)  # the breaker skipped the second call

    async def test_validation_error_does_not_open_breaker(self):
        mock, _ = fake_api(lambda b: (422, {"detail": "bad"}))
        with mock:
            self.assertIsNone(await systemone.noul("s", "q", ON, "x"))
        self.assertTrue(systemone.enabled(ON, "x"))

    async def test_memory_importance_batches_and_respects_confidence(self):
        def handler(body):
            self.assertEqual(set(body["questions"]), {"i0", "i1"})
            return 200, {"answers": {
                "i0": {"type": "score", "score": 3.8, "confidence": 0.9},
                "i1": {"type": "score", "score": 1.0, "confidence": 0.1},
            }}
        mock, seen = fake_api(handler)
        with mock:
            out = await systemone.memory_importance(["dentist friday", "likes tea"], ON)
        self.assertEqual(out, [5, None])
        self.assertEqual(len(seen), 1)


class ToolRoutingTests(Base):
    async def test_jev_hits_come_first_and_keywords_fill(self):
        from core import tool_index
        decls = [types.FunctionDeclaration(name=n, description=d) for n, d in [
            ("read_email", "Read messages from the mail account"),
            ("get_weather", "Weather forecast"),
            ("inbox_zero_tips", "Tips about inbox organisation"),
        ]]
        answer = {"answers": {"q": {"type": "choice", "choice": "read_email", "confidence": 0.8,
                                    "probabilities": {"read_email": 0.9, "get_weather": 0.01,
                                                      "inbox_zero_tips": 0.09}}}}
        mock, _ = fake_api(lambda b: (200, answer))
        with mock, patch.object(tool_index, "_all_declarations", return_value=decls):
            out = json.loads(await tool_index.search_tools(
                {"query": "check my inbox", "limit": 3}, NS(config=ON)))
        self.assertEqual([t["name"] for t in out], ["read_email", "inbox_zero_tips"])

    async def test_keyword_path_unchanged_when_off(self):
        from core import tool_index
        decls = [types.FunctionDeclaration(name="read_email", description="Read mail")]
        with patch.object(tool_index, "_all_declarations", return_value=decls):
            out = await tool_index.search_tools({"query": "check my inbox"}, NS(config={}))
        self.assertIn("No tools match", out)


class MissionVerifyTests(Base):
    def step(self):
        from core.missions import MissionStep
        return MissionStep(id=1, title="t", detail="find the price", result="Price is $4")

    async def test_confident_pass_skips_gemini(self):
        from core import missions
        mock, _ = fake_api(lambda b: (200, {"answers": {"q": {"type": "noul", "noul": 0.97}}}))
        with mock, patch.object(missions, "_generate", AsyncMock(side_effect=AssertionError)):
            ok, reason = await missions.missions._verify_step(None, self.step(), [], ON)
        self.assertTrue(ok)
        self.assertIn("Jev", reason)

    async def test_doubtful_step_still_gets_gemini_reason(self):
        from core import missions
        mock, _ = fake_api(lambda b: (200, {"answers": {"q": {"type": "noul", "noul": 0.4}}}))
        gemini = AsyncMock(return_value=NS(text='{"verified": false, "reason": "no price found"}'))
        with mock, patch.object(missions, "_generate", gemini), \
                patch.object(missions, "get_agent_api_key", return_value="k"):
            ok, reason = await missions.missions._verify_step(None, self.step(), [], ON)
        self.assertEqual((ok, reason), (False, "no price found"))


class NudgeGateTests(Base):
    async def test_unwelcome_nudge_is_dropped_before_drafting(self):
        from core.context_watch import ContextTracker
        t = ContextTracker()
        t._config = {**ON, "ambient": {"context_tracker": {"enabled": True}}}
        t._draft = AsyncMock(return_value="want help?")
        mock, _ = fake_api(lambda b: (200, {"answers": {"q": {"type": "noul", "noul": 0.2}}}))
        with mock, patch("core.context_watch.runtime.emit", AsyncMock()) as emit:
            await t._trigger("stuck", "10 minutes in a game")
        t._draft.assert_not_awaited()
        emit.assert_not_awaited()

    async def test_gate_open_when_jev_off(self):
        from core.context_watch import ContextTracker
        t = ContextTracker()
        t._config = {}
        self.assertTrue(await t._welcome("stuck", "x"))


class ApprovalRiskTests(Base):
    async def test_risk_is_attached_and_published_but_never_resolves(self):
        from core.approvals import approvals
        answer = {"answers": {"q": {"type": "score", "score": 3.2, "confidence": 0.9}}}
        mock, _ = fake_api(lambda b: (200, answer))
        published = []

        async def publish(kind, payload):
            published.append((kind, payload))

        with mock, patch("config.load_config", return_value=ON), \
                patch("core.approvals.bus.publish", publish), \
                patch("core.approvals.bus.publish_soon", lambda *a: None):
            action_id = approvals.request_deferred("delete a folder", "delete_file",
                                                   {"path": "x"}, AsyncMock(), timeout=5)
            for _ in range(50):
                if published:
                    break
                await asyncio.sleep(0.01)
        action = approvals._pending.pop(action_id)
        action.timeout_task.cancel()
        self.assertEqual(action.risk, 4)
        self.assertEqual(action.to_payload()["risk"], 4)
        self.assertEqual(published, [("approval", {"event": "assessed", "id": action_id, "risk": 4})])


class ModeRoutingTests(Base):
    async def test_confident_complex_turn_switches_mode(self):
        from core.live_protocol import ModeChange
        from core.model import FreyaModel
        session = NS(frames=asyncio.Queue(), send_client_content=AsyncMock(),
                     send_realtime_input=AsyncMock(), send_tool_response=AsyncMock())

        async def receive():
            yield await session.frames.get()
        session.receive = receive

        obj = FreyaModel("test", "m", "Zephyr", "Test", {**ON, "active_mode": "default"})
        obj.get_config = lambda: types.LiveConnectConfig(response_modalities=["AUDIO"])
        obj.on_state = AsyncMock()
        obj.on_tool = AsyncMock()

        @asynccontextmanager
        async def connect(**kw):
            yield session
        obj.client = NS(aio=NS(live=NS(connect=connect)))
        stubs = {}
        for mod, attr, value in [
            ("mcp_client", "mcp_manager", NS(start=AsyncMock())),
            ("scheduler", "scheduler", NS(attach=lambda _: None, detach=lambda: None)),
            ("context_watch", "tracker", NS(attach=lambda _: None, detach=lambda: None)),
            ("day_context", "rotator", NS(attach=lambda _: None, detach=lambda: None)),
            ("hotkeys", "start_pause_hotkey", lambda _: None),
            ("ambient", "ambient", NS(stop_all=lambda: None)),
        ]:
            stub = ModuleType("core." + mod); setattr(stub, attr, value); stubs["core." + mod] = stub

        with patch.dict("sys.modules", stubs), \
                patch.object(systemone, "noul", AsyncMock(return_value=0.95)), \
                patch("core.tools.switch_mode", return_value="MODE_SWITCHED:complex_tasks") as sw:
            task = asyncio.create_task(obj.run(NS(read=lambda: None), NS(write=lambda _: None)))
            await session.frames.put(types.LiveServerMessage(server_content=types.LiveServerContent(
                input_transcription=types.Transcription(text="debug why the parser drops rows"),
                turn_complete=True)))
            with self.assertRaises(ModeChange):
                await asyncio.wait_for(task, 3)
        sw.assert_called_once_with("complex_tasks")
        obj.on_tool.assert_awaited_with("switch_mode", {"mode": "complex_tasks", "via": "jev"},
                                        "MODE_SWITCHED:complex_tasks")


if __name__ == "__main__":
    unittest.main()
