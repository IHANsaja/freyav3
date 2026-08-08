"""
Self-extending skills + dev/code execution — Freya can grow new abilities at runtime.

The headline "next-level" power: `create_tool` lets Freya *write a new Python tool for herself*.
The code is validated, saved to core/skills/custom/, and hot-loaded into the registry so it
persists across restarts (load_custom_tools re-imports them on boot). Plus the developer powers
her `coder` sub-agent leans on: run_code, edit_file.

Everything here is dangerous=True, so it all flows through core/safety.py first (destructive
shell/code patterns refused; file writes confined to allowed roots).
"""

import importlib
import importlib.util
import os
import subprocess
import sys

from core.registry import tool, register, OBJ, P, STR
from core.user_paths import resolve_user_path

_CUSTOM_DIR = os.path.join(os.path.dirname(__file__), "skills", "custom")

_TEMPLATE = '''# Auto-generated Freya skill — created by Freya herself.
from core.registry import tool, OBJ, P, STR, INT, BOOL
from core.user_paths import resolve_user_path


@tool({name!r}, {description!r}, OBJ({{"input": P(STR, "optional free-form input")}}))
def {name}(args, ctx):
    text = args.get("input", "")
{body}
'''


def _ensure_pkg():
    os.makedirs(_CUSTOM_DIR, exist_ok=True)
    for d in (os.path.dirname(_CUSTOM_DIR), _CUSTOM_DIR):
        init = os.path.join(d, "__init__.py")
        if not os.path.exists(init):
            with open(init, "w", encoding="utf-8") as f:
                f.write("")


def load_custom_tools():
    """Re-import every previously-created custom skill so it re-registers.
    Tools loaded here are stamped with the 'custom' skill id for the catalog."""
    from core import registry
    previous = registry._current_skill
    registry._current_skill = previous or "custom"
    _ensure_pkg()
    try:
        for name in os.listdir(_CUSTOM_DIR):
            if name.endswith(".py") and name != "__init__.py":
                mod = f"core.skills.custom.{name[:-3]}"
                try:
                    if mod in sys.modules:
                        importlib.reload(sys.modules[mod])
                    else:
                        importlib.import_module(mod)
                except Exception as e:
                    print(f"  [self_extend] couldn't load custom tool {name}: {e}")
    finally:
        registry._current_skill = previous


@tool(
    "create_tool",
    "Write yourself a new Python tool, permanently. Give a snake_case name, a description, and "
    "the function BODY (use `text` for input, `return` a string). Available next session.",
    OBJ({"name": P(STR, "snake_case tool name, e.g. roll_dice"),
         "description": P(STR, "What the tool does (Gemini sees this)"),
         "python_code": P(STR, "The function body. Use `text` for input, `return` a string. "
                               "Local imports allowed.")},
        ["name", "description", "python_code"]),
    dangerous=True,
)
def create_tool(args, ctx) -> str:
    name = (args.get("name") or "").strip()
    if not name.isidentifier():
        return f"'{name}' isn't a valid tool name (use snake_case letters/underscores)."
    description = (args.get("description") or name).strip()
    body = args.get("python_code") or "    return 'ok'"
    # Indent the supplied body into the function.
    indented = "\n".join(("    " + line) if line.strip() else line
                         for line in body.splitlines()) or "    return 'ok'"
    source = _TEMPLATE.format(name=name, description=description, body=indented)
    try:
        compile(source, f"<custom:{name}>", "exec")
    except SyntaxError as e:
        return f"That code has a syntax error on line {e.lineno}: {e.msg}. Tool not created."

    _ensure_pkg()
    path = os.path.join(_CUSTOM_DIR, f"{name}.py")
    # Safety gate re-check on the concrete path.
    from core.safety import path_is_allowed
    if not path_is_allowed(path, ctx.config):
        return "Refused: custom tools must live inside the project."
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    try:
        load_custom_tools()  # register immediately
    except Exception as e:
        return f"Saved but failed to load: {e}"
    return (f"Done — I wrote a new tool called '{name}'. It's saved and will be fully active when "
            "we reconnect the session.")


@tool(
    "run_code",
    "Execute a short Python snippet and return its output. For quick computation, file ops, or "
    "verifying code. Runs in a separate process with a timeout.",
    OBJ({"code": P(STR, "Python code to run; print() what you want back")}, ["code"]),
    dangerous=True,
)
def run_code(args, ctx) -> str:
    code = args.get("code", "")
    if not code.strip():
        return "No code to run."
    try:
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, timeout=30)
        out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        if not out:
            return "Code ran with no output."
        lines = out.splitlines()
        if len(lines) > 20:
            return "\n".join(lines[:20]) + f"\n…(+{len(lines) - 20} more lines)"
        return out
    except subprocess.TimeoutExpired:
        return "Code timed out after 30 seconds."
    except Exception as e:
        return f"Run failed: {e}"


@tool(
    "edit_file",
    "Make a precise edit to a text file by replacing an exact string with a new one.",
    OBJ({"path": P(STR, "Absolute file path"),
         "old_string": P(STR, "Exact text to replace (must be unique in the file)"),
         "new_string": P(STR, "Replacement text")}, ["path", "old_string", "new_string"]),
    dangerous=True,
)
def edit_file(args, ctx) -> str:
    path = resolve_user_path(args.get("path", ""))
    old, new = args.get("old_string", ""), args.get("new_string", "")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"Couldn't read {path}: {e}"
    count = content.count(old)
    if count == 0:
        return f"Couldn't find that exact text in {path}."
    if count > 1:
        return f"That text appears {count} times in {path}; make old_string more specific."
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.replace(old, new))
        return f"Edited {path}."
    except Exception as e:
        return f"Couldn't write {path}: {e}"
