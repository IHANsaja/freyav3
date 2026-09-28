"""The dashboard's activity feed: phases, tool usage history, outcomes."""

import unittest

from core.activity import ActivityFeed, category


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.feed = ActivityFeed(publish=self.sent.append)

    def test_tool_lifecycle_records_history(self):
        self.feed.set_state("listening")
        self.feed.tool_started("c1", "find_on_pc", {"what": "cv"}, "Searching your PC for “cv”")
        snap = self.feed.snapshot()
        self.assertEqual(snap["phase"], "working")
        self.assertEqual(snap["tools"][0]["category"], "search")
        self.feed.tool_outcome("c1", "error", "boom")
        self.feed.tool_finished("c1")
        snap = self.feed.snapshot()
        self.assertEqual(snap["phase"], "listening")
        self.assertEqual(snap["recent"][0]["status"], "error")
        self.assertEqual(snap["stats"], {**snap["stats"], "calls": 1, "failures": 1})

    def test_run_tool_reports_inner_tool(self):
        self.feed.tool_started("c2", "run_tool", {"name": "open_path", "arguments": "{}"}, "Opening it")
        self.assertEqual(self.feed.snapshot()["tools"][0]["name"], "open_path")
        self.assertEqual(self.feed.snapshot()["tools"][0]["category"], "file")

    def test_body_language_is_invisible(self):
        self.feed.tool_started("c3", "set_expression", {}, None)
        self.assertEqual(self.feed.snapshot()["tools"], [])

    def test_priority_recovering_over_approval_over_work(self):
        self.feed.tool_started("c1", "web_search", {}, "Searching the web")
        self.feed.approval("a1", "delete a file")
        self.assertEqual(self.feed.snapshot()["phase"], "approval")
        self.feed.set_recovering("Reconnecting")
        self.assertEqual(self.feed.snapshot()["phase"], "recovering")
        self.feed.set_recovering("")
        self.feed.approval("a1", None)
        self.assertEqual(self.feed.snapshot()["phase"], "working")

    def test_hearing_publishes_once(self):
        self.feed.set_state("listening")
        n = len(self.sent)
        for _ in range(10):
            self.feed.heard()
        self.assertEqual(len(self.sent), n + 1)
        self.assertEqual(self.sent[-1]["phase"], "hearing")

    def test_background_mode_is_published(self):
        self.feed.tool_started("c1", "browser_task", {}, "Browsing")
        self.feed.tool_mode("c1", "background")
        self.assertEqual(self.sent[-1]["tools"][0]["mode"], "background")

    def test_categories(self):
        self.assertEqual(category("web_search"), "web")
        self.assertEqual(category("mcp__github__x"), "agent")
        self.assertEqual(category("nope"), "other")


if __name__ == "__main__":
    unittest.main()
