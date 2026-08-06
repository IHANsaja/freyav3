"""
Pixel-perfect screen control — UI-Automation + OCR hybrid.

The old approach (core/vision.py) sent Gemini a shrunken screenshot and asked it to *guess*
pixel coordinates. That drifts: a few pixels off and the click misses. This module is the
"from scratch, advanced, pixel-perfect" replacement the user asked for:

  • Windows UI Automation (`uiautomation`) walks the focused window's real control tree and
    returns the TRUE bounding rectangle of every button/field/link. Clicking the exact center
    of a real rect is pixel-perfect by construction — no guessing.
  • Tesseract OCR (`pytesseract`) is the fallback for elements UIA can't name (canvas text,
    custom-drawn labels): we locate the on-screen text and click its real box.
  • The classic vision screenshot in core/vision.py stays as the last-resort fallback for
    games / pure-canvas apps where neither UIA nor OCR see anything.

Workflow for the model:  read_screen_elements()  →  click_element(index)  or  click_text("Save").
DPI-awareness is inherited from core/vision.py (imported for its real-pixel mouse helpers).
"""

import threading

from core.registry import tool, OBJ, P, STR, INT, BOOL

# Reuse the DPI-aware, real-pixel mouse helpers + the import side effect that sets
# PER_MONITOR_DPI_AWARE so UIA rects and click coords share one coordinate space.
from core.vision import click as _click_px, move_mouse as _move_px, get_screen_size

# Control types worth surfacing as clickable elements.
_INTERACTIVE = {
    "ButtonControl", "EditControl", "CheckBoxControl", "RadioButtonControl",
    "ComboBoxControl", "HyperlinkControl", "MenuItemControl", "ListItemControl",
    "TabItemControl", "TreeItemControl", "SplitButtonControl", "DocumentControl",
}

_lock = threading.Lock()
_element_map: list[dict] = []  # last scan: [{idx,name,type,cx,cy,rect}]


def _fx_rect(rect):
    """Fire the crimson 'core sync' shader lock-on at a real element rectangle."""
    try:
        from core import overlay
        overlay.show_element_effect(rect)
    except Exception:
        pass


def _fx_ctrl(ctrl):
    try:
        r = ctrl.BoundingRectangle
        _fx_rect((r.left, r.top, r.right, r.bottom))
    except Exception:
        pass


def _fx_scan():
    try:
        from core import overlay
        overlay.show_scan_effect()
    except Exception:
        pass


def _uia():
    import uiautomation as auto
    return auto


def _scan(max_elements: int = 60, max_depth: int = 14) -> list[dict]:
    """Walk the foreground window's control tree → real, clickable elements."""
    auto = _uia()
    elements: list[dict] = []
    sw, sh = get_screen_size()
    try:
        win = auto.GetForegroundControl()
    except Exception:
        win = auto.GetRootControl()
    if win is None:
        return elements

    idx = 0
    for ctrl, _depth in auto.WalkControl(win, includeTop=True, maxDepth=max_depth):
        if idx >= max_elements:
            break
        try:
            ctype = ctrl.ControlTypeName
            name = (ctrl.Name or "").strip()
            if ctype not in _INTERACTIVE and not name:
                continue
            r = ctrl.BoundingRectangle
            if r is None:
                continue
            w, h = r.right - r.left, r.bottom - r.top
            if w <= 0 or h <= 0 or w > sw or h > sh:
                continue  # zero-size or off-screen
            cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
            if not (0 <= cx <= sw and 0 <= cy <= sh):
                continue
            elements.append({
                "idx": idx,
                "name": name or "(unnamed)",
                "type": ctype.replace("Control", ""),
                "cx": cx, "cy": cy,
                "rect": (r.left, r.top, r.right, r.bottom),
            })
            idx += 1
        except Exception:
            continue
    return elements


# ══════════════════════════════════════════════
#  read_screen_elements
# ══════════════════════════════════════════════
@tool(
    "read_screen_elements",
    "Scan the focused window with Windows UI Automation and return a numbered list of the REAL "
    "clickable elements (buttons, fields, links) with their exact positions. Call this before "
    "click_element to act precisely without guessing coordinates from a screenshot.",
    OBJ(),
)
def read_screen_elements(args, ctx) -> str:
    _fx_scan()  # crimson sweep as she scans the screen
    try:
        elements = _scan()
    except Exception as e:
        return (f"UI Automation unavailable ({e}). Fall back to capture_screen + click(x,y).")
    with _lock:
        _element_map.clear()
        _element_map.extend(elements)
    if not elements:
        return ("No UI-Automation elements found in the focused window (likely a game or canvas). "
                "Use capture_screen and click by coordinates instead.")
    lines = [f"{e['idx']}: {e['type']} '{e['name']}' @({e['cx']},{e['cy']})" for e in elements]
    return "Clickable elements on screen:\n" + "\n".join(lines)


