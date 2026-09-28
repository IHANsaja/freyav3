<p align="center">
  <img src="docs/assets/freyja-logo.png" alt="Freyja" width="100%">
</p>

# 🌌 Freya v3.0

**Trading Lab:** open `/trading` for simulation-only BTC/ETH practice, replay,
decision journaling and chart explanations. See [setup, execution rules and tests](docs/TRADING_LAB.md).

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

Armed with **113 tools**, a **mission orchestrator**, **approval-gated autopilot**, **structured long-term memory**, a **rolling day context**, **webcam hand-gesture control**, an **intent-driven 3D avatar**, **always-on context awareness**, and an **on-screen activity pill**, Freya doesn't just run tools; she plans, acts, verifies, remembers, and animates herself.

She also knows the machine she lives on. Ask her what you've got open, tell her to launch
something, ask where a file went, or tell her your desktop is a mess — she resolves all of it
herself from an index of your PC, without asking you for a single path.

---

## ⚡ Install (one command)

Open **PowerShell** and run:

```powershell
irm https://raw.githubusercontent.com/IHANsaja/freyav3/main/install.ps1 | iex
```

The installer checks prerequisites, clones the repo, builds the Python venv and the dashboard, installs Chromium for browser automation, prompts for your Gemini API key (plus an optional Jev key, see below), and writes `start-freya.ps1` and `update-freya.ps1` launchers.

**Updating:** run `.\update-freya.ps1` in the Freya folder. It pulls the latest code, refreshes the Python packages and the dashboard, and keeps your `.env`, settings and memories. Re-running the one-line command from the folder that contains `freyav3` does the same.

Run the one-liner from a normal folder such as your home directory. An admin PowerShell starts in `C:\Windows\System32`; the installer no longer installs there (git refuses to update that folder) and uses your home folder instead, copying the keys, settings and memories of an older `System32` install into the new one.

**Then:**

```powershell
.\start-freya.ps1
```

Both servers start, and `http://localhost:3000` opens as soon as the dashboard is ready. The backend listens on this machine only (`127.0.0.1:8000`).

