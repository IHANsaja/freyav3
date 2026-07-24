"""
Error plumbing — one consistent way to log and describe failures across the backend.

Before this, error handling was ad hoc: some paths swallowed exceptions with a bare
`except Exception: pass` (losing the failure entirely), some printed a one-line string
with no traceback, and the FastAPI/WebSocket layer had no shared shape at all. This
module gives every layer the same two tools:

  • `log_error(where, exc)` — record a failure WITH its traceback under a named logger,
    so problems are actually diagnosable instead of vanishing or printing a cryptic line.
  • `error_payload(exc)` — a stable, safe dict describing a failure for the client. It
    never leaks internals in production: the human-facing `message` is generic unless
    the exception is explicitly user-facing (`UserFacingError`), while `detail` carries
    the real text only when FREYA_DEBUG is set.

Keeping this in one place means the WebSocket loop, the REST endpoints and the tool
layer all report failures identically, and changing that policy is a one-file edit.
"""

import logging
import os
import sys
import traceback

DEBUG = os.getenv("FREYA_DEBUG", "").lower() in ("1", "true", "yes", "on")

# Single named logger for the whole backend. Configured once, here, so importing
# this module is all any caller needs. Level follows FREYA_DEBUG. The failing
# site is carried in the message text (see log_error) rather than a custom
# LogRecord field — the latter collides with logging's `extra=` machinery.
logger = logging.getLogger("freya")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] freya: %(message)s", datefmt="%H:%M:%S",
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)
    logger.propagate = False


class UserFacingError(Exception):
    """Raise for a failure whose message is safe and useful to show the user.

    The client sees this message verbatim (e.g. "That file is outside your
    allowed folders."). Everything else is reported generically so internal
    details never leak to the browser.
    """


def log_error(where: str, exc: BaseException, *, level: int = logging.ERROR) -> None:
    """Log `exc` with its traceback, tagged with a short location string.

    `where` is a stable label for the failing site ("ws.gesture_touch",
    "endpoint.config", "tool.web_search") so logs can be grepped by area.
    """
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logger.log(level, "[%s] %s: %s\n%s", where, type(exc).__name__, exc, tb)


def error_payload(exc: BaseException, *, code: str = "internal_error") -> dict:
    """A safe, stable dict describing a failure for a client.

    `message` is generic unless the exception is a UserFacingError; `detail`
    (the raw text) is included only in debug mode. The shape is always the same
    so the frontend can rely on it.
    """
    user_facing = isinstance(exc, UserFacingError)
    message = str(exc) if user_facing else "Something went wrong on Freya's side."
    payload = {"error": True, "code": "user_error" if user_facing else code, "message": message}
    if DEBUG and not user_facing:
        payload["detail"] = f"{type(exc).__name__}: {exc}"
    return payload
