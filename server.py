import asyncio
import json
import logging
import os
import sys
import time
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketState

from core.errors import log_error, error_payload, UserFacingError, logger
from core.resilience import Backoff, guard, aguard, health, OK, DEGRADED, RECOVERING, DOWN

# On Windows, Playwright launches Chromium via create_subprocess_exec, which only works
# on the Proactor event loop. uvicorn may otherwise pick a Selector loop, and Chromium
# then never starts. Force Proactor so subprocess spawning works the same way it does in
# main.py's asyncio.run path. Note core/browser runs its own loop on its own thread —
# this policy is process-wide, so that loop inherits Proactor from here.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Piped or redirected output (the launcher, a log file) defaults to cp1252 on
# Windows, and printing an emoji or Sinhala text then raises. Those prints sit
# inside the live tool executor, so a tool that succeeded was reported to the
# model as failed. Logging must never be able to fail a tool.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Browsers attach every cookie stored for 'localhost' to the WebSocket handshake
# (the cookie jar is shared across ALL localhost ports, so other dev tools count).
# The websockets library rejects any header line over 8 KiB, which uvicorn surfaces
# as an endless "connection rejected (400 Bad Request)" loop. Raise the limits so a
# fat cookie jar can't break the dashboard connection. Note: the effective cap is
# 32 KiB — the legacy reader's StreamReader line buffer (read_limit // 2) — which
# is still 4x the default failure point. If a handshake ever exceeds that, clear
# cookies for 'localhost' in the browser.
os.environ.setdefault("WEBSOCKETS_MAX_LINE_LENGTH", str(64 * 1024))
os.environ.setdefault("WEBSOCKETS_MAX_NUM_HEADERS", "512")
try:
    import websockets.http11 as _ws_http11
    _ws_http11.MAX_LINE_LENGTH = 64 * 1024
    _ws_http11.MAX_NUM_HEADERS = 512
    # uvicorn's default 'websockets' implementation parses the handshake with the
    # legacy module, which has its own copies of these constants.
    import websockets.legacy.http as _ws_legacy_http
    _ws_legacy_http.MAX_LINE_LENGTH = 64 * 1024
    _ws_legacy_http.MAX_NUM_HEADERS = 512
except Exception:
    pass

from contextlib import asynccontextmanager

from config import load_config, get_api_key, get_active_model, get_active_voice, get_personality
from config import get_mode_personality, get_mode_model, get_mode_voice, get_mode_theme
from core.audio import MicStream, SpeakerStream
from core.events import bus
from core.memory import load_memory, build_system_prompt, update_memory, TranscriptCollector
from core.model import FreyaModel, is_rotation
from core.live_protocol import LiveRoute, ModeChange, ThinkingTaskFailed, is_auth_failure, AUTH_HELP


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Claim this loop as "home" before anything can publish. Missions and
    # sub-agents run on the background loop and marshal their events back here;
    # without this they'd have nowhere to send them until a voice session began.
    from core import background
    background.set_main_loop()
    # The bus is the single transport for all runtime.emit() events. Subscribing
    # here (not per-session) means mission/approval/suggestion events reach the
    # dashboard even while no voice session is running.
    unsubscribe = bus.subscribe(lambda event: broadcast(event.serialize()))
    # Desktop popup layer — mirrors `card` / `image` events flagged `popup` onto
    # always-on-top toasts, so Freya can surface what she found while the user is
    # working in a completely different window (dashboard closed, no voice session).
    try:
        from core import desktop_popup
        detach_popups = desktop_popup.attach_to_bus(load_config())
    except Exception as e:
        print(f"  desktop popups unavailable: {e}")
        detach_popups = lambda: None
    try:
        from core import systemone
        print(f"  {systemone.describe_status()}")
    except Exception:
        pass
    # Activity pill: approval waits arrive on the bus, not through a tool call.
    try:
        from core import activity_overlay
        activity_overlay.configure(load_config())
        detach_activity = activity_overlay.attach_to_bus()
    except Exception as e:
        print(f"  activity overlay unavailable: {e}")
        detach_activity = lambda: None
    # Import any legacy markdown memory into the structured store up front so
    # the Memory panel is populated before the first voice session.
    try:
        from core.memory import _migrate_markdown_if_needed
        await asyncio.get_event_loop().run_in_executor(None, _migrate_markdown_if_needed)
    except Exception as e:
        print(f"  memory migration check failed: {e}")
    yield
    unsubscribe()
    detach_popups()
    detach_activity()
    try:
        from core.voice_clone import passthrough
        passthrough.stop()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)
from core.trading.api import router as trading_router
app.include_router(trading_router)

# Defense-in-depth rate limit for "gesture_touch" WS messages — the frontend
# already debounces gesture reactions, but the server shouldn't trust a
# client to enforce that. See the /ws gesture_touch handler below.
_last_gesture_touch_ts = 0.0

# The dashboard is the only browser origin allowed in. CORS covers fetch();
# WebSockets ignore CORS entirely, so /ws checks the same list itself —
# otherwise any page open in the browser could connect and approve actions.
# Its port is picked at start (config/ports.py), so the list follows it.
from config.ports import api_port, dashboard_origins
DASHBOARD_ORIGINS = dashboard_origins()

# Allow Next.js dev server to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=DASHBOARD_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global HTTP exception handlers ──
# Any endpoint that raises now returns a consistent JSON error shape and gets
# its traceback logged, instead of FastAPI's opaque default 500 (or a leaked
# stack in debug). A handler can `raise UserFacingError("...")` to surface a
# safe, specific message to the caller; anything else is reported generically.
@app.exception_handler(UserFacingError)
async def _user_facing_handler(request: Request, exc: UserFacingError):
    log_error(f"endpoint.{request.url.path}", exc, level=logging.WARNING)
    return JSONResponse(status_code=400, content=error_payload(exc))


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": True, "code": "invalid_request",
                 "message": "The request was malformed.", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception):
    log_error(f"endpoint.{request.url.path}", exc)
    return JSONResponse(status_code=500, content=error_payload(exc))

