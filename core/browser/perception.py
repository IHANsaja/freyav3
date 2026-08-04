"""
The eyes — turn a live page into something a language model can reason about.

A raw DOM is useless to an LLM (megabytes of divs) and a raw screenshot is
useless for acting (no coordinates you can trust). So we do what a person
effectively does: pick out the things on this page that can be *interacted
with*, number them, and read the prose around them.

The output of `perceive()` is a PageView:

    [3] <input> "Search the web"           ← typeable, with a real screen box
    [4] <button> "Search"
    [7] <a> "Transaction processing — Wikipedia"  → en.wikipedia.org/...

Indices are per-snapshot and re-issued after every action, because the page may
have re-rendered underneath us. The agent never invents a selector; it picks a
number it can see, and we translate that back to a point on screen for the
cursor to travel to. That indirection is what keeps clicks honest.

Shadow DOM and same-origin iframes are walked too — cookie banners and embedded
search boxes live there, and a browser that can't dismiss a cookie banner can't
browse.
"""

from dataclasses import dataclass, field

# ── The in-page scanner ────────────────────────────────────────────────────
# Runs inside the page. Kept dependency-free and defensive: it executes on
# hostile third-party markup, so anything that throws is skipped rather than
# allowed to abort the scan.
_SCAN_JS = r"""
(maxElements) => {
  const INTERACTIVE_TAGS = new Set(['a','button','input','select','textarea','summary','label','option']);
  const INTERACTIVE_ROLES = new Set([
    'button','link','checkbox','radio','textbox','searchbox','combobox','listbox',
    'option','menuitem','menuitemcheckbox','menuitemradio','tab','switch','slider','spinbutton'
  ]);

  const out = [];
  const seen = new Set();

  function isVisible(el, rect) {
    if (!rect || rect.width < 2 || rect.height < 2) return false;
    const s = window.getComputedStyle(el);
    if (!s) return false;
    if (s.visibility === 'hidden' || s.display === 'none') return false;
    if (parseFloat(s.opacity || '1') < 0.08) return false;
    if (el.hasAttribute('disabled') || el.getAttribute('aria-hidden') === 'true') return false;
    return true;
  }

  function label(el) {
    const pick = (v) => (v || '').replace(/\s+/g, ' ').trim();
    let t = pick(el.getAttribute('aria-label'));
    if (t) return t;
    if (el.tagName === 'INPUT') {
      t = pick(el.getAttribute('placeholder')) || pick(el.value) ||
          pick(el.getAttribute('name')) || pick(el.getAttribute('type'));
      if (t) return t;
    }
    if (el.getAttribute('aria-labelledby')) {
      const ref = document.getElementById(el.getAttribute('aria-labelledby'));
      if (ref) { t = pick(ref.innerText); if (t) return t; }
    }
    t = pick(el.innerText || el.textContent);
    if (t) return t.slice(0, 160);
    return pick(el.getAttribute('title')) || pick(el.getAttribute('alt')) || '';
  }

  function isInteractive(el) {
    const tag = el.tagName ? el.tagName.toLowerCase() : '';
    if (INTERACTIVE_TAGS.has(tag)) return true;
    const role = (el.getAttribute && el.getAttribute('role') || '').toLowerCase();
    if (INTERACTIVE_ROLES.has(role)) return true;
    if (el.hasAttribute && el.hasAttribute('contenteditable') &&
        el.getAttribute('contenteditable') !== 'false') return true;
    if (el.hasAttribute && el.hasAttribute('onclick')) return true;
    const tabindex = el.getAttribute && el.getAttribute('tabindex');
    if (tabindex !== null && tabindex !== undefined && tabindex !== '-1') return true;
    // A pointer cursor is the web's universal "this is clickable" convention,
    // used by every div-as-button on the internet.
    try {
      if (window.getComputedStyle(el).cursor === 'pointer' &&
          el.children.length < 4 && (el.innerText || '').trim().length > 0) return true;
    } catch (e) {}
    return false;
  }

  function kind(el) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'textarea') return 'type';
    if (tag === 'select') return 'select';
    if (tag === 'input') {
      if (['checkbox','radio','submit','button','image','reset','file'].includes(type)) return 'click';
      return 'type';
    }
    if (el.hasAttribute('contenteditable') && el.getAttribute('contenteditable') !== 'false') return 'type';
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (role === 'textbox' || role === 'searchbox') return 'type';
    return 'click';
  }

  function walk(root, depth) {
    if (depth > 40 || out.length >= maxElements) return;
    let nodes;
    try { nodes = root.querySelectorAll('*'); } catch (e) { return; }
    for (const el of nodes) {
      if (out.length >= maxElements) return;
      try {
        if (el.shadowRoot) walk(el.shadowRoot, depth + 1);
        if (!isInteractive(el)) continue;
        if (seen.has(el)) continue;
        const rect = el.getBoundingClientRect();
        if (!isVisible(el, rect)) continue;
        seen.add(el);
        out.push({
          tag: el.tagName.toLowerCase(),
          type: (el.getAttribute('type') || '').toLowerCase(),
          action: kind(el),
          text: label(el),
          href: el.getAttribute('href') || '',
          value: (el.value !== undefined && typeof el.value === 'string') ? el.value.slice(0, 80) : '',
          checked: el.checked === true,
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
          w: rect.width,
          h: rect.height,
          inViewport: rect.bottom > 0 && rect.top < window.innerHeight &&
                      rect.right > 0 && rect.left < window.innerWidth
        });
      } catch (e) { /* hostile node — skip it, keep scanning */ }
    }
  }

  walk(document, 0);

  // Readable prose, with the page furniture stripped out.
  let text = '';
  try {
    const clone = document.body.cloneNode(true);
    clone.querySelectorAll('script,style,noscript,svg,nav,footer,header,aside,form')
         .forEach(n => n.remove());
    text = (clone.innerText || '').replace(/\n{3,}/g, '\n\n').replace(/[ \t]{2,}/g, ' ').trim();
  } catch (e) {
    text = (document.body && document.body.innerText || '').trim();
  }

  return {
    url: location.href,
    title: document.title || '',
    text: text,
    elements: out,
    scrollY: window.scrollY,
    viewportHeight: window.innerHeight,
    pageHeight: Math.max(document.body ? document.body.scrollHeight : 0,
                         document.documentElement ? document.documentElement.scrollHeight : 0)
  };
}
"""


