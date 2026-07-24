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

from core.errors import log_error, error_payload, UserFacingError, logger

# On Windows, browser-use (Playwright) launches Chromium via create_subprocess_exec,
# which only works on the Proactor event loop. uvicorn may otherwise pick a Selector
# loop, causing browser_task to hang until its 30s launch watchdog fires. Force Proactor
# so subprocess spawning works the same way it does in main.py's asyncio.run path.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

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
from core.model import FreyaModel


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The bus is the single transport for all runtime.emit() events. Subscribing
    # here (not per-session) means mission/approval/suggestion events reach the
    # dashboard even while no voice session is running.
    unsubscribe = bus.subscribe(lambda event: broadcast(event.serialize()))
    # Import any legacy markdown memory into the structured store up front so
    # the Memory panel is populated before the first voice session.
    try:
        from core.memory import _migrate_markdown_if_needed
        await asyncio.get_event_loop().run_in_executor(None, _migrate_markdown_if_needed)
    except Exception as e:
        print(f"  memory migration check failed: {e}")
    yield
    unsubscribe()


app = FastAPI(lifespan=lifespan)

# Defense-in-depth rate limit for "gesture_touch" WS messages — the frontend
# already debounces gesture reactions, but the server shouldn't trust a
# client to enforce that. See the /ws gesture_touch handler below.
_last_gesture_touch_ts = 0.0

# Allow Next.js dev server to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
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


# ══════════════════════════════════════════════
#  BROADCAST  — send a message to all UI clients
# ══════════════════════════════════════════════
async def broadcast(message: dict):
    disconnected = []
    for client in connected_clients:
        try:
            await client.send_json(message)
        except Exception:
            disconnected.append(client)
    for c in disconnected:
        # Guarded: the /ws finally block may already have removed a client that
        # also failed to send here — a bare .remove() would raise ValueError.
        if c in connected_clients:
            connected_clients.remove(c)


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
    memory = load_memory()
    personality = build_system_prompt(get_mode_personality(config, base_personality), memory)
    transcript = TranscriptCollector()

    input_idx = config["audio"]["input_device_index"]
    output_idx = config["audio"]["output_device_index"]

    mic = MicStream(device_index=input_idx)
    speaker = SpeakerStream(device_index=output_idx)
    mic.start()
    speaker.start()

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
                # Reconnect so the mode's model/personality overrides apply
                asyncio.create_task(restart_freya())

        async def on_state(self, value: str):
            await broadcast({"type": "state", "value": value})

        # NOTE: no on_event override — generic events (agent / mcp / schedule /
        # ambient / browser / speech / mic / …) now flow runtime.emit → event bus
        # → the broadcast subscriber registered in lifespan().

    consecutive_failures = 0
    max_reconnect_attempts = 5

    try:
        while freya_running:
            freya = FreyaModelWithBroadcast(
                api_key=api_key,
                model_id=model_id,
                voice=voice,
                personality=personality,
                config=config,
                transcript=transcript
            )
            try:
                await freya.run(mic, speaker)
                # Clean exit from run means session completed normally (or user stopped it without cancellation)
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                consecutive_failures += 1
                print(f"Freya session error (attempt {consecutive_failures}/{max_reconnect_attempts}): {e}")
                if consecutive_failures >= max_reconnect_attempts:
                    await broadcast({
                        "type": "transcript",
                        "speaker": "Freya",
                        "text": f"[SESSION ERROR] Max reconnect attempts reached. Connection stopped."
                    })
                    break
                
                await broadcast({
                    "type": "transcript",
                    "speaker": "Freya",
                    "text": f"[Connection lost. Reconnecting to Gemini... Attempt {consecutive_failures}/{max_reconnect_attempts}]"
                })
                
                await asyncio.sleep(2 * consecutive_failures)
                
                # Reload config and keys in case they were updated
                config = load_config()
                api_key = get_api_key()
                model_id = get_mode_model(config)
                voice = get_mode_voice(config)
                base_personality = get_personality(config)
                personality = build_system_prompt(get_mode_personality(config, base_personality), memory)
    finally:
        freya_running = False
        mic.stop()
        speaker.stop()
        try:
            from core.mcp_client import mcp_manager
            await mcp_manager.stop()
        except Exception:
            pass
        await broadcast({"type": "state", "value": "idle"})
        await update_memory(api_key, transcript.get(), memory)