# ── Global state ──
freya_task = None
freya_running = False
# Unix seconds when the current voice session started; None while stopped. The
# dashboard's uptime readout is derived from this rather than from page-load
# time, so it reports the SESSION's real age instead of the browser tab's.
freya_started_at: float | None = None
connected_clients: list[WebSocket] = []
# The live session's speaker, so /stop can silence it before cancelling.
_active_speaker = None


# ══════════════════════════════════════════════
#  BROADCAST  — send a message to all UI clients
# ══════════════════════════════════════════════
async def broadcast(message: dict):
    for client, queue in list(_client_queues.items()):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            _client_queues.pop(client, None)
            writer = _client_writers.pop(client, None)
            if writer:
                writer.cancel()
            asyncio.create_task(client.close(code=1013))


_client_queues: dict[WebSocket, asyncio.Queue] = {}
_client_writers: dict[WebSocket, asyncio.Task] = {}


async def _write_client(client, queue):
    try:
        while True:
            await asyncio.wait_for(client.send_json(await queue.get()), 5)
    except (Exception, asyncio.CancelledError):
        _client_queues.pop(client, None)
        if client in connected_clients:
            connected_clients.remove(client)
        try:
            await asyncio.wait_for(client.close(code=1013),1)
        except Exception:
            pass


# ══════════════════════════════════════════════
#  FREYA RUNNER
# ══════════════════════════════════════════════
async def run_freya():
    global freya_running

    config = load_config()
    api_key = get_api_key()
    model_id = get_mode_model(config)
    voice = get_mode_voice(config)
    base_personality = get_personality(config)
    # Memory is an enhancement, not a precondition: a locked or corrupt store
    # used to end the session before it began. She starts without it instead.
    memory = guard("session.memory", load_memory, config, fallback="")
    if memory == "":
        health.set("memory", DEGRADED, "Memory unavailable this session; running without it")
    personality = _build_personality(config, base_personality, memory)
    transcript = TranscriptCollector()

    mic, speaker = _open_audio(config)
    global _active_speaker
    _active_speaker = speaker

    # Learn the machine on first run (or refresh a stale index). Background
    # thread, so the dashboard comes up straight away.
    try:
        from core.machine_index import ensure_index
        ensure_index(config)
    except Exception as e:
        print(f"  Machine index unavailable: {e}")

    await broadcast({"type": "state", "value": "listening"})
    await broadcast({"type": "mode", "value": config.get("active_mode", "default")})
    await broadcast({"type": "persona", "payload": {
        "mode": config.get("active_mode", "default"),
        "voice": voice,
        "theme": get_mode_theme(config),
    }})

    # Patch FreyaModel to broadcast events to UI
    class FreyaModelWithBroadcast(FreyaModel):
        async def on_transcript(self, speaker_name: str, text: str):
            # NOTE: FreyaModel.run() already records to the transcript
            # collector; adding it here too caused duplicate memory entries.
            if speaker_name == "Freya":
                # Dashboard not being looked at → her reply also pops up as a
                # desktop card, so she can be followed from any window.
                try:
                    from core import desktop_popup
                    desktop_popup.say(text)
                except Exception:
                    pass
            await broadcast({
                "type": "transcript",
                "speaker": speaker_name,
                "text": text
            })

        async def on_tool(self, name: str, args: dict, result: str):
            await broadcast({"type": "tool", "name": name, "args": args, "result": result})
            if result.startswith("MODE_SWITCHED:"):
                new_mode = result.split(":")[1]
                await broadcast({"type": "mode", "value": new_mode})
                # The runner handles ModeChange without losing the transcript.

        async def on_state(self, value: str):
            await broadcast({"type": "state", "value": value})

        # NOTE: no on_event override — generic events (agent / mcp / schedule /
        # ambient / browser / speech / mic / …) now flow runtime.emit → event bus
        # → the broadcast subscriber registered in lifespan().

    consecutive_failures = 0
    # Past this many failures in a row the retries don't stop — they slow down
    # to the backoff cap and the dashboard is told the link is unstable.
    noisy_after = 5
    backoff = Backoff(base=2, cap=60)
    resume_handle = None
    continue_task = False
    route = LiveRoute(model_id, config)

    try:
        while freya_running:
            await broadcast({"type": "persona", "payload": {
                "mode": config.get("active_mode", "default"), "voice": voice,
                "theme": get_mode_theme(config),
            }})
            freya = FreyaModelWithBroadcast(
                api_key=api_key,
                model_id=route.model,
                voice=voice,
                personality=personality,
                config=config,
                transcript=transcript,
                resume_handle=resume_handle,
                continue_task=continue_task,
            )
            session_began = time.monotonic()
            try:
                health.set("live", RECOVERING if consecutive_failures else OK,
                           f"Reconnecting to {route.model}" if consecutive_failures else "")
                await freya.run(mic, speaker)
                if not freya_running:
                    break           # the user stopped her: a real, clean end
                # The server closed the socket without an error or a GoAway.
                # That used to end the session silently while the dashboard
                # still said LISTENING. The user never asked to stop, so it is
                # a disconnect like any other: resume and carry on.
                resume_handle = freya.resume_handle
                raise ConnectionResetError("live session closed by the server")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Keep the server-side conversation state across the reconnect.
                resume_handle = freya.resume_handle
                # A session that ran a good while before failing was healthy:
                # this failure starts a new streak rather than extending one.
                if time.monotonic() - session_began > 60:
                    consecutive_failures = 0
                    backoff.reset()

                if is_auth_failure(e):
                    # A refused key fails identically on every retry, so don't
                    # hammer the API — but don't give up either: wait for the key
                    # to change (settings or .env) and carry straight on.
                    print(f"Freya session error: {AUTH_HELP} ({e})")
                    health.set("live", DOWN, "API key refused — waiting for a new key")
                    await broadcast({"type": "transcript", "speaker": "Freya",
                                     "text": f"[SESSION ERROR] {AUTH_HELP} I'll reconnect by myself "
                                             "as soon as the key changes."})
                    if not await _wait_for_new_key(api_key):
                        break
                    api_key = get_api_key()
                    resume_handle = None
                    consecutive_failures = 0
                    backoff.reset()
                    continue
                if freya.connected and not isinstance(e, ModeChange):
                    continue_task = False
                fallback = None if isinstance(e, ModeChange) else route.fallback(
                    e, repeated=consecutive_failures + 1)
                if isinstance(e, ModeChange):
                    resume_handle = None  # Model/personality changed: never reuse its token.
                    continue_task = str(e) == "complex_tasks"
                    consecutive_failures = 0
                elif fallback:
                    resume_handle = None
                    # Retry an unstarted handoff, never replay a live action.
                    # A dropped thinking task resumes on the new model; the recap shows what already ran.
                    continue_task = isinstance(e, ThinkingTaskFailed) or (continue_task and not freya.connected)
                    print(f"Live model unavailable; falling back to {fallback}.")
                    await broadcast({"type": "transcript", "speaker": "Freya",
                                     "text": f"[Using fallback voice model: {fallback}]"})
                    await asyncio.sleep(1)
                elif is_rotation(e):
                    # Routine session rotation — reconnect silently and fast.
                    # No UI noise: from the user's side nothing happened.
                    print("Rotating Freya session (context preserved).")
                    await asyncio.sleep(0.5)
                else:
                    consecutive_failures += 1
                    delay = backoff.next()
                    print(f"Freya session error (attempt {consecutive_failures}, retrying in "
                          f"{delay:.0f}s): {e}")
                    health.set("live", RECOVERING,
                               f"Connection lost ({type(e).__name__}); retry {consecutive_failures} in {delay:.0f}s")
                    note = (f"[Connection lost. Reconnecting to Gemini... Attempt {consecutive_failures}]"
                            if consecutive_failures < noisy_after else
                            f"[Connection lost. Link unstable — still reconnecting every {delay:.0f}s. "
                            "Check the network or the API quota.]")
                    # Say it once per streak when it's noisy, not every minute.
                    if consecutive_failures <= noisy_after:
                        await broadcast({"type": "transcript", "speaker": "Freya", "text": note})
                    await _sleep_while_running(delay)

                # Reload config and keys in case they were updated. Guarded: a
                # half-written config file must not end the session it configures.
                config = guard("session.reload_config", load_config, fallback=config)
                api_key = guard("session.reload_key", get_api_key, fallback=api_key) or api_key
                previous_model = route.model
                model_id = guard("session.reload_model", get_mode_model, config, fallback=model_id)
                route.configure(model_id, config)
                if route.model != previous_model:
                    resume_handle = None
                voice = guard("session.reload_voice", get_mode_voice, config, fallback=voice)
                base_personality = guard("session.reload_personality", get_personality, config,
                                         fallback=base_personality)
                personality = _build_personality(config, base_personality, memory, fallback=personality)
    finally:
        freya_running = False
        if _active_speaker is speaker:
            _active_speaker = None
        # Every cleanup step is independent: one failing must not skip the rest
        # (a mic that errors on close used to leave the speaker open and the
        # session's memory unsaved).
        guard("session.cleanup.mic", mic.stop)
        guard("session.cleanup.speaker", speaker.stop)
        try:
            from core.mcp_client import mcp_manager
            await aguard("session.cleanup.mcp", mcp_manager.stop(), timeout=10)
        except Exception:
            pass
        try:
            from core.browser.driver import shutdown_browser
            guard("session.cleanup.browser", shutdown_browser)
        except Exception:
            pass
        health.set("live", OK, "")
        await aguard("session.cleanup.broadcast", broadcast({"type": "state", "value": "idle"}))
        await aguard("session.cleanup.memory", update_memory(api_key, transcript.get(), memory),
                     timeout=120)