# ══════════════════════════════════════════════
#  click_element  (by index from the last scan)
# ══════════════════════════════════════════════
@tool(
    "click_element",
    "Click the exact center of an element from the most recent read_screen_elements scan, by its "
    "number. Pixel-perfect — uses the element's real bounding box.",
    OBJ({"index": P(INT, "The element number from read_screen_elements"),
         "double": P(BOOL, "True for a double-click"),
         "button": P(STR, "left, right or middle")}, ["index"]),
)
def click_element(args, ctx) -> str:
    idx = int(args.get("index", -1))
    with _lock:
        match = next((e for e in _element_map if e["idx"] == idx), None)
    if not match:
        return f"No element #{idx}. Run read_screen_elements first."
    _fx_rect(match["rect"])  # lock the crimson field onto the real element
    return _click_px(match["cx"], match["cy"],
                     args.get("button", "left"), bool(args.get("double", False))) + \
        f" (element '{match['name']}')"


# ══════════════════════════════════════════════
#  click_text  (UIA name match → OCR fallback)
# ══════════════════════════════════════════════
def _ocr_find(text: str):
    """Locate on-screen text with Tesseract; return its center or None."""
    import mss
    import pytesseract
    from PIL import Image
    target = text.lower().strip()
    with mss.mss() as sct:
        mon = sct.monitors[1]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    for i, word in enumerate(data["text"]):
        if word and target in word.lower():
            x = data["left"][i] + data["width"][i] // 2
            y = data["top"][i] + data["height"][i] // 2
            return x, y
    return None


@tool(
    "click_text",
    "Click an on-screen element by the text it shows (e.g. 'Save', 'Sign in'). Tries UI "
    "Automation first for a pixel-perfect hit, then OCR. No coordinates needed.",
    OBJ({"text": P(STR, "Visible label/text of the element to click"),
         "double": P(BOOL, "True for a double-click")}, ["text"]),
)
def click_text(args, ctx) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return "No text given to click."
    double = bool(args.get("double", False))

    # 1) UI Automation exact match (case-insensitive contains)
    try:
        for e in _scan():
            if text.lower() in e["name"].lower():
                _fx_rect(e["rect"])
                return _click_px(e["cx"], e["cy"], "left", double) + f" (matched '{e['name']}')"
    except Exception:
        pass

    # 2) OCR fallback
    try:
        hit = _ocr_find(text)
        if hit:
            return _click_px(hit[0], hit[1], "left", double) + f" (OCR matched '{text}')"
    except Exception as e:
        return f"Couldn't find '{text}' — UIA empty and OCR failed: {e}"

    return f"Couldn't find anything labelled '{text}' on screen. Try read_screen_elements."


# ══════════════════════════════════════════════
#  UI-AUTOMATION CONTROL PATTERNS
#  The real mechanism: instead of guessing coordinates and clicking, we ask the
#  control to perform its OWN action (Invoke / SetValue / Toggle / Select / Expand)
#  through the Windows accessibility API. This is exact, and it returns success so
#  Freya can verify her own work instead of asking "did I do it right?".
# ══════════════════════════════════════════════
def _rank(name: str, q: str) -> float:
    n = name.lower()
    if n == q:
        return 3.0
    if n.startswith(q):
        return 2.0
    if q in n:
        return 1.0
    return 0.0


def _find_control(query: str, max_depth: int = 18):
    """Search the foreground window's UIA tree for the best element matching `query`."""
    auto = _uia()
    try:
        win = auto.GetForegroundControl()
    except Exception:
        win = auto.GetRootControl()
    if win is None:
        return None, []
    q = query.lower().strip()
    best, best_score, names = None, 0.0, []
    for ctrl, _d in auto.WalkControl(win, includeTop=True, maxDepth=max_depth):
        try:
            name = (ctrl.Name or "").strip()
            if not name:
                continue
            score = _rank(name, q)
            if score <= 0:
                continue
            if ctrl.ControlTypeName in _INTERACTIVE:
                score += 0.5  # prefer something actually operable
            names.append(name)
            if score > best_score:
                best, best_score = ctrl, score
        except Exception:
            continue
    return best, names


def _pattern(ctrl, getter: str):
    """Safely fetch a UIA pattern (returns None if unsupported)."""
    try:
        fn = getattr(ctrl, getter, None)
        return fn() if fn else None
    except Exception:
        return None