**Jev is optional.** Jev (TypeSafe System One) is an early-access API for fast routing and triage decisions. If you have a key, enter it when the installer asks (or add `TYPESAFE_API_KEY=...` to `.env`) and Freya uses Jev with Gemini as the fallback. Without a key she runs on Gemini alone; nothing else to configure. The startup log says which: `Jev: on` or `Jev: off — running on Gemini only`.

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
# create .env with GEMINI_API_KEY=...  (and TYPESAFE_API_KEY=... only if you have Jev access)
```

`config/freya_config.json` is created automatically from `config/freya_config.example.json`
the first time Freya starts — you don't need to write one. The `apps` and `projects` blocks in
it are **optional overrides**: `open_app` resolves anything installed from its own PC index, so
leaving them empty is the normal case.

</details>

---

## 🌟 Key Capabilities

*   🔊 **Zero-Latency Live Conversation**: 16 kHz input / 24 kHz output on a dedicated audio thread pool, so background agents can never stutter her voice.
*   💬 **Talks First, One Job at a Time**: She says what she's about to do *before* she does it, keeps chatting while a long job runs, and queues anything new you ask for until the current job is done — no silent stretches, no overlapping desktop actions.
*   🟢 **Activity Pill**: A small status pill at the top of your screen always shows what she's doing right now — *Thinking…*, *Searching your PC for "resume"*, *Waiting for your OK* — with a running timer. Click-through, never steals focus, invisible to her own screenshots.
*   🛟 **Keeps Going When Google Doesn't**: Repeated Live-server errors switch her to the fallback voice model; an overloaded or exhausted background model retries once on a lighter one; a turn that comes back silent gets a nudge instead of leaving her mute.
*   ✳️ **Real GLSL Desktop Overlay**: You watch her work. Six fragment-shader effects — target lock-on, click impact, capture scan, cursor trail, scroll flow, typing — rendered over the live desktop with noise fields, chromatic aberration, hex lattices and glitch displacement. Colour follows your active persona, so switching mode re-skins your whole screen.
*   🖥️ **She Knows Your Desktop**: What programs are open, which window is in front, where any file lives, and how to launch anything installed — Start Menu, registry, Microsoft Store apps and portable exes all indexed. You never give her a path.
*   🧹 **Tidy Up**: *"Organise my desktop"* sorts loose files into type folders in one pass, leaves your shortcuts and code projects alone, and is reversible with *"undo"*.
*   🖐️ **Hand-Gesture Control**: Steer the 3D orb with your webcam — move to rotate, pinch to zoom, squeeze to compress. She reacts out loud to deliberate hand signs.
*   🎯 **Mission Mode**: Give a high-level goal — Freya plans steps, executes them with background agents, verifies each result, and reports back out loud.
*   🛡️ **Approval Checkpoints**: Sensitive actions pause for your explicit yes — by voice or a dashboard button — with an editable folder sandbox.
*   🧠 **Structured Memory**: Typed, searchable, editable memory items in SQLite+FTS5, mirrored into semantic vector recall. Due items get spoken reminders.
*   📅 **Day Context**: She knows what *today* has been about — what you worked on, where the hours went, what's still open — and rotates it at 4am, carrying unfinished threads into tomorrow.
*   🪪 **She Knows You by Name**: One file, `memory/MEMORY.md`, is the only place your name and profile live. She uses it the way someone close to you would.
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
| 🌐 **Browser** | Drives a real Chromium window the way a person does — DuckDuckGo search, curved mouse moves, typed keystrokes, scrolling and reading. Built from scratch in `core/browser`. | `browser_task`, `browser_research`, `browser_open`, `browser_status` |
| 🔎 **Web & News** | Quota-free search/fetch plus live headlines projected into the scene. | `web_search`, `web_fetch`, `get_world_news` |
| 🖼️ **Show, Don't Say** | Puts what she found on screen, following your attention: a card on the right of your screen when you're heads-down, the dashboard when you're actually looking at it. | `show_info`, `show_image` |
| 📅 **Day Context** | Knows what today has been about; rotates and summarises the day at 4am, carrying open threads forward. | `note_day_context`, `get_day_context`, `rotate_day_context` |
| 🔦 **PC Knowledge** | Knows where your apps, projects and documents live, and searches the disk live when they aren't indexed. Launches anything installed by name — no path, ever. Documents come back best match first, newest first among equals, so *"my latest CV"* finds the new one. | `open_app`, `find_on_pc`, `list_installed_apps`, `refresh_pc_knowledge` |
| 📈 **Trading Lab** | Paper-trading practice on live Coinbase candles with a patient teacher. Opening it reuses the tab you already have (or opens one in *your* browser) and follows the session you're looking at. | `open_trading_lab`, `get_trading_lab_context`, `analyze_chart`, `draw_on_chart`, `paper_order` |
| 🖥️ **Desktop Awareness** | What programs are open, grouped by app, with the focused window marked; optionally every background process too. | `list_windows`, `get_active_window` |
| 🧹 **Tidy Up** | Sorts a cluttered folder into type-based subfolders in one pass, skipping shortcuts and code projects. Fully reversible. | `organize_folder`, `undo_organize` |
| 📁 **File Manager** | Copy, move/rename, recycle, zip/unzip, inspect, reveal in Explorer, find large/recent files. | `copy_item`, `move_item`, `delete_item`, `zip_item`, `find_files_by`, … |
| 🎬 **Watch Video** | Actually watches a YouTube link or local file and answers questions about it. | `use_skill("watch")` |
| 💼 **Career Ops** | Bridged [career-ops](https://github.com/santifer/career-ops): scan portals, A–G offer evaluation, CV tailoring, tracking. | `use_career_mode`, `run_career_script` |
| 💃 **Avatar** | Emotional expressions, gestures, poses on her 3D body. | `set_expression`, `set_gesture`, `set_idle_state` |
| 🧠 **Memory** | Save/search/edit/forget typed memories mid-conversation, and re-read what was said earlier this session. | `remember`, `list_memories`, `forget`, `whats_coming_up`, `recall_conversation` |
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
├── config/
│   ├── freya_config.example.json  # Tracked template — copied to freya_config.json on first run
│   └── freya_config.json          # Your local config (gitignored: machine-specific paths)
├── core/
│   ├── events.py           # Typed event bus (+ replay buffer for reconnects)
│   ├── errors.py           # Shared logger + safe client error payloads
│   ├── safety.py           # Folder sandbox + approval rules
│   ├── approvals.py        # Human-in-the-loop approval gate
│   ├── missions.py         # Plan -> execute -> verify -> report orchestrator
│   ├── agents.py           # Sub-agents (own thread + event loop each)
│   ├── file_manager.py     # Copy/move/recycle/zip/inspect file operations
│   ├── organizer.py        # Tidy a cluttered folder into type buckets, reversibly
│   ├── shader_overlay.py   # GLSL desktop overlay host (loads core/shaders/)
│   ├── shaders/            # Real .glsl — lib/ helpers + fx/ per effect
│   ├── machine_index.py    # The PC map: apps, projects, documents (SQLite)
│   ├── md_skills.py        # SKILL.md packs w/ progressive disclosure
│   ├── career_ops.py       # career-ops bridge
│   ├── memory_store.py     # Structured memory (SQLite + FTS5)
│   ├── day_context.py      # Rolling day context + daily rotation
│   ├── user_identity.py    # Reads memory/MEMORY.md — the only source of your name
│   ├── context_watch.py    # Always-on metadata context tracker (opt-in)
│   ├── desktop_popup.py    # show_info / show_image cards outside the dashboard
│   ├── activity_overlay.py # The "what she's doing now" pill at the top of the screen
│   ├── systemone.py        # Optional Jev (TypeSafe) fast decisions — on only with a key
│   ├── quota.py            # Gemini pacing, retries, flash -> flash-lite fallback
│   ├── proc.py             # subprocess with a timeout that really returns (tree kill)
│   ├── tool_index.py       # search_tools / run_tool: core tools loaded, the rest on demand
│   ├── trading/            # Trading Lab: simulator, live data, teacher, chart tools
│   └── ...                 # audio, model loop, registry, screen, browser, scheduler
├── freya-ui/
│   └── app/
│       ├── components/hud/     # AgentsCard, ChatCard, SystemStatusCard, ...
│       ├── components/scene/   # Orb + shaders, hand-driven rotation/zoom/squeeze
│       ├── hooks/useHandGestures.ts     # MediaPipe webcam tracking
│       └── hooks/useGestureOrbBridge.ts # Gesture -> reaction dispatch
├── skills/watch/           # Markdown skill pack: video watching
├── memory/                 # ALL generated at runtime and gitignored — see below
│   ├── MEMORY.md           # Who you are — copy MEMORY.example.md
│   ├── freya_memory.db     # Structured memory + day context (SQLite)
│   ├── machine_index.db    # The PC map
│   └── rag_db/             # Chroma vector store
├── test_scripts/           # pytest suites + test_smoke / test_awareness / test_organizer scripts
├── install.ps1             # One-command installer
├── main.py                 # CLI entrypoint
├── server.py               # FastAPI + WebSocket backend
└── requirements.txt
```

