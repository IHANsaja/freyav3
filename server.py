import asyncio
import json
import os
import sys
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# On Windows, browser-use (Playwright) launches Chromium via create_subprocess_exec,
# which only works on the Proactor event loop. uvicorn may otherwise pick a Selector
# loop, causing browser_task to hang until its 30s launch watchdog fires. Force Proactor
# so subprocess spawning works the same way it does in main.py's asyncio.run path.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

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

# Allow Next.js dev server to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global state ──
freya_task = None
freya_running = False
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
    global freya_task, freya_running
    if freya_running:
        return JSONResponse({"status": "already running"})
    freya_running = True
    freya_task = asyncio.create_task(run_freya())
    return JSONResponse({"status": "started"})


@app.post("/stop")
async def stop_freya():
    global freya_task, freya_running
    if freya_task:
        freya_task.cancel()
        freya_task = None
    freya_running = False
    await broadcast({"type": "state", "value": "idle"})
    return JSONResponse({"status": "stopped"})


@app.get("/config")
async def get_config_endpoint():
    config = load_config()
    return JSONResponse({
        "active_model": config["active_model"],
        "active_voice": config["providers"]["gemini"]["active_voice"],
        "models": config["providers"]["gemini"]["models"],
        "voices": config["providers"]["gemini"]["voices"],
        "modes": {
            mode_id: {
                "label": mode.get("label", mode_id),
                "theme": mode.get("theme") or {},
            }
            for mode_id, mode in config.get("modes", {}).items()
        },
        "active_mode": config.get("active_mode", "default"),
    })


@app.post("/config")
async def update_config_endpoint(body: dict):
    config_path = os.path.join("config", "freya_config.json")
    with open(config_path, "r") as f:
        config = json.load(f)
    if "model" in body:
        config["active_model"] = body["model"]
    if "voice" in body:
        config["providers"]["gemini"]["active_voice"] = body["voice"]
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


@app.get("/status")
async def get_status():
    return JSONResponse({"running": freya_running})


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
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "start":
                await start_freya()
            elif msg_type == "stop":
                await stop_freya()
            elif msg_type == "set_model":
                await update_config_endpoint({"model": data.get("model")})
            elif msg_type == "set_voice":
                await update_config_endpoint({"voice": data.get("voice")})
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

    except WebSocketDisconnect:
        connected_clients.remove(websocket)


# ══════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════
if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)