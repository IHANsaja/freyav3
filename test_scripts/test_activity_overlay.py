"""Activity pill wording — no window is created here."""

import json

from core.activity_overlay import describe


def test_direct_tool():
    assert describe("find_on_pc", {"what": "Freya test"}) == "Searching your PC for “Freya test”"


def test_run_tool_uses_inner_tool_and_args():
    args = {"name": "open_path", "arguments": json.dumps({"path": r"C:\Docs\report.pdf"})}
    assert describe("run_tool", args) == "Opening report.pdf"


def test_body_language_is_silent():
    assert describe("set_expression", {"expression": "calm"}) is None
    assert describe("run_tool", {"name": "trigger_thinking", "arguments": "{}"}) is None


def test_unknown_tool_gets_readable_fallback():
    assert describe("brand_new_tool", {}) == "Brand new tool"


def test_bad_arguments_never_raise():
    assert describe("run_tool", {"name": "list_dir", "arguments": "{not json"}) == "Looking inside it"
    assert describe("set_volume", None) == "Setting the volume"
    assert describe("set_volume", {"level": 30}) == "Setting volume to 30%"


def test_long_values_are_trimmed():
    label = describe("web_search", {"query": "x" * 200})
    assert len(label) < 80 and label.endswith("…”")