> [!IMPORTANT]
> **Everything under `memory/` is gitignored, and so is `config/freya_config.json`.** Freya
> remembers what you tell her, and that memory is a diary — who you are, what you worked on,
> what you asked for and when. It is rebuilt locally on first run, so a clone loses nothing.
> If you fork this, keep it that way.

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

The backend prints a few status lines at startup worth knowing:

```
  Jev: off (no TYPESAFE_API_KEY) — running on Gemini only.
Connecting to gemini-3.8-live...
  Tool index: 27 tools loaded, 96 deferred
  Context budget: baseline ~6,257 tok (prompt 3,603 + 27 tools 2,654)
```

---

## 🧠 Models & Resilience

| Role | Default | Falls back to |
| :--- | :--- | :--- |
| Voice (default mode) | `gemini-3.8-live` | `gemini-3.1-flash-live-preview` on quota/unavailable errors, or on a **second** `1011 Internal error` in a row |
| Voice (Complex Tasks mode) | `gemini-3.8-live-extended-thinking` | `gemini-3.8-live`, then the 3.1 fallback |
| Missions, sub-agents, chart analysis | `gemini-3.5-flash` | `gemini-3.5-flash-lite`, once, when flash is overloaded or out of quota (`quota.fallback_models`) |
| Fast decisions (tool routing, mission checks, memory triage, approval risk) | Jev, **only if `TYPESAFE_API_KEY` is set** | Gemini / built-in heuristics — the normal path without a key |