async def restart_freya():
    """Hot-restart the live session (used when switching modes so the
    mode's model_override and personality_override take effect)."""
    global freya_task, freya_running
    if freya_task:
        freya_task.cancel()
        freya_task = None
    freya_running = False
    await asyncio.sleep(0.8)  # let audio devices fully release
    freya_running = True
    freya_task = asyncio.create_task(run_freya())


# ══════════════════════════════════════════════
#  REST ENDPOINTS
# ══════════════════════════════════════════════
@app.post("/start")
async def start_freya():
    global freya_task, freya_running, freya_started_at
    if freya_running:
        return JSONResponse({"status": "already running"})
    freya_running = True
    freya_started_at = time.time()
    freya_task = asyncio.create_task(run_freya())
    await broadcast({"type": "session", "payload": _session_payload()})
    return JSONResponse({"status": "started"})


@app.post("/stop")
async def stop_freya():
    global freya_task, freya_running, freya_started_at
    if freya_task:
        freya_task.cancel()
        freya_task = None
    freya_running = False
    freya_started_at = None
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
        "input_device_index": config.get("audio", {}).get("input_device_index"),
        "output_device_index": config.get("audio", {}).get("output_device_index"),
        "modes": {
            mode_id: {
                "label": mode.get("label", mode_id),
                "theme": mode.get("theme") or {},
            }
            for mode_id, mode in config.get("modes", {}).items()
        },
        "active_mode": config.get("active_mode", "default"),
    })


@app.get("/audio/devices")
async def get_audio_devices_endpoint():
    from core.audio import list_audio_devices
    return JSONResponse(list_audio_devices())


@app.post("/config")
async def update_config_endpoint(body: dict):
    config_path = os.path.join("config", "freya_config.json")
    with open(config_path, "r") as f:
        config = json.load(f)
    if "model" in body:
        config["active_model"] = body["model"]
    if "voice" in body:
        config["providers"]["gemini"]["active_voice"] = body["voice"]
    if "input_device_index" in body:
        config.setdefault("audio", {})["input_device_index"] = body["input_device_index"]
    if "output_device_index" in body:
        config.setdefault("audio", {})["output_device_index"] = body["output_device_index"]
    with open(config_path, "w") as f:
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


@app.post("/memory/items")
async def create_memory_item(body: dict):
    from core.memory_store import get_store
    loop = asyncio.get_event_loop()
    item_id = await loop.run_in_executor(
        None,
        lambda: get_store().add(
            kind=str(body.get("kind", "fact")),
            subject=str(body.get("subject", "General")),
            content=str(body.get("content", "")),
            importance=int(body.get("importance", 2) or 2),
            due_at=body.get("due_at"),
            source="ui",
        ),
    )
    await broadcast({"type": "memory_changed", "payload": {"kinds": [body.get("kind", "fact")]}})
    return JSONResponse({"id": item_id})


@app.patch("/memory/items/{item_id}")
async def update_memory_item_endpoint(item_id: int, body: dict):
    from core.memory_store import get_store
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
        for job_id, j in agent_jobs.items():
            jobs.append({
                "id": job_id,
                "kind": j.get("type") or "agent",
                "task": j.get("task") or "",
                "status": j.get("status") or "working",
                "step": j.get("step"),
                "startedAt": j.get("started"),
                "result": (str(j["result"])[:400] if j.get("result") else None),
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
    with open(config_path, "r") as f:
        cfg = json.load(f)
    node = cfg
    parts = gate.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = not bool(node.get(parts[-1], True))
    with open(config_path, "w") as f:
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
        if websocket in connected_clients:
            connected_clients.remove(websocket)


async def _dispatch_ws_message(websocket: WebSocket, msg_type, data: dict):
    """Handle one client→server WebSocket message. Raised exceptions are caught
    and logged by the receive loop, so one bad message never drops the socket."""
    if msg_type == "start":
        await start_freya()
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
                    "[GESTURE DETECTED — Ihan just squeezed/closed a fist at your "
                    "orb-core through the webcam hand tracker, like he squeezed you. "
                    "React out loud, briefly and in character — playful protest, a "
                    "startled reaction, teasing him back, whatever fits your mood. "
                    "One short sentence.]"
                )
            else:
                text = (
                    f"[GESTURE DETECTED — Ihan just made a '{gesture}' hand gesture at "
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
            with open(config_path, "r") as f:
                cfg = json.load(f)
            cfg["active_mode"] = mode
            with open(config_path, "w") as f:
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
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)