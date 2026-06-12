import asyncio
import json
import os
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import load_config, get_api_key, get_active_model, get_active_voice, get_personality
from config import get_mode_personality, get_mode_model
from core.audio import MicStream, SpeakerStream
from core.memory import load_memory, build_system_prompt, update_memory, TranscriptCollector
from core.model import FreyaModel

app = FastAPI()

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
    voice = get_active_voice(config)
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

    # Patch FreyaModel to broadcast events to UI
    class FreyaModelWithBroadcast(FreyaModel):
        async def on_transcript(self, speaker_name: str, text: str):
            transcript.add(speaker_name, text)
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
    finally:
        freya_running = False
        mic.stop()
        speaker.stop()
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
            mode_id: {"label": mode.get("label", mode_id)}
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
    memory = load_memory()
    return JSONResponse({"content": memory})


@app.post("/memory")
async def save_memory(body: dict):
    from core.memory import MEMORY_PATH
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        f.write(body.get("content", ""))
    return JSONResponse({"status": "saved"})


@app.get("/status")
async def get_status():
    return JSONResponse({"running": freya_running})


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
        cfg = load_config()
        await websocket.send_json({"type": "mode", "value": cfg.get("active_mode", "default")})
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
            elif msg_type == "set_mode":
                mode = data.get("mode", "default")
                config_path = os.path.join("config", "freya_config.json")
                with open(config_path, "r") as f:
                    cfg = json.load(f)
                if mode in cfg.get("modes", {}):
                    cfg["active_mode"] = mode
                    with open(config_path, "w") as f:
                        json.dump(cfg, f, indent=2)
                    await broadcast({"type": "mode", "value": mode})
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