@dataclass
class Element:
    index: int
    tag: str
    action: str          # "click" | "type" | "select"
    text: str
    href: str = ""
    value: str = ""
    type: str = ""
    checked: bool = False
    x: float = 0.0       # viewport coordinates, already frame-offset
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    in_viewport: bool = True
    frame_path: str = "" # which frame it lives in (for keyboard focus)

    def render(self) -> str:
        bits = [f"[{self.index}]", f"<{self.tag}>"]
        if self.text:
            bits.append(f'"{self.text[:90]}"')
        if self.action == "type":
            bits.append("(typeable)" + (f" current={self.value[:30]!r}" if self.value else ""))
        if self.href and not self.href.startswith("javascript"):
            # ASCII arrow deliberately: this string reaches Windows consoles
            # that are still cp1252, where a real arrow raises UnicodeEncodeError.
            bits.append(f"-> {self.href[:70]}")
        if not self.in_viewport:
            bits.append("(off-screen — scroll first)")
        return " ".join(bits)


@dataclass
class PageView:
    url: str = ""
    title: str = ""
    text: str = ""
    elements: list[Element] = field(default_factory=list)
    scroll_y: int = 0
    viewport_height: int = 0
    page_height: int = 0

    @property
    def scroll_position(self) -> str:
        if self.page_height <= self.viewport_height:
            return "whole page visible"
        pct = int(100 * self.scroll_y / max(1, self.page_height - self.viewport_height))
        return f"{pct}% down the page"

    def get(self, index: int) -> Element | None:
        for el in self.elements:
            if el.index == index:
                return el
        return None

    def render(self, max_text: int = 3000, max_elements: int = 90) -> str:
        """The page as the agent sees it."""
        lines = [
            f"URL: {self.url}",
            f"TITLE: {self.title}",
            f"POSITION: {self.scroll_position}",
            "",
            "THINGS YOU CAN INTERACT WITH (use the number):",
        ]
        shown = [e for e in self.elements if e.in_viewport][:max_elements]
        if len(shown) < max_elements:
            shown += [e for e in self.elements if not e.in_viewport][:max_elements - len(shown)]
        lines += [f"  {e.render()}" for e in shown] or ["  (nothing interactive found)"]
        lines += ["", "PAGE TEXT:", self.text[:max_text] or "(no readable text)"]
        if len(self.text) > max_text:
            lines.append(f"... [{len(self.text) - max_text} more characters — scroll to read on]")
        return "\n".join(lines)


async def perceive(page, max_elements: int = 140) -> PageView:
    """Scan the page and every reachable child frame into one indexed view."""
    try:
        raw = await page.evaluate(_SCAN_JS, max_elements)
    except Exception as e:
        return PageView(url=page.url, title="", text=f"(could not read the page: {e})")

    view = PageView(
        url=raw.get("url") or page.url,
        title=raw.get("title", ""),
        text=raw.get("text", ""),
        scroll_y=int(raw.get("scrollY") or 0),
        viewport_height=int(raw.get("viewportHeight") or 0),
        page_height=int(raw.get("pageHeight") or 0),
    )

    idx = 0
    for e in raw.get("elements", []):
        view.elements.append(_to_element(e, idx))
        idx += 1

    # Child frames: cookie walls, consent dialogs and embedded widgets live
    # here. Their coordinates are frame-local, so shift them into page space.
    for frame in page.frames:
        if frame is page.main_frame or idx >= max_elements:
            continue
        try:
            handle = await frame.frame_element()
            box = await handle.bounding_box()
            if not box:
                continue
            sub = await frame.evaluate(_SCAN_JS, max_elements - idx)
        except Exception:
            continue
        for e in sub.get("elements", []):
            e["x"] += box["x"]
            e["y"] += box["y"]
            view.elements.append(_to_element(e, idx, frame_path=frame.url[:120]))
            idx += 1
        extra = (sub.get("text") or "").strip()
        if extra and len(extra) > 40:
            view.text += f"\n\n[embedded frame]\n{extra[:1200]}"

    return view


def _to_element(e: dict, index: int, frame_path: str = "") -> Element:
    return Element(
        index=index,
        tag=e.get("tag", "div"),
        action=e.get("action", "click"),
        text=(e.get("text") or "").strip(),
        href=e.get("href") or "",
        value=e.get("value") or "",
        type=e.get("type") or "",
        checked=bool(e.get("checked")),
        x=float(e.get("x") or 0),
        y=float(e.get("y") or 0),
        w=float(e.get("w") or 0),
        h=float(e.get("h") or 0),
        in_viewport=bool(e.get("inViewport", True)),
        frame_path=frame_path,
    )