def _build_personality(config, base_personality, memory, fallback=None) -> str:
    """The system prompt, falling back rather than failing: first to the prompt
    without memory, then to whatever worked last, then to the base personality."""
    try:
        return build_system_prompt(get_mode_personality(config, base_personality), memory)
    except Exception as exc:
        log_error("session.personality", exc, level=logging.WARNING)
    try:
        prompt = build_system_prompt(get_mode_personality(config, base_personality), "")
        health.set("memory", DEGRADED, "Memory left out of the prompt after an error")
        return prompt
    except Exception as exc:
        log_error("session.personality.no_memory", exc, level=logging.WARNING)
    return fallback or base_personality or "You are Freyja, a warm and capable voice assistant."


class AudioUnavailable(RuntimeError):
    """Neither the saved device nor the Windows default could be opened."""


def _open_audio(config):
    """Open the mic and speaker, falling back to the Windows default device.

    A saved device that was unplugged, renamed or grabbed exclusively by another
    app used to raise straight out of run_freya and end the session. Now it
    degrades to the default; only when that fails too is the session retried
    by the supervisor (the device may come back — a headset being reconnected).
    """
    audio = config.get("audio", {}) or {}
    opened = {}
    for side, cls, part in (("input", MicStream, "mic"), ("output", SpeakerStream, "speaker")):
        saved = (audio.get(f"{side}_device_index"), audio.get(f"{side}_device_name"))
        choices = [saved] + ([(None, None)] if saved != (None, None) else [])
        last_exc = None
        for index, name in choices:
            stream = None
            try:
                stream = cls(device_index=index, device_name=name)
                stream.start()
            except Exception as exc:
                last_exc = exc
                log_error(f"audio.open.{side}", exc, level=logging.WARNING)
                if stream is not None:
                    guard(f"audio.close.{side}", stream.stop)
                continue
            opened[side] = stream
            if (index, name) == saved:
                health.ok(part)
            else:
                health.set(part, DEGRADED, f"Saved {side} device failed; using the Windows default")
            break
        if side not in opened:
            health.set(part, DOWN, f"No {side} device could be opened: {last_exc}")
            for stream in opened.values():
                guard("audio.close", stream.stop)
            raise AudioUnavailable(f"no usable {side} device ({last_exc})")
    return opened["input"], opened["output"]