Pick the voice model in ⚙ Settings. Voices keep their names across models but are rendered by
each model's own audio stack, so *Zephyr* on 3.8 does not sound identical to *Zephyr* on 3.1.

**Live-session safety nets** — all logged, so you can see when they fire:

- `[live] empty model turn; nudging it to respond.` — the model closed a turn with no speech and no action (3.8 has proactive audio permanently on and sometimes chooses silence).
- `[live] model went quiet 8s after a tool result; nudging it on.` — a tool result that got no follow-up (`live.stall_nudge_s`).
- `Spoken tool call caught: …` — she said call syntax out loud instead of making the call; it's scrubbed and she's told to make it.
- Pausing listening sends `audio_stream_end`, so she hears you again straight after you resume.

---

## 🪪 Telling Her Who You Are

Nothing in the code knows your name. Copy the template and fill it in:

```powershell
copy memory\MEMORY.example.md memory\MEMORY.md
```

```markdown
# Freya Memory — Jane Doe

## Personal
- Name: Jane Doe
- Preferred name: Jane      # optional; otherwise she uses your first name
```

`memory/MEMORY.md` is the **only** source for your name — never the config, never your Windows
account folder, never something she inferred mid-conversation. She reads it at startup and
addresses you by name the way someone close to you would: at greetings, reassurance, and when
picking a thread back up — not in every sentence. Without the file she simply says "you".

It's gitignored, so the repo never carries your details.

---

## 🧮 Context Budget

Freya's *immovable* context — system prompt plus every tool declaration — is re-sent on every
turn, so it costs you on each one and eats into what's left for the conversation.

| | tokens | set by |
| :--- | ---: | :--- |
| model input limit (131,072 for `gemini-3.1-flash-live-preview`) | per model | Google |
| `freya.compression_trigger_tokens` | 96,000 | you |
| `freya.compression_target_tokens` | 32,000 | you |
| baseline: system prompt + 27 core tool declarations | ~6,250 | code |
| conversation retained after a compression | ~25,700 | result |

Only a core set of tools is declared in full. The other ~96 are listed by name and reached
through `search_tools` → `run_tool` (`core/tool_index.py`), which is what halved the baseline.
She prints this at startup so it can never drift silently:

```
Context budget: baseline ~6,257 tok (prompt 3,603 + 27 tools 2,654)
                trigger 96,000 / target 32,000 -> ~25,743 tok for conversation
```

If the target ever drops below the baseline she says so loudly — that combination shreds the
conversation on every turn, and it looks exactly like her "forgetting" what you just told her.

---

## 🔐 Access Control

Freya can write files, run code, and drive your desktop, so file-touching tools pass through a sandbox first (`core/safety.py`).

Edit it in **⚙ Settings → ACCESS_CONTROL**:

- **Allowed folders** — add/remove the roots she may modify. Empty means the safe default: your home folder and the Freya project. Paths are validated server-side.
- **Confirm sensitive actions** — the approval gate for deletions, sends, submissions, and out-of-project writes.
- **Unrestricted mode** — disables the folder sandbox entirely. Off by default; only enable if you understand the consequences.

**Network exposure.** The API can approve actions, change the sandbox and drive your desktop,
and it has no login of its own, so it is locked to this machine:

- The backend listens on `127.0.0.1` only — not reachable from your LAN.
- The WebSocket accepts browser connections only from the dashboard origin
  (`http://localhost:3000` / `http://127.0.0.1:3000`). A random website open in your browser
  can no longer connect and approve a pending action. Local scripts that send no `Origin`
  header still work.
- Settings and memory writes are validated: an unknown model/voice/device or an empty memory
  is rejected with HTTP 400 instead of being saved.

Opening the dashboard from a phone on your LAN therefore needs a deliberate change (a token and
a different bind address) — it is not on by default.

---

## 🔌 HTTP API

