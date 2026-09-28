"""Trading Teacher persona: built-in mode, and the lab switching Freya into it and back."""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from config import teacher
from core.trading import lab_mode
from core.trading.lab_mode import LabPresence, TEACHER


def _cfg(mode="default", enabled=True):
    return {"active_mode": mode, "trading": {"teacher_mode": enabled},
            "modes": {TEACHER: teacher.MODE, "coding": {}, "complex_tasks": {}}}


class BuiltinModeTests(unittest.TestCase):
    def test_load_config_adds_teacher_mode(self):
        from config import load_config
        cfg = load_config()
        self.assertIn(TEACHER, cfg["modes"])
        self.assertEqual(cfg["modes"][TEACHER]["label"], "Trading Teacher")
        self.assertIn("not a licensed financial adviser", cfg["modes"][TEACHER]["personality_override"])

    def test_mode_personality_keeps_base_prompt(self):
        from config import get_mode_personality
        prompt = get_mode_personality(_cfg(TEACHER), "BASE")
        self.assertTrue(prompt.startswith("BASE"))
        self.assertIn("Trading Teacher", prompt)
        self.assertIn("[DELIVERY]", prompt)


class PresenceTests(unittest.IsolatedAsyncioTestCase):
    async def run_sync(self, presence, mode, in_use, live=True, enabled=True):
        requested = AsyncMock(return_value=True)
        with patch("config.load_config", return_value=_cfg(mode, enabled)), \
             patch("core.runtime.is_live", return_value=live), \
             patch("core.runtime.request_mode", requested), \
             patch.object(presence, "lab_in_use", return_value=in_use), \
             patch.object(presence, "_schedule_greeting"):
            await presence.on_workspace()
        return requested

    async def test_switches_in_when_lab_in_use(self):
        p = LabPresence()
        req = await self.run_sync(p, "coding", True)
        req.assert_awaited_once_with(TEACHER, "trading_lab")
        self.assertEqual(p.return_to, "coding")

    async def test_not_without_live_session_or_when_disabled(self):
        self.assertFalse((await self.run_sync(LabPresence(), "default", True, live=False)).await_count)
        self.assertFalse((await self.run_sync(LabPresence(), "default", True, enabled=False)).await_count)

    async def test_never_overrides_complex_tasks(self):
        self.assertFalse((await self.run_sync(LabPresence(), "complex_tasks", True)).await_count)

    async def test_pending_switch_is_not_an_opt_out(self):
        p = LabPresence()
        await self.run_sync(p, "default", True)
        req = await self.run_sync(p, "default", True)       # hasn't landed yet
        self.assertFalse(req.await_count)
        self.assertFalse(p.opted_out)

    async def test_manual_mode_choice_in_lab_is_respected(self):
        p = LabPresence()
        await self.run_sync(p, "default", True)
        p._requested_at = time.monotonic() - 60           # the switch landed long ago
        req = await self.run_sync(p, "coding", True)        # he picked coding himself
        self.assertFalse(req.await_count)
        self.assertTrue(p.opted_out)
        self.assertIsNone(p.return_to)

    async def test_returns_to_previous_mode_after_grace(self):
        p = LabPresence()
        await self.run_sync(p, "coding", True)
        with patch.object(lab_mode, "RETURN_GRACE_S", 0.01):
            await self.run_sync(p, TEACHER, False)
            back = AsyncMock(return_value=True)
            with patch("config.load_config", return_value=_cfg(TEACHER)), \
                 patch("core.runtime.request_mode", back), \
                 patch.object(p, "lab_in_use", return_value=False):
                await asyncio.wait_for(p._return_task, 1)
        back.assert_awaited_once_with("coding", "left_trading_lab")

    async def test_quick_return_to_lab_cancels_switch_back(self):
        p = LabPresence()
        await self.run_sync(p, "coding", True)
        await self.run_sync(p, TEACHER, False)
        self.assertIsNotNone(p._return_task)
        task = p._return_task
        await self.run_sync(p, TEACHER, True)               # back within the grace period
        await asyncio.sleep(0)
        self.assertTrue(task.cancelled() or task.done())
        self.assertEqual(p.return_to, "coding")


if __name__ == "__main__":
    unittest.main()