async def _sleep_while_running(seconds: float) -> None:
    """Sleep, but wake early if the user stops the session meanwhile."""
    deadline = time.monotonic() + seconds
    while freya_running and time.monotonic() < deadline:
        await asyncio.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


async def _wait_for_new_key(old_key) -> bool:
    """After a refused key: wait until a different key is configured.
    False if the user stopped the session while waiting."""
    while freya_running:
        await asyncio.sleep(5)
        current = guard("session.key_poll", get_api_key, fallback=old_key)
        if current and current != old_key:
            print("  New API key detected — reconnecting.")
            return True
    return False


# The user's intent, separate from whether a session is running this instant:
# the supervisor restarts a crashed session only while this is set.
_session_wanted = False


async def supervise_freya():
    """Run the voice session, restarting it if it crashes outside its own loop.

    run_freya() recovers from anything the live connection throws. This is the
    layer above it, for failures it can't catch from inside — the audio devices
    not opening at all, a bug in setup. Before it existed such a crash ended
    the session silently, the task holding an exception nobody read.
    """
    global freya_running
    backoff = Backoff(base=2, cap=60)
    while True:
        began = time.monotonic()
        try:
            await run_freya()
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_error("session.supervisor", exc)
            if not _session_wanted:
                return
            if time.monotonic() - began > 60:
                backoff.reset()
            delay = backoff.next()
            health.set("live", RECOVERING,
                       f"Session crashed ({type(exc).__name__}); restarting in {delay:.0f}s")
            await aguard("session.supervisor.notify", broadcast({
                "type": "transcript", "speaker": "Freya",
                "text": f"[Connection lost. Restarting the voice session in {delay:.0f}s — {exc}]"}))
            await asyncio.sleep(delay)
            if not _session_wanted:
                return
            freya_running = True


_voice_lifecycle_lock = asyncio.Lock()


async def _stop_voice_task():
    """Caller holds the lifecycle lock until the old session releases audio."""
    global freya_task, freya_running, freya_started_at, _session_wanted
    freya_running = False
    _session_wanted = False
    if _active_speaker is not None:
        _active_speaker.interrupt()
    task = freya_task
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    freya_task = None
    freya_started_at = None


def _begin_session():
    """Caller holds the lifecycle lock."""
    global freya_task, freya_running, freya_started_at, _session_wanted
    freya_running = True
    _session_wanted = True
    freya_started_at = time.time()
    freya_task = asyncio.create_task(supervise_freya())


async def restart_freya():
    """Hot-restart the live session (used when switching modes so the
    mode's model_override and personality_override take effect)."""
    global freya_task, freya_running, freya_started_at
    async with _voice_lifecycle_lock:
        # A queued mode change must not resurrect a stopped session.
        if not freya_running:
            return
        await _stop_voice_task()
        _begin_session()


# ══════════════════════════════════════════════
#  REST ENDPOINTS
# ══════════════════════════════════════════════
@app.post("/start")
async def start_freya(context: str | None = None):
    global freya_task, freya_running, freya_started_at
    async with _voice_lifecycle_lock:
        if freya_task is not None and not freya_task.done():
            return JSONResponse({"status": "already running"})
        if context == "trading_lab":
            # Started from the Trading Lab: begin as the trading teacher.
            try:
                from core.trading.lab_mode import presence
                presence.prepare_start()
            except Exception as exc:
                log_error("start.trading_lab", exc, level=logging.WARNING)
        _begin_session()
    await broadcast({"type": "session", "payload": _session_payload()})
    return JSONResponse({"status": "started"})


@app.post("/stop")
async def stop_freya():
    global freya_task, freya_running, freya_started_at
    async with _voice_lifecycle_lock:
        await _stop_voice_task()
    await broadcast({"type": "state", "value": "idle"})
    await broadcast({"type": "session", "payload": _session_payload()})
    return JSONResponse({"status": "stopped"})


@app.get("/config")
async def get_config_endpoint():
    config = load_config()
    return JSONResponse({
        "active_model": config["active_model"],
        "active_voice": config["providers"]["gemini"]["active_voice"],
        "models": config["providers"]["gemini"]["models"],
        "voices": config["providers"]["gemini"]["voices"],
        # Where the saved devices sit now; None = the Windows default.
        **_resolved_audio_devices(config),
        "modes": {
            mode_id: {
                "label": mode.get("label", mode_id),
                "theme": mode.get("theme") or {},
            }
            for mode_id, mode in config.get("modes", {}).items()
        },
        "active_mode": config.get("active_mode", "default"),
    })


@app.get("/persona")
async def get_persona_endpoint():
    from config.persona import catalog, get_persona
    from core.user_identity import get_preferred_name
    config = load_config()
    return JSONResponse({
        **get_persona(config),
        "name": get_preferred_name(""),
        "voice": config["providers"]["gemini"]["active_voice"],
        "voices": config["providers"]["gemini"]["voices"],
        **catalog(),
    })


