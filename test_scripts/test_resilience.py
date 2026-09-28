"""Recovery protocol: backoff, breaker, health, guarded calls and the session runner."""

import asyncio
import importlib
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

from core import resilience
from core.resilience import Backoff, ToolBreaker, Health, guard, aguard


class BackoffTests(unittest.TestCase):
    def test_grows_and_caps(self):
        b = Backoff(base=1, cap=8, jitter=0)
        self.assertEqual([b.next() for _ in range(6)], [1, 2, 4, 8, 8, 8])
        b.reset()
        self.assertEqual(b.next(), 1)

    def test_jitter_stays_in_band(self):
        b = Backoff(base=10, cap=10, jitter=0.2)
        for _ in range(50):
            self.assertTrue(8 <= b.next() <= 12)


class BreakerTests(unittest.TestCase):
    def test_trips_after_threshold_and_success_closes(self):
        br = ToolBreaker(threshold=2, rest_s=60)
        self.assertFalse(br.failure("x"))
        self.assertTrue(br.failure("x"))
        self.assertTrue(br.is_open("x"))
        self.assertIn("resting", br.resting_message("x"))
        br.success("x")
        self.assertFalse(br.is_open("x"))

    def test_half_open_after_rest(self):
        br = ToolBreaker(threshold=2, rest_s=0)
        br.failure("x")
        br.failure("x")
        self.assertFalse(br.is_open("x"))       # rest over: one attempt allowed
        self.assertTrue(br.failure("x"))        # and one failure re-opens it


class GuardTests(unittest.IsolatedAsyncioTestCase):
    def test_guard_returns_fallback(self):
        self.assertEqual(guard("t", lambda: 1 / 0, fallback="safe"), "safe")
        self.assertEqual(guard("t", lambda a: a * 2, 3), 6)

    async def test_aguard_timeout_and_error(self):
        self.assertEqual(await aguard("t", asyncio.sleep(5), fallback="late", timeout=0.01), "late")

        async def boom():
            raise ValueError("x")
        self.assertIsNone(await aguard("t", boom()))

    async def test_aguard_never_swallows_cancel(self):
        task = asyncio.create_task(aguard("t", asyncio.sleep(5)))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


class HealthTests(unittest.TestCase):
    def test_overall_is_worst_component(self):
        h = Health()
        with patch.object(h, "_publish"):
            self.assertEqual(h.overall(), "ok")
            h.set("mic", "degraded", "default device")
            h.set("live", "recovering", "retry")
            self.assertEqual(h.overall(), "recovering")
            names = {c["name"] for c in h.snapshot()["components"]}
            self.assertTrue({"live", "mic"} <= names)
            h.ok("live")
            h.ok("mic")
            self.assertEqual(h.overall(), "ok")

    def test_publishes_only_on_change(self):
        h = Health()
        with patch.object(h, "_publish") as pub:
            h.set("mic", "degraded", "a")
            h.set("mic", "degraded", "a")
            self.assertEqual(pub.call_count, 1)


def _server():
    # Import the dashboard without requiring PortAudio on the test machine.
    with patch.dict("sys.modules", {"pyaudio": NS(paInt16=8)}):
        return importlib.import_module("server")


class AudioFallbackTests(unittest.TestCase):
    def test_saved_device_falls_back_to_default(self):
        server = _server()

        class Stream:
            def __init__(self, device_index=None, device_name=None):
                self.index = device_index

            def start(self):
                if self.index is not None:
                    raise OSError("device gone")

            def stop(self):
                pass

        cfg = {"audio": {"input_device_index": 3, "input_device_name": "Headset",
                         "output_device_index": None, "output_device_name": None}}
        with patch.object(server, "MicStream", Stream), patch.object(server, "SpeakerStream", Stream), \
             patch.object(resilience.health, "_publish"):
            mic, _speaker = server._open_audio(cfg)
            self.assertIsNone(mic.index)
            self.assertEqual(resilience.health.get("mic").state, "degraded")

    def test_no_device_at_all_raises_for_the_supervisor(self):
        server = _server()

        class Broken:
            def __init__(self, **kw):
                pass

            def start(self):
                raise OSError("no audio")

            def stop(self):
                pass

        with patch.object(server, "MicStream", Broken), patch.object(server, "SpeakerStream", Broken), \
             patch.object(resilience.health, "_publish"):
            with self.assertRaises(server.AudioUnavailable):
                server._open_audio({"audio": {}})


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_never_gives_up_after_many_failures(self):
        server = _server()
        cfg = {"active_provider": "gemini", "active_model": "m", "active_mode": "default", "modes": {},
               "audio": {}, "providers": {"gemini": {"active_voice": "Zephyr"}},
               "freya": {"personality": "T"}}
        runs = []

        class FakeModel:
            def __init__(self, **kw):
                self.resume_handle = None
                self.connected = False

            async def run(self, *a):
                runs.append(1)
                if len(runs) < 9:
                    raise ConnectionError("net down")
                server.freya_running = False

        with patch.object(server, "FreyaModel", FakeModel), patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "get_api_key", return_value="k"), patch.object(server, "load_memory", return_value=""), \
             patch.object(server, "MicStream", MagicMock()), patch.object(server, "SpeakerStream", MagicMock()), \
             patch.object(server, "broadcast", AsyncMock()), patch.object(server, "update_memory", AsyncMock()), \
             patch.object(server, "freya_running", True), patch("core.machine_index.ensure_index"), \
             patch.object(server, "_sleep_while_running", AsyncMock()), patch.object(resilience.health, "_publish"):
            await server.run_freya()
        self.assertEqual(len(runs), 9)

    async def test_prompt_failure_degrades_instead_of_crashing(self):
        server = _server()
        with patch.object(server, "build_system_prompt", side_effect=[RuntimeError("db"), "prompt"]), \
             patch.object(server, "get_mode_personality", return_value="base"), \
             patch.object(resilience.health, "_publish"):
            self.assertEqual(server._build_personality({}, "base", "mem"), "prompt")

    async def test_supervisor_restarts_after_crash(self):
        server = _server()
        calls = []

        async def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("setup bug")

        with patch.object(server, "run_freya", flaky), patch.object(server, "broadcast", AsyncMock()), \
             patch.object(server, "_session_wanted", True), patch("asyncio.sleep", AsyncMock()), \
             patch.object(resilience.health, "_publish"):
            await server.supervise_freya()
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
