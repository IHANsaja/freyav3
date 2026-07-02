# 🌌 Freya v3.0

🚀 **The Cybernetic Voice Assistant & Agent Interface**

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Gemini API](https://img.shields.io/badge/Google_Gemini-Live_API-orange?style=for-the-badge&logo=google-gemini&logoColor=white)](https://ai.google.dev/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org/)
[![OS](https://img.shields.io/badge/Platform-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)](#)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](./LICENSE)

---

Freya 3.5 is a local, real-time voice assistant establishing a low-latency bi-directional audio stream with Google Gemini Live API. Running on your Windows desktop, she acts as a conversational **agent**, dynamically executing automation on command and providing visual feedback through a browser-based dashboard.

> [!NOTE]
> For a detailed dive into the modular design, internal subsystems, and operational patterns, see the [Architecture Documentation](./ARCHITECTURE.md).

Armed with **60+ tools**, a **mission orchestrator**, **approval-gated autopilot**, **structured long-term memory**, an **intent-driven 3D avatar**, and **always-on context awareness**, Freya doesn't just run tools; she plans, acts, verifies, remembers, and animates herself.

---

## 🌟 Key Capabilities

*   🔊 **Zero-Latency Live Conversation**: Optimized 16kHz audio input and 24kHz output create a fluid, hands-free conversational loop.
*   🎯 **Mission Mode**: Give a high-level goal — Freya plans concrete steps, executes them with background agents, verifies each result, and reports back out loud (`start_mission`).
*   🛡️ **Approval Checkpoints**: Sensitive actions (shutdowns, deletions, sending/submitting things) pause for your explicit yes — by voice or a dashboard button.
*   🧠 **Structured Memory**: Typed, searchable, editable memory items (preferences, people, projects, deadlines, follow-ups) in SQLite+FTS5, mirrored into semantic vector recall. Due items get spoken reminders.
*   👁️ **Context Awareness**: Opt-in metadata-only tracking of your active window with rate-limited proactive suggestion chips ("you've been stuck on this — want help?"). Zero screenshots unless you accept.
*   💃 **Living 3D Avatar**: Freya animates her own body through tools (`set_expression`, `set_gesture`, `trigger_thinking`, ...) — clip crossfades, procedural breathing/look-at, and shader accents. Never frozen.
*   🖥️ **Live Reasoning Panel**: The dashboard shows the active mission's plan, step progress, verification results, and awaiting-approval state in real time.
*   🎭 **Personas**: Modes now switch voice, speaking style, UI theme colors, and avatar posture (e.g. Night Guardian: soft voice, dim crimson, seated pose).
*   ⌬ **Skill Modules**: Every capability is a discoverable skill with a manifest, tool list, and enable toggle (`GET /skills` + dashboard catalog).

---

## 🦾 Superpowers & Autonomous Agents

| Superpower | What she can do | Key Tools |
| :--- | :--- | :--- |
| 🎯 **Missions** | Plan → execute → verify → report for big goals, with approval pauses. | `start_mission`, `mission_status`, `cancel_mission` |
| 🛡️ **Approvals** | Human-in-the-loop gate for sensitive/irreversible actions. | `approve_action`, `reject_action` |
| 💃 **Avatar** | Emotional expressions, gestures, poses on her 3D body. | `set_expression`, `set_gesture`, `set_idle_state`, … |
| 🧠 **Memory** | Save/search/edit/forget typed memories mid-conversation. | `remember`, `list_memories`, `forget`, `whats_coming_up` |
| 👁️ **Context** | Always-on window awareness with proactive suggestions. | `enable_context_awareness`, `watch_screen` |
| 📰 **Top News** | Fetches and reads the latest global / topic headlines aloud. | `get_world_news`, `get_news` |
| 🤖 **Sub-Agents** | Delegates multi-step research, coding, or UI tasks to background agents. | `dispatch_agent`, `check_agents` |
| 🌐 **Browser Use** | Autonomously drives a Chromium browser to browse or complete web tasks. | `browser_task` |
| 🎯 **System Automation** | Full control: clipboard, standard files, window management, volume/media, shut/sleep. | `clipboard_*`, `read_file`, `set_volume`, … |
| 🧩 **Modes & Persona** | Hot-swap personality, voice, theme, and avatar posture. | `switch_mode` |
| 🧬 **Self-Extension** | Autonomously writes, loads, and uses new Python tools. | `create_tool`, `run_code` |

### Requirements for advanced powers
```bash
pip install -r requirements.txt
playwright install chromium          # for browser-use
```

---

## 🏗️ Project Structure

```
freyav3/
├── config/                 # Config loading, mode/persona profiles, feature gates
├── core/
│   ├── events.py           # Typed event bus (+ replay buffer for reconnects)
│   ├── approvals.py        # Human-in-the-loop approval gate
│   ├── missions.py         # Plan → execute → verify → report orchestrator
│   ├── avatar.py           # Avatar animation intent tools
│   ├── memory_store.py     # Structured memory (SQLite + FTS5)
│   ├── memory_tools.py     # remember / forget / list_memories / whats_coming_up
│   ├── context_watch.py    # Always-on metadata context tracker (opt-in)
│   ├── skills/loader.py    # Skill manifests + catalog
│   ├── agents.py           # Shared ReAct executor + quick sub-agents
│   └── …                   # audio, model loop, registry, screen, browser, scheduler, …
├── freya-ui/
│   └── app/components/
│       ├── MissionPanel.tsx     # Live reasoning display
│       ├── ApprovalPrompt.tsx   # Approve/Deny cards
│       ├── SuggestionChips.tsx  # Proactive nudges
│       ├── MemoryPanel.tsx      # Structured memory editor
│       ├── SkillsPanel.tsx      # Skill catalog + toggles
│       └── avatar/              # AvatarController + model manifest
├── memory/                 # freya_memory.db (SQLite), rag_db (Chroma), schedule.json
├── test_scripts/           # Diagnostic tools for audio, memory, and devices
├── .env                    # API Keys (GEMINI_API_KEY) - Git ignored
├── main.py                 # CLI entrypoint
├── server.py               # Web UI backend (FastAPI + WebSocket server)
└── requirements.txt        # Backend dependencies
```

---

## ⚡ Quick Start

### 1️⃣ Clone and Prepare Environment

Requires **Python 3.10+**, **Node.js 18+**, and a C/C++ compiler for `pyaudio`.

```bash
# Clone the repository
git clone https://github.com/your-username/freyav3.git
cd freyav3

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt
```

### 2️⃣ Configure API Keys

Create a `.env` file in the root directory:

```env
GEMINI_API_KEY=YourGeminiApiKeyHere
```

### 3️⃣ Initialize Personal Memory

```bash
copy memory\freya_memory.example.md memory\freya_memory.md
```

---

## 🚀 Execution

Freya supports two operation modes:

### Mode 1: Web Dashboard (Recommended)

Start the Python backend and Next.js frontend separately.

```bash
# Terminal 1 — Backend (fastapi)
python server.py

# Terminal 2 — Frontend (Next.js)
cd freya-ui
npm run dev
```

Open `http://localhost:3000`.

### Mode 2: Headless CLI

```bash
python main.py
```
Use `Ctrl + C` in the terminal to stop and trigger memory persistence.

---

## 🧪 Testing the New Features

Start both servers (Mode 1), open `http://localhost:3000`, press **⚡ START FREYA**, then:

| Feature | Say / do | Expect |
| :--- | :--- | :--- |
| **Approval gate** | *"Shut down my computer"* | Freya asks for confirmation + a card appears above the dock. Say *"yes"* (or click Approve/Deny). `git status` runs freely; `del …` gets gated. |
| **Mission mode** | *"Start a mission: research the three best open-source screen recorders and write a comparison to my desktop"* | Plan appears in the right-side panel, steps tick through with verification, the out-of-project file write pauses for approval, and she reports the result aloud. |
| **Live reasoning panel** | (during any mission) | Goal, step glyphs, AWAITING APPROVAL pulse, progress bar, final report. Collapse it with **—**; cancel with the pill button or *"cancel the mission"*. |
| **Avatar intents** | *"Dance for me"*, *"look excited"*, *"show me your thinking pose"* | The 3D figure (toggle **CORE/FIGURE** in the header) crossfades gestures and always returns to a breathing idle — never a frozen T-pose. |
| **New 3D model** | Header **CORE → FIGURE** | The full-resolution Blender model (`FreyaV2.glb`) with contract clips; the shader core reacts to the same intents in CORE view. |
| **Structured memory** | *"Remember my dentist appointment is Friday at 3pm"* → open ⚙ Settings | A `deadline` item appears in LONG_TERM_MEMORY_CORE (filter, search, edit inline, forget). When it comes due, Freya says it out loud. Also try *"what's coming up?"* |
| **Context awareness** | *"Enable context awareness"*, then work in one window ~10 min | A `CTX:` line appears in the header; a single suggestion chip appears ("You've been on this a while…"). **Do it** makes her act; **✕** teaches her to nudge that kind less. Off by default — configurable under `ambient.context_tracker`. |
| **Personas** | Click **Night Guardian** mode (or say *"switch to night guardian mode"*) | Voice changes to Kore after reconnect, UI recolors to dim crimson, the core slows, and the avatar sits. Coding mode gets its own accent + terse delivery. |
| **Skills** | ⚙ Settings → SKILL_MODULES | Every capability with its tool count; toggle gated ones (applies next session). Also `curl http://localhost:8000/skills`. |

**Without a voice session** (no mic/quota needed): `POST /debug/emit` pushes any event to the dashboard, e.g.

```bash
curl -X POST http://localhost:8000/debug/emit -H "Content-Type: application/json" \
  -d '{"type":"avatar","payload":{"intent":"gesture","name":"celebrate"}}'
```

**Memory migration note:** on first run your old `memory/freya_memory.md` is imported into `memory/freya_memory.db` automatically and kept as `freya_memory.imported.md`.

---

## 🪐 License

This project is licensed under the MIT License.
