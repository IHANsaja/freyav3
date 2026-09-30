"""Answering and ending calls in WhatsApp desktop and Phone Link.

Uses UI Automation (core/screen.py) on the call app's own windows, focused or
not - an incoming-call popup usually is not. Button labels differ by app
version and language, so they are overridable in config voice_clone.apps.
Every result says plainly whether it worked; nothing is assumed.
"""
import time
from dataclasses import dataclass, field

_CALL_TTL_S = 20 * 60


@dataclass
class AppSpec:
    name: str
    processes: list
    titles: list
    accept: list
    hangup: list


APPS = {
    "whatsapp": AppSpec("WhatsApp", ["whatsapp.exe", "whatsapp.root.exe"], ["whatsapp"],
                        ["Accept", "Answer", "Accept call"], ["End call", "Hang up", "Leave"]),
    "phone_link": AppSpec("Phone Link", ["phoneexperiencehost.exe"], ["phone link", "incoming call"],
                          ["Answer", "Accept", "Answer call"], ["End call", "Hang up"]),
}


@dataclass
class CallState:
    active: bool = False
    app: str | None = None
    started_at: float = 0.0
    lines: int = 0
    first_line_approved: bool = False
    history: list = field(default_factory=list)

    def start(self, app: str):
        self.active, self.app, self.started_at = True, app, time.time()
        self.lines, self.first_line_approved = 0, False

    def end(self):
        self.active, self.app = False, None
        self.first_line_approved = False

    def is_active(self) -> bool:
        if self.active and time.time() - self.started_at > _CALL_TTL_S:
            self.end()
        return self.active


state = CallState()


@dataclass
class CallResult:
    ok: bool
    app: str | None
    message: str


def _specs(app: str, config: dict) -> list[tuple[str, AppSpec]]:
    from core.voice_clone import settings
    overrides = settings(config).get("apps") or {}
    names = list(APPS) if app in (None, "", "auto") else [app]
    out = []
    for name in names:
        base = APPS.get(name)
        if base is None:
            continue
        extra = overrides.get(name) or {}
        out.append((name, AppSpec(base.name, base.processes, base.titles,
                                  list(extra.get("accept") or base.accept),
                                  list(extra.get("hangup") or base.hangup))))
    return out


def _find(labels: list, windows: list):
    from core import screen
    for win in windows:
        for label in labels:
            try:
                ctrl, _ = screen._find_control(label, root=win)
            except Exception:
                ctrl = None
            if ctrl is not None and (ctrl.Name or "").strip().lower().startswith(label.lower()):
                return win, ctrl
    return None, None


def normalize_app(app: str | None) -> str:
    app = (app or "auto").lower().replace(" ", "_")
    return {"phone": "phone_link", "phonelink": "phone_link", "whats_app": "whatsapp"}.get(app, app)


def answer(app: str, config: dict) -> CallResult:
    """Click the incoming call's answer button. Blocking (UI Automation)."""
    from core import screen
    app = normalize_app(app)
    if app not in ("auto", *APPS):
        return CallResult(False, None, f"I can answer WhatsApp and Phone Link calls, not '{app}'.")
    for name, spec in _specs(app, config):
        windows = screen.find_top_windows(spec.processes, spec.titles)
        win, ctrl = _find(spec.accept, windows)
        if ctrl is None:
            continue
        try:
            screen._do_invoke(ctrl)
        except Exception as e:
            return CallResult(False, name, f"I found the {spec.name} answer button but couldn't press it: {e}")
        time.sleep(0.8)
        still, _ = _find(spec.accept, [win])
        hang, _ = _find(spec.hangup, screen.find_top_windows(spec.processes, spec.titles))
        if still is not None and hang is None:
            return CallResult(False, name, f"I pressed answer in {spec.name}, but the call still looks unanswered.")
        state.start(name)
        return CallResult(True, name, f"Answered the {spec.name} call.")
    which = "WhatsApp or Phone Link" if app == "auto" else APPS[app].name
    return CallResult(False, None, f"I don't see an incoming {which} call to answer.")


def hang_up(app: str | None, config: dict) -> CallResult:
    from core import screen
    app = normalize_app(app or state.app)
    for name, spec in _specs(app, config):
        _, ctrl = _find(spec.hangup, screen.find_top_windows(spec.processes, spec.titles))
        if ctrl is None:
            continue
        try:
            screen._do_invoke(ctrl)
        except Exception as e:
            return CallResult(False, name, f"I couldn't press end call in {spec.name}: {e}")
        state.end()
        return CallResult(True, name, f"Ended the {spec.name} call.")
    state.end()
    return CallResult(False, None, "I couldn't find an active call to end - it may have ended already.")