def _do_invoke(ctrl) -> str:
    # Most reliable first: the control's own Invoke action, then Select, then a
    # real-clickable-point click (still exact — uses the element's true rect).
    p = _pattern(ctrl, "GetInvokePattern")
    if p is not None:
        p.Invoke()
        return "invoked"
    p = _pattern(ctrl, "GetSelectionItemPattern")
    if p is not None:
        p.Select()
        return "selected"
    try:
        ctrl.Click(simulateMove=False)  # uiautomation clicks the element's own point
        return "clicked"
    except Exception:
        r = ctrl.BoundingRectangle
        _click_px((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        return "clicked"


def _do_set(ctrl, value: str) -> str:
    p = _pattern(ctrl, "GetValuePattern")
    if p is not None:
        p.SetValue(value)
        return "set"
    try:
        ctrl.SetFocus()
        ctrl.SendKeys(value)
        return "typed"
    except Exception as e:
        return f"failed: {e}"


@tool(
    "find_element",
    "Search the focused window for an element by the text/label it shows (e.g. 'Save', 'address "
    "bar', 'Bold'). Reports whether it exists and what similar elements are around it. Use to "
    "locate something before acting on it — you never need coordinates.",
    OBJ({"query": P(STR, "Visible name/label of the element to find")}, ["query"]),
)
def find_element(args, ctx) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "What element should I look for?"
    try:
        ctrl, names = _find_control(query)
    except Exception as e:
        return f"UI Automation unavailable ({e})."
    if not names:
        return (f"Nothing labelled like '{query}' in the focused window. If it's another app, "
                "focus that window first (focus_window), or run read_screen_elements.")
    uniq = list(dict.fromkeys(names))[:8]
    if ctrl is not None:
        _fx_ctrl(ctrl)  # show what she located
        return (f"Found '{(ctrl.Name or '').strip()}'. Nearby matches: {', '.join(uniq)}. "
                "Use control_element to act on it.")
    return f"Possible matches: {', '.join(uniq)}"


@tool(
    "control_element",
    "Operate a UI element by its visible name using the Windows accessibility API — no coordinates, "
    "no guessing. This is your PRIMARY way to control apps. Actions: 'click' (press a button/link), "
    "'type' (set a field's text via value), 'toggle' (checkbox/switch), 'select' (list/menu item), "
    "'expand'/'collapse', 'focus'. It returns what happened so you can confirm it worked yourself "
    "instead of asking. Focus the right app window first if needed.",
    OBJ({"query": P(STR, "Visible name/label of the target element, e.g. 'Save', 'Search'"),
         "action": P(STR, "click, type, toggle, select, expand, collapse, or focus"),
         "value": P(STR, "Text to enter when action is 'type'")}, ["query", "action"]),
)
def control_element(args, ctx) -> str:
    query = (args.get("query") or "").strip()
    action = (args.get("action") or "click").lower().strip()
    value = str(args.get("value", ""))
    if not query:
        return "Tell me which element to control (by the text it shows)."
    try:
        ctrl, _names = _find_control(query)
    except Exception as e:
        return f"UI Automation unavailable ({e})."
    if ctrl is None:
        return (f"Couldn't find '{query}' in the focused window. Focus the right app "
                "(focus_window) or run read_screen_elements to see what's there.")
    name = (ctrl.Name or "").strip() or "(unnamed)"
    ctype = ctrl.ControlTypeName.replace("Control", "")
    _fx_ctrl(ctrl)  # crimson core-sync lock-on so the user sees exactly what she's operating
    try:
        if action in ("click", "invoke", "press", "open", "activate"):
            how = _do_invoke(ctrl)
            return f"Done — {how} the {ctype} '{name}'."
        if action in ("type", "set", "enter", "write", "fill"):
            how = _do_set(ctrl, value)
            if how.startswith("failed"):
                return f"Couldn't type into '{name}': {how}"
            return f"Done — {how} '{value}' into the {ctype} '{name}'."
        if action == "toggle":
            p = _pattern(ctrl, "GetTogglePattern")
            if p is None:
                return f"'{name}' isn't toggleable."
            p.Toggle()
            return f"Toggled '{name}' (now {p.ToggleState})."
        if action == "select":
            p = _pattern(ctrl, "GetSelectionItemPattern")
            if p is None:
                return f"'{name}' isn't selectable."
            p.Select()
            return f"Selected '{name}'."
        if action in ("expand", "collapse"):
            p = _pattern(ctrl, "GetExpandCollapsePattern")
            if p is None:
                return f"'{name}' can't expand/collapse."
            p.Expand() if action == "expand" else p.Collapse()
            return f"{action.capitalize()}ed '{name}'."
        if action == "focus":
            ctrl.SetFocus()
            return f"Focused '{name}'."
        return f"Unknown action '{action}'. Use click, type, toggle, select, expand, collapse or focus."
    except Exception as e:
        return f"Couldn't {action} '{name}': {e}"