| Endpoint | Purpose |
| :--- | :--- |
| `GET /status` | Session telemetry: running, startedAt, model, voice, mode, tool count |
| `GET /agents` | Live sub-agent + browser jobs with their tasks and current step |
| `GET`/`POST` `/safety` | Read/update the access-control sandbox |
| `GET`/`POST` `/config` | Model, voice, mode, audio input/output devices (validated — unknown values get HTTP 400) |
| `GET`/`POST`/`PATCH`/`DELETE` `/memory/items` | Structured memory CRUD (empty content is rejected) |
| `GET /skills` | Skill catalog with tools + gate state |
| `GET /audio/devices` | Input/output device enumeration |
| `/trading/*` | Trading Lab sessions, live candles, analysis, and the workspace the page reports |
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
| **Attention-aware cards** | While studying or watching something, ask her to look something up | The answer lands as a card on the right of your screen, not on a dashboard you aren't looking at |
| **Day context** | *"What did I work on yesterday?"* | She answers from the rotated day summary, not a guess |
| **Carry-over** | *"Note that the API refactor is still open"* | It's tagged open and reappears in tomorrow's context after the 4am rotation |
| **Session recall** | Discuss something, talk for a while, then refer back to it obliquely | She looks it up in the transcript instead of asking you to repeat |
| **Your name** | Just talk to her | She uses your first name naturally — never a pet name |
| **Personas** | Click **Night Guardian** | Voice, theme, core speed and avatar posture all change |
| **What's open** | *"What have I got open?"* | Programs grouped by app, with the one in front marked |
| **Open anything** | *"Open Blender"* — or any app you've never configured | It launches. She never asks where it is |
| **Find a file** | *"Where's my CV?"* | The path, from the index or a live disk walk — no questions back |
| **Tidy the desktop** | *"My desktop is a mess, sort it out"* | Files sorted into type folders; shortcuts and repos untouched; *"undo"* puts it all back |
| **Activity pill** | *"Find the Freya Constitution and open it"* | A pill at the top of your screen: *Searching your PC for "Freya Constitution"*, then *Opening FREYA CONSTITUTION v1.2.pdf* |
| **Talk first, one job at a time** | Ask for a slow search, then ask something else while it runs | She says what she's doing before starting, chats meanwhile, and runs the second request only after the first finishes |
| **Latest document** | *"Open my latest CV — it's called something like full stack developer"* | Best name match, newest first, from any drive |
| **Trading Lab** | *"Open the trading lab"* | Opens in your browser (or reuses your open tab) and works on the chart you're looking at |
| **Windows** | *"Open VS Code, minimize it, maximize it, close it"* | Every step hits the same window — never another VS Code you had open |

---

## 🧪 Tests

Offline suites — no mic, no API quota, no network. Run them from the project root.

The pytest suites cover the live loop (with a fake Gemini session), tool scheduling, fallbacks,
search, the Trading Lab and the activity pill:

```powershell
.\venv\Scripts\python.exe -m pytest -q test_scripts\test_live_routing.py test_scripts\test_voice_lifecycle.py `
  test_scripts\test_session_resilience.py test_scripts\test_find_documents.py test_scripts\test_systemone.py `
  test_scripts\test_activity_overlay.py test_scripts\test_trading_open.py test_scripts\test_quota_fixes.py
```

`test_live_routing.py` includes the one-job-at-a-time scenario: a slow job goes to the
background, a second request is answered "queued" and only starts after the first finishes,
an expression runs instantly, and both results are delivered in order.

Script-style checks:

```powershell
.\venv\Scripts\python.exe test_scripts\test_shaders.py     # GLSL compiles + every effect draws
.\venv\Scripts\python.exe test_scripts\test_smoke.py       # config, skills, gates, safety
.\venv\Scripts\python.exe test_scripts\test_awareness.py   # windows, focus, declarations
.\venv\Scripts\python.exe test_scripts\test_search.py      # index ranking + live search
.\venv\Scripts\python.exe test_scripts\test_organizer.py   # tidy/undo round trip
```

`test_smoke.py` is the one to run before a release: it proves a fresh clone's config loads,
every skill imports, every declared tool has a handler, nothing harmless asks for approval,
and the safety gate still refuses to write into Windows or move a git repo.

---

## 🪐 License

MIT.
