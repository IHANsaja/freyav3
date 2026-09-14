"""Freya as a trading teacher: learner memory, seeing drawings, drawing on the chart."""
import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.trading.simulator import TradingService
from core.trading import guide, learner


class FakeStore:
    def __init__(self):
        self.items = []

    def list(self, kinds=None, limit=200):
        return [i for i in self.items if not kinds or i.kind in kinds]

    def add(self, kind, subject, content, importance=2, source=""):
        self.items.append(SimpleNamespace(id=len(self.items) + 1, kind=kind, subject=subject, content=content))
        return len(self.items)

    def update(self, item_id, **fields):
        item = next(i for i in self.items if i.id == item_id)
        item.content = fields.get("content", item.content)
        return True


class TeacherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = TradingService(os.path.join(self.tmp.name, "lab.db"))
        self.s = self.svc.create({"key": "teach"})
        self.store = FakeStore()
        patcher = patch.object(learner, "_store", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)
        guide._views.clear()
        self.addCleanup(guide._views.clear)

    def tearDown(self):
        self.tmp.cleanup()

    def test_learner_starts_as_complete_beginner_and_grows(self):
        self.assertEqual(learner.profile()["level"], "complete beginner")
        learner.update(understood=["what a candle is"], struggling=["RSI"], learning_now="moving averages")
        p = learner.update(level="beginner", understood=["RSI", "what a candle is"], note="likes analogies")
        self.assertEqual(p["level"], "beginner")
        self.assertEqual(p["understood"], ["what a candle is", "RSI"])
        self.assertEqual(p["struggling"], [])
        self.assertEqual(p["lessons"], 2)
        self.assertEqual(len(self.store.items), 1)
        self.assertTrue(self.store.items[0].content.startswith("Trading knowledge: level beginner"))
        self.assertEqual(learner.profile()["learning_now"], "moving averages")
        with self.assertRaises(ValueError):
            learner.update(level="wizard")

    def test_context_includes_user_drawings_and_profile(self):
        candle = self.s["candles"][-1]
        guide.set_workspace(self.svc, guide.Workspace(
            client_id="c", session_id=self.s["id"], focused=True,
            drawings=[{"id": "d1", "kind": "hline", "points": [{"time": candle["time"], "price": 60000}], "point_count": 1}]))
        facts = guide.context(self.svc)
        self.assertEqual(facts["drawings"][0]["name"], "Horizontal line")
        self.assertEqual(facts["drawings"][0]["author"], "user")
        self.assertEqual(facts["learner_profile"]["level"], "complete beginner")

    def test_freya_draws_validated_snapped_drawing(self):
        from core.trading import tools
        candle = self.s["candles"][-1]
        guide.set_workspace(self.svc, guide.Workspace(client_id="c", session_id=self.s["id"], focused=True))
        async def page_confirms(event_type, payload):
            # The Trading Lab page acknowledges every drawing it adds.
            if payload.get("event") == "draw":
                guide.ack_draw(payload["draw_id"])
        emit = AsyncMock(side_effect=page_confirms)
        with patch.object(tools, "services", return_value=(self.svc, None)), patch.object(tools.runtime, "emit", emit):
            bad = asyncio.run(tools.draw_on_chart({"kind": "trend", "points": [{"time": candle["time"], "price": 1}]}, None))
            self.assertIn("needs exactly 2", bad)
            ok = asyncio.run(tools.draw_on_chart({"kind": "trend", "points": [
                {"time": candle["time"] + 7, "price": 60000}, {"time": candle["time"] * 1000, "price": 61000}]}, None))
            self.assertEqual(json.loads(ok)["drawn"], "Trend line")
            self.assertTrue(json.loads(ok)["visible"])
            asyncio.run(tools.clear_my_drawings({}, None))
        # No page confirmation: Freya is told the drawing did not appear.
        with patch.object(tools, "services", return_value=(self.svc, None)), \
                patch.object(tools.runtime, "emit", AsyncMock()), patch.object(tools, "DRAW_ACK_TIMEOUT_S", 0.05):
            lost = json.loads(asyncio.run(tools.draw_on_chart(
                {"kind": "hline", "points": [{"time": candle["time"], "price": 60000}]}, None)))
        self.assertFalse(lost["visible"]); self.assertIn("did not", lost["problem"])
        (_, draw), _ = emit.await_args_list[0]
        self.assertIn("draw_id", draw)
        self.assertEqual(draw["event"], "draw")
        self.assertEqual(draw["drawing"]["points"][0]["time"], candle["time"])
        self.assertEqual(draw["drawing"]["points"][1]["time"], candle["time"])
        self.assertEqual(emit.await_args_list[1].args[1]["event"], "clear_freya")


if __name__ == "__main__":
    unittest.main()