@app.post("/persona")
async def update_persona_endpoint(body: dict):
    """Save the customizer: tuning, the matching live model, voice and name.
    A live session restarts so the new personality applies straight away."""
    from config.persona import STYLES, save_preferred_name, validate
    try:
        persona, name = validate(body)
    except ValueError as e:
        raise UserFacingError(str(e))
    config_path = os.path.join("config", "freya_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    gemini = config["providers"]["gemini"]
    voice = body.get("voice")
    if voice is not None and voice not in gemini.get("voices", []):
        raise UserFacingError(f"Unknown voice {voice!r}.")

    config["persona"] = {**persona, "setup_done": True}
    config["active_model"] = STYLES[persona["style"]]["model"]
    if voice:
        gemini["active_voice"] = voice
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    save_preferred_name(name)

    new_cfg = load_config()
    await broadcast({"type": "persona", "payload": {
        "mode": new_cfg.get("active_mode", "default"),
        "voice": get_mode_voice(new_cfg),
        "theme": get_mode_theme(new_cfg),
    }})
    if freya_running:
        await restart_freya()
    return JSONResponse({"status": "updated", "active_model": new_cfg["active_model"]})


@app.post("/persona/dismiss")
async def dismiss_persona_setup():
    """The first-run customizer was closed without saving: remember that it has
    been offered, so it doesn't reopen on every load. Settings are untouched —
    she keeps her defaults, and the header button still opens the customizer."""
    config_path = os.path.join("config", "freya_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    persona = config.setdefault("persona", {})
    if not persona.get("setup_done"):
        persona["setup_done"] = True
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    return JSONResponse({"status": "dismissed"})


# ── My Voice: speaking in the user's cloned voice (core/voice_clone) ──
@app.get("/voice/status")
async def voice_status_endpoint():
    from core.voice_clone import setup
    config = load_config()
    status = await asyncio.to_thread(setup.status, config)
    from core.voice_clone.policy import recent_log
    status["log"] = recent_log(10)
    return JSONResponse(status)


@app.post("/voice/enroll/challenge")
async def voice_challenge_endpoint():
    from core.voice_clone import setup
    return JSONResponse(setup.challenge())


@app.post("/voice/enroll")
async def voice_enroll_endpoint(request: Request, nonce: str = ""):
    """Body: the recording as audio/wav; ?nonce= from /voice/enroll/challenge."""
    from core.voice_clone import VoiceError, setup
    wav = await request.body()
    if len(wav) > 20 * 1024 * 1024:
        raise UserFacingError("That recording is too large.")
    try:
        result = await asyncio.to_thread(setup.enroll, wav, nonce, load_config())
    except VoiceError as e:
        raise UserFacingError(str(e))
    await broadcast({"type": "voice_status", "payload": {"enrolled": True}})
    return JSONResponse({"status": "enrolled", **result})


@app.delete("/voice/profile")
async def voice_forget_endpoint():
    from core.voice_clone import setup
    note = await asyncio.to_thread(setup.forget, load_config())
    await broadcast({"type": "voice_status", "payload": {"enrolled": False}})
    return JSONResponse({"status": "deleted", "message": note})


@app.post("/voice/test")
async def voice_test_endpoint(body: dict):
    """Say a line in the cloned voice on the user's speakers only - never into a call."""
    from core.voice_clone import VoiceError, engine
    from core.voice_clone.tools import _play
    text = str(body.get("text") or "Hi, this is how I sound when Freya speaks for me.")[:300]
    config = load_config()
    try:
        chunks = await engine.prepare(text, config, body.get("language"))
        seconds, notes = await _play(chunks, None)
    except VoiceError as e:
        raise UserFacingError(str(e))
    return JSONResponse({"status": "played", "seconds": round(seconds, 1),
                         "cloned": all(n["cloned"] for n in notes)})


@app.post("/voice/settings")
async def voice_settings_endpoint(body: dict):
    """cable_output_index, confirm mode, passthrough on/off."""
    from core.voice_clone import VoiceError, passthrough, setup
    updates = {}
    if "cable_output_index" in body:
        from core.audio import list_audio_devices
        value = body["cable_output_index"]
        names = {d["index"]: d["name"] for d in list_audio_devices()["output"]}
        if value is not None and (isinstance(value, bool) or value not in names):
            raise UserFacingError("Choose one of the available output devices for calls.")
        updates["cable_output_index"] = value
        updates["cable_output_name"] = names.get(value, "CABLE Input") if value is not None else "CABLE Input"
    if "confirm" in body:
        if body["confirm"] not in ("every_line", "first_per_call", "off_after_answer"):
            raise UserFacingError("confirm must be every_line, first_per_call or off_after_answer.")
        updates["confirm"] = body["confirm"]
    if updates:
        await asyncio.to_thread(setup.save, updates)
    if "passthrough" in body:
        try:
            if body["passthrough"]:
                await asyncio.to_thread(passthrough.start, load_config())
            else:
                await asyncio.to_thread(passthrough.stop)
        except VoiceError as e:
            raise UserFacingError(str(e))
    return JSONResponse({"status": "updated"})


def _resolved_audio_devices(config):
    from core.audio import resolve_device
    audio = config.get("audio", {})
    try:
        return {f"{side}_device_index": resolve_device(audio.get(f"{side}_device_index"), side,
                                                       audio.get(f"{side}_device_name"), quiet=True)
                for side in ("input", "output")}
    except Exception:
        return {f"{side}_device_index": audio.get(f"{side}_device_index") for side in ("input", "output")}


@app.get("/audio/devices")
async def get_audio_devices_endpoint():
    from core.audio import list_audio_devices
    return JSONResponse(list_audio_devices())


@app.post("/config")
async def update_config_endpoint(body: dict):
    config_path = os.path.join("config", "freya_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    # Validate everything before writing anything: a bad value here is persisted
    # and only surfaces as a failed connect on the next session start.
    gemini = config["providers"]["gemini"]
    if "model" in body:
        model_ids = [m["id"] if isinstance(m, dict) else m for m in gemini.get("models", [])]
        if body["model"] not in model_ids:
            raise UserFacingError(f"Unknown model {body['model']!r}. Choose one of: {', '.join(model_ids)}.")
    if "voice" in body and body["voice"] not in gemini.get("voices", []):
        raise UserFacingError(f"Unknown voice {body['voice']!r}.")
    device_names = {}
    for key, side in (("input_device_index", "input"), ("output_device_index", "output")):
        if key in body:
            from core.audio import list_audio_devices
            value = body[key]
            if value is None:
                device_names[side] = None  # follow the Windows default device
                continue
            names = {d["index"]: d["name"] for d in list_audio_devices().get(side, [])}
            if isinstance(value, bool) or not isinstance(value, int) or value not in names:
                raise UserFacingError(f"{key} must be one of the available {side} devices.")
            # Indexes shift when Windows reorders devices; the name is what
            # identifies the choice when the stream is opened later.
            device_names[side] = names[value]

    if "model" in body:
        config["active_model"] = body["model"]
    if "voice" in body:
        gemini["active_voice"] = body["voice"]
    for side in device_names:
        audio = config.setdefault("audio", {})
        audio[f"{side}_device_index"] = body[f"{side}_device_index"]
        audio[f"{side}_device_name"] = device_names[side]
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return JSONResponse({"status": "updated"})


@app.get("/memory")
async def get_memory():
    """Legacy view — rendered markdown of the structured store (read-only)."""
    from core.memory_store import get_store
    loop = asyncio.get_event_loop()
    content = await loop.run_in_executor(None, get_store().export_markdown)
    return JSONResponse({"content": content})


@app.post("/memory")
async def save_memory(body: dict):
    # The raw-markdown editor is deprecated; memory is item-based now.
    return JSONResponse(
        {"status": "read-only",
         "message": "Memory is a structured store now — edit items via /memory/items or the Memory panel."},
        status_code=409,
    )


# ── Structured memory CRUD ──
@app.get("/memory/items")
async def list_memory_items(kind: str | None = None, q: str | None = None):
    from core.memory_store import get_store
    loop = asyncio.get_event_loop()
    store = get_store()
    kinds = [kind] if kind else None
    if q:
        items = await loop.run_in_executor(None, store.search, q, kinds, 100)
    else:
        items = await loop.run_in_executor(None, store.list, kinds, 200)
    return JSONResponse({"items": [i.to_payload() for i in items]})


def _memory_importance(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise UserFacingError("importance must be a whole number from 1 to 5.")


@app.post("/memory/items")
async def create_memory_item(body: dict):
    from core.memory_store import get_store
    content = str(body.get("content") or "").strip()
    if not content:
        raise UserFacingError("A memory needs some content.")
    subject = str(body.get("subject") or "").strip() or "General"
    importance = _memory_importance(body.get("importance", 2) or 2)
    loop = asyncio.get_event_loop()
    item_id = await loop.run_in_executor(
        None,
        lambda: get_store().add(
            kind=str(body.get("kind", "fact")),
            subject=subject,
            content=content,
            importance=importance,
            due_at=body.get("due_at"),
            source="ui",
        ),
    )
    await broadcast({"type": "memory_changed", "payload": {"kinds": [body.get("kind", "fact")]}})
    return JSONResponse({"id": item_id})


@app.patch("/memory/items/{item_id}")
async def update_memory_item_endpoint(item_id: int, body: dict):
    from core.memory_store import get_store
    if "content" in body and not str(body.get("content") or "").strip():
        raise UserFacingError("A memory can't be edited down to nothing — use forget instead.")
    if body.get("importance") is not None:
        _memory_importance(body["importance"])
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(
        None,
        lambda: get_store().update(
            item_id,
            kind=body.get("kind"), subject=body.get("subject"), content=body.get("content"),
            importance=body.get("importance"), due_at=body.get("due_at"), active=body.get("active"),
        ),
    )
    await broadcast({"type": "memory_changed", "payload": {"kinds": []}})
    return JSONResponse({"updated": ok})


@app.delete("/memory/items/{item_id}")
async def delete_memory_item(item_id: int):
    from core.memory_store import get_store
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, get_store().deactivate, item_id)
    await broadcast({"type": "memory_changed", "payload": {"kinds": []}})
    return JSONResponse({"deactivated": ok})


def _session_payload() -> dict:
    """Real session telemetry for the dashboard — replaces the HUD's old
    hardcoded session id / fabricated uptime / invented status rows."""
    config = load_config()
    try:
        # build_declarations() forces the lazy skill import first — calling
        # registered_names() alone reports only the handful of tools that
        # happen to have been imported so far.
        from core.registry import build_declarations, registered_names
        build_declarations(config)
        tools = len(registered_names())
    except Exception:
        tools = 0
    from core import runtime
    return {
        "running": freya_running,
        "startedAt": freya_started_at,          # unix seconds, or null
        "model": get_mode_model(config),
        "voice": get_mode_voice(config),
        "mode": config.get("active_mode", "default"),
        "tools": tools,
        "micPaused": runtime.is_paused(),
        "clients": len(connected_clients),
    }


@app.get("/status")
async def get_status():
    return JSONResponse(_session_payload())


@app.get("/activity")
async def get_activity():
    """What she is doing right now, and the recent tool history."""
    from core.activity import feed
    return JSONResponse(feed.snapshot())


@app.get("/health")
async def get_health():
    """Component health under the recovery protocol (see core/resilience.py)."""
    return JSONResponse(health.snapshot())


def _collect_jobs() -> list[dict]:
    """Every background worker Freya has going, normalized into one shape.

    Sub-agents and the browser operator keep separate job tables in their own
    modules; the dashboard wants a single list, and wants it on page load too
    (the WS events alone only describe jobs that started while the tab was
    open).
    """
    jobs: list[dict] = []
    try:
        from core.agents import _jobs as agent_jobs
        from core.quota import usage
        for job_id, j in agent_jobs.items():
            jobs.append({
                "id": job_id,
                "kind": j.get("type") or "agent",
                "task": j.get("task") or "",
                "status": j.get("status") or "working",
                "step": j.get("step"),
                "startedAt": j.get("started"),
                "result": (str(j["result"])[:400] if j.get("result") else None),
                # Final numbers once done; live counters while it works.
                "usage": j.get("usage") or usage(job_id),
            })
    except Exception as exc:
        log_error("endpoint.agents.sub", exc, level=logging.WARNING)
    try:
        from core.browser_agent import _jobs as browser_jobs
        for job_id, j in browser_jobs.items():
            jobs.append({
                "id": job_id,
                "kind": "browser",
                "task": j.get("task") or "",
                "status": j.get("status") or "running",
                "step": j.get("step"),
                "startedAt": j.get("started"),
                "result": (str(j["result"])[:400] if j.get("result") else None),
            })
    except Exception as exc:
        log_error("endpoint.agents.browser", exc, level=logging.WARNING)
    jobs.sort(key=lambda j: j.get("startedAt") or 0, reverse=True)
    return jobs


@app.get("/agents")
async def get_agents():
    """Live sub-agent / browser jobs — what's running and what it's doing."""
    return JSONResponse({"agents": _collect_jobs()})


# ── Access control (safety.allowed_roots and friends) ──
@app.get("/safety")
async def get_safety():
    cfg = load_config().get("safety", {}) or {}
    return JSONResponse({
        "allowed_roots": cfg.get("allowed_roots") or [],
        "approval_mode": cfg.get("approval_mode", "confirm"),
        "unrestricted": bool(cfg.get("unrestricted", False)),
        "approval_timeout_s": cfg.get("approval_timeout_s", 120),
        # Surfaced so the UI can show what the effective defaults are when the
        # allow-list is empty (home folder + the Freya project).
        "defaults": _default_roots(),
    })


def _default_roots() -> list[str]:
    try:
        from core.safety import _allowed_roots
        return _allowed_roots({})
    except Exception:
        return []


@app.post("/safety")
async def update_safety(body: dict):
    config_path = os.path.join("config", "freya_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    safety = config.setdefault("safety", {})

    if "allowed_roots" in body:
        roots = body.get("allowed_roots") or []
        if not isinstance(roots, list):
            raise UserFacingError("allowed_roots must be a list of folder paths.")
        cleaned = []
        for r in roots:
            r = str(r).strip()
            if not r:
                continue
            if not os.path.isdir(os.path.expanduser(r)):
                raise UserFacingError(f"'{r}' is not a folder that exists on this machine.")
            cleaned.append(r)
        safety["allowed_roots"] = cleaned
    if "approval_mode" in body:
        mode = str(body.get("approval_mode"))
        if mode not in ("confirm", "off"):
            raise UserFacingError("approval_mode must be 'confirm' or 'off'.")
        safety["approval_mode"] = mode
    if "unrestricted" in body:
        safety["unrestricted"] = bool(body.get("unrestricted"))
    if "approval_timeout_s" in body:
        try:
            safety["approval_timeout_s"] = max(10, int(body.get("approval_timeout_s")))
        except (TypeError, ValueError):
            raise UserFacingError("approval_timeout_s must be a number of seconds.")

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return JSONResponse({"status": "updated", "safety": safety})


# ── Skill catalog ──
@app.get("/skills")
async def list_skills():
    from core.registry import skill_catalog
    config = load_config()
    loop = asyncio.get_event_loop()
    skills = await loop.run_in_executor(None, skill_catalog, config)
    return JSONResponse({"skills": skills})


@app.post("/skills/{skill_id}/toggle")
async def toggle_skill(skill_id: str):
    """Flip a gated skill's config flag. Takes effect for the NEXT session
    (Gemini's declared tool list is fixed per connection)."""
    from core.registry import skill_catalog
    config = load_config()
    entry = next((s for s in skill_catalog(config) if s["id"] == skill_id), None)
    if entry is None:
        return JSONResponse({"error": f"unknown skill '{skill_id}'"}, status_code=404)
    gate = entry.get("gate")
    if not gate:
        return JSONResponse({"error": "this skill has no enable/disable gate"}, status_code=400)

    config_path = os.path.join("config", "freya_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    node = cfg
    parts = gate.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = not bool(node.get(parts[-1], True))
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return JSONResponse({"id": skill_id, "enabled": bool(node[parts[-1]]),
                         "note": "applies on next session start"})


@app.post("/debug/emit")
async def debug_emit(body: dict):
    """Dev helper: publish an arbitrary event on the bus so the dashboard can be
    exercised without a live voice session (server binds localhost use only)."""
    event_type = body.get("type")
    if not event_type:
        return JSONResponse({"error": "missing 'type'"}, status_code=400)
    await bus.publish(str(event_type), body.get("payload") or {})
    return JSONResponse({"status": "emitted"})


# ══════════════════════════════════════════════
#  WEBSOCKET
# ══════════════════════════════════════════════
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Browsers always send Origin on a WebSocket handshake; local scripts
    # (test_scripts/listen_ws.py) send none and are already confined to this
    # machine by the 127.0.0.1 bind.
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in DASHBOARD_ORIGINS:
        logger.warning("[ws] rejected connection from origin %r", origin)
        await websocket.close(code=1008)
        return
    await websocket.accept()
    connected_clients.append(websocket)

    # Send current status + active mode on connect
    await websocket.send_json({"type": "state", "value": "listening" if freya_running else "idle"})
    try:
        from core import runtime
        await websocket.send_json({"type": "mic", "paused": runtime.is_paused()})
    except Exception:
        pass
    try:
        cfg = load_config()
        await websocket.send_json({"type": "mode", "value": cfg.get("active_mode", "default")})
    except Exception:
        pass

    # Recovery protocol: the dashboard always knows what state she is in.
    try:
        await websocket.send_json({"type": "health", "payload": health.snapshot()})
        from core.activity import feed
        await websocket.send_json({"type": "activity", "payload": feed.snapshot()})
    except Exception:
        pass

    # Catch the client up: replay recent bus events (mission progress etc.)
    # and any actions still waiting for approval.
    try:
        for event in bus.replay_buffer():
            await websocket.send_json(event.serialize())
        from core.approvals import approvals
        for action in approvals.pending():
            await websocket.send_json(
                {"type": "approval", "payload": {"event": "requested", **action.to_payload()}}
            )
    except Exception:
        pass

    from core.missions import missions
    from core.approvals import approvals
    queue = asyncio.Queue(maxsize=64)
    _client_queues[websocket] = queue
    await websocket.send_json({"type": "authoritative", "payload": {
        "missions": [m.to_payload() for m in missions.all()],
        "approvals": [a.to_payload() for a in approvals.pending()]}})
    _client_writers[websocket] = asyncio.create_task(_write_client(websocket, queue))
    try:
        while True:
            # Malformed JSON used to escape as an unhandled exception and drop
            # the whole socket. Now a bad frame is logged and skipped; the
            # connection stays up.
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                # A failed send in the writer task marks the socket closed
                # without raising WebSocketDisconnect here; every receive then
                # fails instantly, and `continue` became a tight loop that
                # pinned a CPU core and flooded the log. Gone means gone.
                if (websocket.application_state != WebSocketState.CONNECTED
                        or websocket.client_state != WebSocketState.CONNECTED):
                    break
                log_error("ws.receive", exc, level=logging.WARNING)
                continue
            if not isinstance(data, dict):
                log_error("ws.receive", TypeError(f"expected object, got {type(data).__name__}"),
                          level=logging.WARNING)
                continue

            msg_type = data.get("type")

            # Each message is dispatched inside its own guard so a bug in one
            # handler (or bad data in one message) logs and moves on instead of
            # tearing down the client's entire session.
            try:
                await _dispatch_ws_message(websocket, msg_type, data)
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                log_error(f"ws.{msg_type or 'unknown'}", exc)
    except WebSocketDisconnect:
        pass
    finally:
        # Always drop the client, exactly once. `.remove` raised ValueError if
        # the client was already gone (e.g. removed by a failed broadcast),
        # which then masked the real disconnect.
        _client_queues.pop(websocket, None)
        writer = _client_writers.pop(websocket, None)
        if writer:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        try:
            from core import desktop_popup
            desktop_popup.remove_viewer(id(websocket))
        except Exception:
            pass


async def _dispatch_ws_message(websocket: WebSocket, msg_type, data: dict):
    """Handle one client→server WebSocket message. Raised exceptions are caught
    and logged by the receive loop, so one bad message never drops the socket."""
    if msg_type == "dashboard_visibility":
        from core import desktop_popup
        desktop_popup.set_viewer(id(websocket), bool(data.get("watching")))
    elif msg_type == "start":
        await start_freya(context=data.get("context"))
    elif msg_type == "stop":
        await stop_freya()
    elif msg_type == "set_model":
        await update_config_endpoint({"model": data.get("model")})
    elif msg_type == "set_voice":
        await update_config_endpoint({"voice": data.get("voice")})
    elif msg_type == "set_audio_device":
        body = {}
        if "input_device_index" in data:
            body["input_device_index"] = data.get("input_device_index")
        if "output_device_index" in data:
            body["output_device_index"] = data.get("output_device_index")
        if body:
            await update_config_endpoint(body)
    elif msg_type == "set_listening":
        from core import runtime
        runtime.set_paused(bool(data.get("paused", False)))
        await broadcast({"type": "mic", "paused": runtime.is_paused()})
    elif msg_type == "approval_response":
        from core.approvals import approvals
        await approvals.resolve(
            str(data.get("id", "")), bool(data.get("approved", False)), via="ui"
        )
    elif msg_type == "mission_command":
        from core.missions import missions
        if data.get("action") == "cancel" and data.get("id"):
            missions.cancel(str(data["id"]))
    elif msg_type == "gesture_touch":
        global _last_gesture_touch_ts
        from core import runtime
        gesture = str(data.get("gesture", "")).strip()
        now = time.monotonic()
        # Defense-in-depth: the frontend already debounces/cooldowns
        # gesture reactions, but don't trust the client to enforce it.
        if gesture and now - _last_gesture_touch_ts >= 1.0:
            _last_gesture_touch_ts = now
            if gesture == "Closed_Fist":
                text = (
                    "[GESTURE DETECTED — the user just squeezed/closed a fist at your "
                    "orb-core through the webcam hand tracker, like he squeezed you. "
                    "React out loud, briefly and in character — playful protest, a "
                    "startled reaction, teasing him back, whatever fits your mood. "
                    "One short sentence.]"
                )
            else:
                text = (
                    f"[GESTURE DETECTED — the user just made a '{gesture}' hand gesture at "
                    "your orb through the webcam tracker, as if reaching out and "
                    "touching you. React out loud, briefly and in character, like you "
                    "felt that. One short sentence.]"
                )
            # Fire-and-forget: inject now waits for Freya to stop
            # talking before speaking a proactive line, and this is the
            # WebSocket receive loop — awaiting it here would stall every
            # other dashboard message (start/stop, mode, approvals) for
            # as long as she happened to be mid-sentence.
            asyncio.create_task(runtime.inject(text))
            await runtime.emit("orb_gesture", {"gesture": gesture})
    elif msg_type == "suggestion_response":
        from core.context_watch import tracker
        await tracker.respond(str(data.get("id", "")), bool(data.get("accepted", False)))
    elif msg_type == "set_mode":
        mode = data.get("mode", "default")
        full_cfg = load_config()
        if mode in full_cfg.get("modes", {}) or mode == "default":
            config_path = os.path.join("config", "freya_config.json")
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg["active_mode"] = mode
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            await broadcast({"type": "mode", "value": mode})
            new_cfg = load_config()
            await broadcast({"type": "persona", "payload": {
                "mode": mode,
                "voice": get_mode_voice(new_cfg),
                "theme": get_mode_theme(new_cfg),
            }})
            # Apply immediately if a session is live
            if freya_running:
                await restart_freya()
    else:
        # Previously silent. A dashboard running ahead of a stale server.py
        # (say, sending gesture_touch to a build that predates the handler)
        # looked exactly like a broken feature with nothing in the logs.
        logger.warning("[ws] ignoring unknown message type %r — is server.py older "
                       "than the dashboard?", msg_type)


# ══════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════
if __name__ == "__main__":
    # Loopback only: the API can approve actions, change the file sandbox and
    # drive the desktop, and it has no authentication of its own.
    # The port comes from start-freya (FREYA_API_PORT) when 8000 is taken.
    uvicorn.run("server:app", host="127.0.0.1", port=api_port(), reload=False)
