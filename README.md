# 🌌 Freya v3.0

🚀 **The Cybernetic Voice Assistant & Agent Interface**

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Gemini API](https://img.shields.io/badge/Google_Gemini-Live_API-orange?style=for-the-badge&logo=google-gemini&logoColor=white)](https://ai.google.dev/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org/)
[![OS](https://img.shields.io/badge/Platform-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)](#)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](./LICENSE)

---

Freya is a local, real-time voice assistant built on a low-latency bi-directional audio stream with the Google Gemini Live API. Running on your Windows desktop, she acts as a conversational **agent** — executing automation on command and showing her work through a browser-based 3D dashboard you can steer with your hands.

> [!NOTE]
> For the modular design, internal subsystems, and operational patterns, see the [Architecture Documentation](./ARCHITECTURE.md).

Armed with **75+ tools**, a **mission orchestrator**, **approval-gated autopilot**, **structured long-term memory**, **webcam hand-gesture control**, an **intent-driven 3D avatar**, and **always-on context awareness**, Freya doesn't just run tools; she plans, acts, verifies, remembers, and animates herself.

---

## ⚡ Install (one command)

Open **PowerShell** and run:

```powershell
irm https://raw.githubusercontent.com/IHANsaja/freyav3/main/install.ps1 | iex
```

The installer checks prerequisites, clones the repo, builds the Python venv and the dashboard, installs Chromium for browser automation, prompts for your Gemini API key, and writes a `start-freya.ps1` launcher.

**Then:**

```powershell
.\start-freya.ps1
```

Both servers start and `http://localhost:3000` opens automatically.

<details>
<summary>Installer options &amp; manual setup</summary>

```powershell
.\install.ps1 -SkipBrowser        # skip the ~150 MB Chromium download
.\install.ps1 -SkipFrontend       # headless / CLI-only, no npm install
.\install.ps1 -InstallPath D:\ai\freya
```

**Prerequisites:** Python 3.10+, Node.js 18+, git, and C++ Build Tools (for `pyaudio`).

Manual equivalent:

```powershell
git clone https://github.com/IHANsaja/freyav3.git
cd freyav3
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cd freya-ui; npm install; cd ..
# create .env with GEMINI_API_KEY=...
```

</details>

---

## 🌟 Key Capabilities

*   🔊 **Zero-Latency Live Conversation**: 16 kHz input / 24 kHz output on a dedicated audio thread pool, so background agents can never stutter her voice.
*   🖐️ **Hand-Gesture Control**: Steer the 3D orb with your webcam — move to rotate, pinch to zoom, squeeze to compress. She reacts out loud to deliberate hand signs.
*   🎯 **Mission Mode**: Give a high-level goal — Freya plans steps, executes them with background agents, verifies each result, and reports back out loud.
*   🛡️ **Approval Checkpoints**: Sensitive actions pause for your explicit yes — by voice or a dashboard button — with an editable folder sandbox.
*   🧠 **Structured Memory**: Typed, searchable, editable memory items in SQLite+FTS5, mirrored into semantic vector recall. Due items get spoken reminders.
*   👁️ **Context Awareness**: Opt-in, metadata-only tracking of your active window with rate-limited proactive suggestions. Zero screenshots unless you accept.
*   💃 **Living 3D Avatar**: Freya animates her own body through tools — clip crossfades, procedural breathing/look-at, shader accents. Never frozen.
*   📊 **Live Dashboard**: Real sub-agent tracking, the running conversation, mission progress, and genuine system telemetry — no placeholder data.
*   ⌬ **Two Skill Systems**: Python skills (`@tool`) *and* Claude-style markdown `SKILL.md` packs loaded on demand with progressive disclosure.
*   🎭 **Personas**: Modes switch voice, speaking style, UI theme colors, and avatar posture.

---

## 🖐️ Hand-Gesture Control

Enable it with the hand icon in the header (it asks for camera permission). Powered by MediaPipe's gesture recognizer, bundled locally in `freya-ui/public/mediapipe/` — no CDN calls.

| Gesture | Effect |
| :--- | :--- |
| **Move an open hand** | Rotates the orb itself (the scene and camera stay put) |
| **Pinch** thumb + index, then spread/close | Zooms the orb in / out |
| **Squeeze** (closed fist) | Compresses the orb proportionally to grip strength, with a spring rebound on release |
| **Victory / 👍 / 👎 / ☝️ / 🤟** | Freya reacts out loud, in character, through the live session |

Design notes:
- Merely *tracking* a hand never changes the orb's size or state — squeezing requires a genuinely closed hand (hysteresis-latched), so drags and pinches can't dent it.
- Rotation stands down while pinching, so resizing doesn't also fling the orb.
- Grip is measured from middle/ring/pinky and pinch from thumb+index — **disjoint fingers**, so zoom and squeeze stay independent.
- Camera selection is available in the header when more than one webcam is present.

---

## 🦾 Superpowers & Autonomous Agents

| Superpower | What she can do | Key Tools |
| :--- | :--- | :--- |
| 🎯 **Missions** | Plan → execute → verify → report for big goals, with approval pauses. | `start_mission`, `mission_status`, `cancel_mission` |
| 🛡️ **Approvals** | Human-in-the-loop gate for sensitive/irreversible actions. | `approve_action`, `reject_action` |
| 🤖 **Sub-Agents** | Delegates multi-step research, coding, or UI tasks to background workers on their own threads. | `dispatch_agent`, `check_agents` |
| 🌐 **Browser Use** | Autonomously drives a Chromium browser for interactive web tasks. | `browser_task` |
| 🔎 **Web & News** | Quota-free search/fetch plus live headlines projected into the scene. | `web_search`, `web_fetch`, `get_world_news` |
| 📁 **File Manager** | Copy, move/rename, recycle, zip/unzip, inspect, reveal in Explorer, find large/recent files. | `copy_item`, `move_item`, `delete_item`, `zip_item`, `find_files_by`, … |
| 🎬 **Watch Video** | Actually watches a YouTube link or local file and answers questions about it. | `use_skill("watch")` |
| 💼 **Career Ops** | Bridged [career-ops](https://github.com/santifer/career-ops): scan portals, A–G offer evaluation, CV tailoring, tracking. | `use_career_mode`, `run_career_script` |
| 💃 **Avatar** | Emotional expressions, gestures, poses on her 3D body. | `set_expression`, `set_gesture`, `set_idle_state` |
| 🧠 **Memory** | Save/search/edit/forget typed memories mid-conversation. | `remember`, `list_memories`, `forget`, `whats_coming_up` |
| 👁️ **Context** | Always-on window awareness with proactive suggestions. | `enable_context_awareness`, `watch_screen` |
| 🎯 **System Automation** | Clipboard, windows, volume/media, lock/sleep, screen control via UI-Automation. | `clipboard_*`, `focus_window`, `control_element`, … |
| 🧬 **Self-Extension** | Autonomously writes, loads, and uses new Python tools. | `create_tool`, `run_code` |

---

## ⌬ Skills

Freya has **two** complementary skill systems.

**1. Python skills** — modules that register callable tools via `@tool`, listed in `core/skills/loader.py` with a manifest, tool list, and enable gate. Browse them in ⚙ Settings → SKILL_MODULES or `GET /skills`.

**2. Markdown skill packs** — Claude-style `SKILL.md` folders under `skills/`, using the open Agent Skill Standard, with **progressive disclosure**:

```
skills/
  watch/
    SKILL.md          <- frontmatter: name + description; body: instructions
    scripts/watch.py  <- bundled executable, run on demand
```

- Every skill's **name + description** is always visible to the model.
- The **full instructions** load only when she calls `use_skill(name)`.
- Bundled **scripts** run via `run_skill_script` without ever occupying context.

This means third-party agent-standard skills can be dropped into `skills/` and used essentially unmodified.

---

## 🏗️ Project Structure

```
freyav3/
├── config/                 # Config loading, mode/persona profiles, feature gates
├── core/
│   ├── events.py           # Typed event bus (+ replay buffer for reconnects)
│   ├── errors.py           # Shared logger + safe client error payloads
│   ├── safety.py           # Folder sandbox + approval rules
│   ├── approvals.py        # Human-in-the-loop approval gate
│   ├── missions.py         # Plan -> execute -> verify -> report orchestrator
│   ├── agents.py           # Sub-agents (own thread + event loop each)
│   ├── file_manager.py     # Copy/move/recycle/zip/inspect file operations
│   ├── md_skills.py        # SKILL.md packs w/ progressive disclosure
│   ├── career_ops.py       # career-ops bridge
│   ├── memory_store.py     # Structured memory (SQLite + FTS5)
│   ├── context_watch.py    # Always-on metadata context tracker (opt-in)
│   └── ...                 # audio, model loop, registry, screen, browser, scheduler
├── freya-ui/
│   └── app/
│       ├── components/hud/     # AgentsCard, ChatCard, SystemStatusCard, ...
│       ├── components/scene/   # Orb + shaders, hand-driven rotation/zoom/squeeze
│       ├── hooks/useHandGestures.ts     # MediaPipe webcam tracking
│       └── hooks/useGestureOrbBridge.ts # Gesture -> reaction dispatch
├── skills/watch/           # Markdown skill pack: video watching
├── memory/                 # freya_memory.db (SQLite), rag_db (Chroma), schedule.json
├── install.ps1             # One-command installer
├── main.py                 # CLI entrypoint
├── server.py               # FastAPI + WebSocket backend
└── requirements.txt
```

---

## 🚀 Running

```powershell
.\start-freya.ps1            # both halves + opens the dashboard
```

Or manually:

```powershell
# Terminal 1 - backend
.\venv\Scripts\python.exe server.py

# Terminal 2 - dashboard
cd freya-ui; npm run dev
```

Open `http://localhost:3000` and press **START FREYA**.

**Headless CLI:** `.\venv\Scripts\python.exe main.py` (`Ctrl+C` stops and persists memory).

---

## 🔐 Access Control

Freya can write files, run code, and drive your desktop, so file-touching tools pass through a sandbox first (`core/safety.py`).

Edit it in **⚙ Settings → ACCESS_CONTROL**:

- **Allowed folders** — add/remove the roots she may modify. Empty means the safe default: your home folder and the Freya project. Paths are validated server-side.
- **Confirm sensitive actions** — the approval gate for deletions, sends, submissions, and out-of-project writes.
- **Unrestricted mode** — disables the folder sandbox entirely. Off by default; only enable if you understand the consequences.

---

## 🔌 HTTP API

| Endpoint | Purpose |
| :--- | :--- |
| `GET /status` | Session telemetry: running, startedAt, model, voice, mode, tool count |
| `GET /agents` | Live sub-agent + browser jobs with their tasks and current step |
| `GET`/`POST` `/safety` | Read/update the access-control sandbox |
| `GET`/`POST` `/config` | Model, voice, mode, audio devices |
| `GET /skills` | Skill catalog with tools + gate state |
| `GET /audio/devices` | Input/output device enumeration |
| `POST /debug/emit` | Push any event to the dashboard without a voice session |

Exercise the UI with no mic or quota:

```bash
curl -X POST http://localhost:8000/debug/emit -H "Content-Type: application/json" \
  -d '{"type":"agent","payload":{"id":"res-1","agent":"researcher","task":"Compare GPUs","status":"working","step":"web_search"}}'
```

---

## 🧪 Trying it out

| Feature | Say / do | Expect |
| :--- | :--- | :--- |
| **Hand control** | Enable the hand icon, move your hand | Orb rotates; pinch zooms; a fist compresses it |
| **Gesture reaction** | Make a 👍 or ✌️ at the camera | Freya reacts out loud, in character |
| **Sub-agents** | *"Research the best budget GPUs in the background"* | The SUB-AGENTS card shows the worker, its task and current tool |
| **Approval gate** | *"Shut down my computer"* | Confirmation card appears; `git status` runs freely, `del ...` is gated |
| **Mission mode** | *"Start a mission: research screen recorders and write a comparison to my desktop"* | Plan appears, steps tick with verification, she reports aloud |
| **Watch a video** | *"Watch this video and tell me what happens at 2:30"* + a YouTube link | She actually analyses the frames and audio |
| **Memory** | *"Remember my dentist appointment is Friday at 3pm"* | A `deadline` item appears in Settings; she reminds you when due |
| **Personas** | Click **Night Guardian** | Voice, theme, core speed and avatar posture all change |

---

## 🪐 License

MIT.
