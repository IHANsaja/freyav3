<p align="center">
  <img src="docs/assets/freyja-logo.png" alt="Freyja" width="100%">
</p>

<h1 align="center">Freya v3</h1>

<p align="center">
  <b>A local, real-time voice assistant for Windows that plans, acts, verifies and remembers.</b><br>
  Gemini Live voice &middot; 120+ desktop tools &middot; background agents &middot; a 3D dashboard you steer with your hands
</p>

<p align="center">
  <a href="#quick-start"><img alt="Install: one command" src="https://img.shields.io/badge/install-one_command-0f9c6e?style=for-the-badge&logo=gnometerminal&logoColor=white"></a>
  <img alt="Windows 10 | 11" src="https://img.shields.io/badge/Windows-10_%7C_11-0078D4?style=for-the-badge&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0id2hpdGUiPjxwYXRoIGQ9Ik0yIDQuNWw4LjItMS4xdjcuOUgyek0xMS4yIDMuM0wyMiAxLjh2OS41SDExLjJ6TTIgMTIuN2g4LjJ2Ny45TDIgMTkuNXpNMTEuMiAxMi43SDIydjkuNWwtMTAuOC0xLjV6Ii8%2BPC9zdmc%2B">
  <a href="https://ai.google.dev/gemini-api/docs/live"><img alt="Gemini Live API" src="https://img.shields.io/badge/Gemini-Live_API-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white"></a>
  <a href="./LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-3DA639?style=for-the-badge"></a>
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-backend-009688?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="Next.js 16" src="https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=nextdotjs&logoColor=white">
  <img alt="React 19" src="https://img.shields.io/badge/React-19-149ECA?style=flat-square&logo=react&logoColor=white">
  <img alt="Three.js" src="https://img.shields.io/badge/Three.js-3D_dashboard-000000?style=flat-square&logo=threedotjs&logoColor=white">
  <img alt="MediaPipe" src="https://img.shields.io/badge/MediaPipe-hand_tracking-0097A7?style=flat-square&logo=google&logoColor=white">
  <img alt="Local-first" src="https://img.shields.io/badge/local--first-your_PC,_your_data-0f9c6e?style=flat-square">
  <a href="https://github.com/IHANsaja/freyav3/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/IHANsaja/freyav3?style=flat-square&color=0f9c6e"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> &nbsp;&bull;&nbsp;
  <a href="#what-she-can-do">Features</a> &nbsp;&bull;&nbsp;
  <a href="#using-freya">Using Freya</a> &nbsp;&bull;&nbsp;
  <a href="#configuration">Configuration</a> &nbsp;&bull;&nbsp;
  <a href="#development">Development</a> &nbsp;&bull;&nbsp;
  <a href="./ARCHITECTURE.md">Architecture</a>
</p>

---

## Overview

Freya holds a low-latency, two-way audio conversation with the Google Gemini Live API and acts on
your Windows desktop while she talks. Ask what you have open, tell her to launch something, ask
where a file went, or tell her your desktop is a mess: she works it out herself from an index of
your PC, without asking you for a single path.

Bigger jobs become **missions**: she plans the steps, hands them to background agents, checks each
result, and reports back out loud. Anything sensitive waits for your yes. Everything she does shows
up live on a browser dashboard with a 3D orb and avatar you can steer with your hands.

> [!NOTE]
> For the subsystems, data flow and design decisions, see [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## Quick start

Open **PowerShell** anywhere and run:

```powershell
irm https://raw.githubusercontent.com/IHANsaja/freyav3/main/install.ps1 | iex
```

That one command:

1. Installs whatever is missing of **Python, Node.js and git** (through winget; Windows may ask you to approve each one).
2. Downloads Freya into `%USERPROFILE%\freyav3`, whichever folder you ran it from.
3. Builds the Python environment and the dashboard, and installs Chromium for browser automation.
4. Asks for your **Gemini API key** (free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)) and checks it with Google.
5. **Starts Freya.** The dashboard opens in your browser, where a short setup lets you pick her personality.

**Next time**, double-click `start-freya.cmd` in `%USERPROFILE%\freyav3`.
**To update**, double-click `update-freya.cmd`, or run the same command again.

> [!TIP]
> Running the command again is also the fix for most problems: it updates Freya, asks for a key you
> skipped or one Google rejects, and repairs a half-finished install. Your `.env`, settings and
> memories are always kept.

<details>
<summary><b>Installer options</b></summary>
<br>

Run from inside the Freya folder:

| Option | Effect |
| :--- | :--- |
| `.\install.ps1 -SkipBrowser` | Skip the ~150 MB Chromium download (`browser_task` stays unavailable) |
| `.\install.ps1 -SkipFrontend` | Headless / CLI-only: no Node.js, no dashboard |
| `.\install.ps1 -InstallPath D:\ai\freya` | Install somewhere other than `%USERPROFILE%\freyav3` |
| `.\install.ps1 -NoStart` | Install or update without starting Freya |

</details>

<details>
<summary><b>Manual setup</b></summary>
<br>

Requires Python 3.10+, Node.js 18+ and git.

```powershell
git clone https://github.com/IHANsaja/freyav3.git
cd freyav3
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cd freya-ui; npm.cmd install; cd ..
# then create .env containing:  GEMINI_API_KEY=...
```

`config/freya_config.json` is created from `config/freya_config.example.json` the first time
Freya starts; you never need to write it. Its `apps` and `projects` blocks are optional overrides,
because `open_app` finds anything installed on its own.

</details>

<details>
<summary><b>Optional: Jev (TypeSafe System One)</b></summary>
<br>

Jev is an early-access API for fast routing and triage decisions. If you have a key, enter it when
the installer asks, or add `TYPESAFE_API_KEY=...` to `.env`; Freya then uses Jev with Gemini as the
fallback. Without a key she runs on Gemini alone, with nothing else to configure. The startup log
says which: `Jev: on` or `Jev: off - running on Gemini only`.

</details>

---

## What she can do

### Conversation

| Capability | Details |
| :--- | :--- |
| **Live voice** | 16 kHz in / 24 kHz out on a dedicated audio thread pool, so background work never makes her stutter. |
| **Talks first, one job at a time** | Says what she is about to do before doing it, keeps chatting while a long job runs, and queues new requests until it finishes. |
| **Personalities** | Pick Friendly, Quick or Focused (each with its own Gemini model), then tune warmth, humour, detail and initiative. Modes such as Night Guardian change voice, style, colours and posture. |
| **Stays up when Google doesn't** | Repeated Live-server errors switch to a fallback voice model; overloaded background models retry on a lighter one; a silent turn gets a nudge. |

### Your PC

| Capability | What it covers | Key tools |
| :--- | :--- | :--- |
| **Knows your machine** | Installed apps (Start Menu, registry, Store apps, portable exes), projects and documents, indexed and searched live. Launches anything by name. | `open_app`, `find_on_pc`, `list_installed_apps` |
| **Desktop awareness** | Open programs grouped by app, with the focused window marked. | `list_windows`, `get_active_window` |
| **System automation** | Clipboard, windows, volume and media, lock and sleep, UI Automation control of any app. | `clipboard_*`, `focus_window`, `control_element` |
| **Files** | Copy, move, rename, recycle, zip, inspect, reveal in Explorer, find large or recent files. | `copy_item`, `move_item`, `delete_item`, `zip_item` |
| **Tidy up** | Sorts a cluttered folder into type folders in one pass, leaving shortcuts and code projects alone. Fully reversible. | `organize_folder`, `undo_organize` |
| **Browser** | Drives a real Chromium window like a person: search, curved mouse moves, typing, scrolling, reading. | `browser_task`, `browser_research` |
| **Web and news** | Quota-free search and page reading, plus live headlines projected into the dashboard. | `web_search`, `web_fetch`, `get_world_news` |
| **Watch video** | Watches a YouTube link or local file and answers questions about it. | `use_skill("watch")` |

### Agents and missions

| Capability | What it covers | Key tools |
| :--- | :--- | :--- |
| **Missions** | Plan, execute, verify and report for large goals, pausing for approval where needed. | `start_mission`, `mission_status`, `cancel_mission` |
| **Sub-agents** | Research, coding or UI work handed to background workers on their own threads. | `dispatch_agent`, `check_agents` |
| **Approvals** | Sensitive or irreversible actions wait for your yes, by voice or a dashboard button. | `approve_action`, `reject_action` |
| **Self-extension** | Writes, loads and uses new Python tools of her own. | `create_tool`, `run_code` |
| **Career Ops** | Bridge to [career-ops](https://github.com/santifer/career-ops): portal scans, offer evaluation, CV tailoring. | `use_career_mode`, `run_career_script` |
| **Trading Lab** | Simulation-only BTC/ETH practice on live candles, with replay, a decision journal and a patient teacher. See [docs/TRADING_LAB.md](docs/TRADING_LAB.md). | `open_trading_lab`, `analyze_chart`, `paper_order` |

### Memory and awareness

| Capability | What it covers | Key tools |
| :--- | :--- | :--- |
| **Structured memory** | Typed, searchable, editable items in SQLite + FTS5, mirrored into semantic recall. Due items get spoken reminders. | `remember`, `list_memories`, `forget` |
| **Day context** | What today has been about; rotated at 4 am, carrying open threads into tomorrow. | `note_day_context`, `get_day_context` |
| **Session recall** | Re-reads what was said earlier instead of asking you to repeat it. | `recall_conversation` |
| **Context awareness** | Opt-in, metadata-only tracking of your active window with rate-limited suggestions. No screenshots unless you accept. | `enable_context_awareness`, `watch_screen` |

### Dashboard and presence

| Capability | Details |
| :--- | :--- |
| **Live dashboard** | Sub-agent activity, the running conversation, mission progress and real system telemetry. |
| **3D avatar** | She animates her own body through tools: expressions, gestures, poses, procedural breathing and look-at. |
| **Hand-gesture control** | Rotate, zoom and squeeze the orb through your webcam; she reacts to hand signs. See [Hand gestures](#hand-gestures). |
| **Activity pill** | A click-through pill at the top of your screen shows what she is doing right now, with a timer. |
| **Desktop overlay** | GLSL effects drawn over the live desktop (lock-on, click impact, capture scan, cursor trail) in your persona's colour. |
| **Cards where you look** | `show_info` / `show_image` land beside your work when you are heads-down, and on the dashboard when you are watching it. |

---

## Using Freya

### Try saying

| You say or do | What happens |
| :--- | :--- |
| *"What have I got open?"* | Programs grouped by app, with the one in front marked |
| *"Open Blender"* (or any app you never configured) | It launches; she never asks where it is |
| *"Where's my CV?"* / *"Open my latest CV"* | Best name match, newest first, from any drive |
| *"My desktop is a mess, sort it out"* | Files sorted into type folders; *"undo"* puts everything back |
| *"Research the best budget GPUs in the background"* | A sub-agent appears on the dashboard with its task and current tool |
| *"Start a mission: compare screen recorders and write it to my desktop"* | A plan appears, steps tick off with verification, she reports aloud |
| *"Shut down my computer"* | An approval card appears; nothing happens until you confirm |
| *"Remember my dentist appointment is Friday at 3pm"* | A deadline memory is saved and she reminds you when it is due |
| *"What did I work on yesterday?"* | An answer from the rotated day summary, not a guess |
| *"Watch this video and tell me what happens at 2:30"* + a link | She analyses the frames and audio |
| *"Open the trading lab"* | Opens in your browser (or reuses your tab) and follows the chart you are on |

### Hand gestures

Turn it on with the hand icon in the header (it asks for camera access). MediaPipe runs locally
from `freya-ui/public/mediapipe/`, with no CDN calls.

| Gesture | Effect |
| :--- | :--- |
| Move an open hand | Rotates the orb (the scene and camera stay put) |
| Pinch thumb and index, then spread or close | Zooms the orb in or out |
| Close your fist | Compresses the orb with your grip, springing back on release |
| Victory, thumbs up / down, pointing, rock-on | Freya reacts out loud, in character |

Tracking alone never changes the orb: squeezing needs a genuinely closed hand, rotation pauses while
you pinch, and grip and pinch use different fingers so zoom and squeeze stay independent.

### Personality

On first run the dashboard opens a short setup; the sliders button in the header reopens it any time.

| Style | Model | Best for |
| :--- | :--- | :--- |
| **Friendly** | Gemini 3.1 Flash Live | The most friendly and energetic version |
| **Quick** | Gemini 3.8 Live | Faster responses and quick work, less chatty |
| **Focused** | Gemini 3.8 Live Extended Thinking | Putting the task first; harder, multi-step work |

Then set warmth, humour, detail and initiative, her voice, an accent colour, what she calls you, and
anything else she should know. Your choices are added on top of her core instructions, so tools and
safety rules are unaffected.

---

## Configuration

### Your name

Nothing in the code knows who you are. Your name lives in one file, `memory/MEMORY.md`, which the
installer and the personality setup write for you. To edit it by hand:

```markdown
# Freya Memory - Jane Doe

## Personal
- Name: Jane Doe
- Preferred name: Jane
```

She uses it the way someone close to you would: at greetings, reassurance, and when picking a
thread back up. Without the file she simply says "you".

### Models and fallbacks

| Role | Default | Falls back to |
| :--- | :--- | :--- |
| Voice | Chosen in the personality setup (`gemini-3.8-live` by default) | `gemini-3.1-flash-live-preview` on quota or availability errors, or a second `1011` in a row |
| Voice, Complex Tasks mode | `gemini-3.8-live-extended-thinking` | `gemini-3.8-live`, then the 3.1 fallback |
| Missions, sub-agents, chart analysis | `gemini-3.5-flash` | `gemini-3.5-flash-lite`, once, when flash is overloaded |
| Fast decisions (routing, triage, approval risk) | Jev, only with `TYPESAFE_API_KEY` | Gemini and built-in heuristics |

Voices keep their names across models but each model renders them itself, so *Zephyr* on 3.8 does
not sound identical to *Zephyr* on 3.1. More in [docs/GEMINI_MODELS.md](docs/GEMINI_MODELS.md) and
[docs/QUOTA_AND_RELIABILITY.md](docs/QUOTA_AND_RELIABILITY.md).

### Access control

File-touching tools pass through a sandbox (`core/safety.py`), editable in **Settings > ACCESS_CONTROL**:

- **Allowed folders** - the roots she may modify. Empty means the safe default: your home folder and the Freya project.
- **Confirm sensitive actions** - the approval gate for deletions, sends, submissions and writes outside the project.
- **Unrestricted mode** - turns the sandbox off. Off by default.

> [!IMPORTANT]
> The API can approve actions and drive your desktop and has no login, so it is locked to this
> machine: the backend listens on `127.0.0.1` only, and the WebSocket accepts browsers only from the
> dashboard origin (`localhost:3000`). Opening the dashboard from another device needs a deliberate
> change.

> [!IMPORTANT]
> Everything under `memory/`, plus `config/freya_config.json` and `.env`, is gitignored. Her memory
> is effectively a diary of who you are and what you did; it is rebuilt locally on first run, so a
> clone loses nothing. If you fork this, keep it that way.

<details>
<summary><b>Context budget</b></summary>
<br>

The system prompt and every tool declaration are re-sent on each turn, so they cost tokens every
time and shrink the room left for conversation. Only 27 core tools are declared in full; the other
~96 are listed by name and reached through `search_tools` then `run_tool` (`core/tool_index.py`).

| | Tokens | Set by |
| :--- | ---: | :--- |
| Model input limit (`gemini-3.1-flash-live-preview`) | 131,072 | Google |
| `freya.compression_trigger_tokens` | 96,000 | you |
| `freya.compression_target_tokens` | 32,000 | you |
| Baseline: system prompt + 27 core tools | ~6,250 | code |
| Conversation kept after a compression | ~25,700 | result |

She prints this at startup, and warns loudly if the target ever drops below the baseline, which
would look exactly like her forgetting what you just said:

```text
Context budget: baseline ~6,257 tok (prompt 3,603 + 27 tools 2,654)
                trigger 96,000 / target 32,000 -> ~25,743 tok for conversation
```

</details>

---

## Skills

Freya has two complementary skill systems:

- **Python skills** register callable tools with `@tool` and are listed in `core/skills/loader.py`
  with a manifest and an enable gate. Browse them in **Settings > SKILL_MODULES** or `GET /skills`.
- **Markdown skill packs** are Claude-style `SKILL.md` folders under `skills/`, following the open
  Agent Skill Standard with progressive disclosure: every skill's name and description is always
  visible, the full instructions load only on `use_skill(name)`, and bundled scripts run through
  `run_skill_script` without taking up context.

```text
skills/
  watch/
    SKILL.md          frontmatter (name, description) + instructions
    scripts/watch.py  bundled script, run on demand
```

Third-party agent-standard skills can be dropped into `skills/` and used essentially unmodified.

---

## Development

### Running manually

```powershell
.\start-freya.cmd                        # backend + dashboard, opens the browser

.\venv\Scripts\python.exe server.py      # or: backend only   (127.0.0.1:8000)
cd freya-ui; npm.cmd run dev             #     dashboard only (localhost:3000)

.\venv\Scripts\python.exe main.py        # headless CLI; Ctrl+C stops and saves memory
```

Useful startup lines:

```text
  Jev: off (no TYPESAFE_API_KEY) - running on Gemini only.
Connecting to gemini-3.8-live...
  Tool index: 27 tools loaded, 96 deferred
```

<details>
<summary><b>Project structure</b></summary>
<br>

```text
freyav3/
|-- config/
|   |-- freya_config.example.json   tracked template, copied on first run
|   |-- persona.py                  personality styles, sliders and prompt tuning
|   `-- freya_config.json           your local config (gitignored)
|-- core/
|   |-- model.py                    live session loop
|   |-- live_protocol.py            model routing, fallbacks, auth-failure detection
|   |-- events.py                   typed event bus with a replay buffer
|   |-- safety.py / approvals.py    folder sandbox and the approval gate
|   |-- missions.py / agents.py     mission orchestrator and background sub-agents
|   |-- machine_index.py            the PC map: apps, projects, documents (SQLite)
|   |-- memory_store.py             structured memory (SQLite + FTS5)
|   |-- day_context.py              rolling day context and 4 am rotation
|   |-- user_identity.py            reads memory/MEMORY.md, the only source of your name
|   |-- tool_index.py               core tools loaded, the rest on demand
|   |-- audio.py                    mic / speaker streams and device selection
|   |-- browser/  shaders/  trading/  skills/
|   `-- ...
|-- freya-ui/app/
|   |-- components/hud/             dashboard cards
|   |-- components/scene/           orb, shaders, hand-driven rotation and zoom
|   `-- hooks/                      socket, hand tracking, gesture bridge
|-- skills/                         markdown skill packs
|-- memory/                         runtime data, all gitignored
|-- test_scripts/                   pytest suites and script checks
|-- install.ps1                     one-command installer and updater
|-- server.py                       FastAPI + WebSocket backend
`-- main.py                         headless CLI
```

</details>

<details>
<summary><b>HTTP API</b></summary>
<br>

| Endpoint | Purpose |
| :--- | :--- |
| `GET /status` | Session telemetry: running, start time, model, voice, mode, tool count |
| `GET /agents` | Live sub-agent and browser jobs with their current step |
| `GET` `POST` `/config` | Model, voice, mode and audio devices (unknown values return HTTP 400) |
| `GET` `POST` `/persona` | Personality setup: style, sliders, voice, accent, name |
| `GET` `POST` `/safety` | The access-control sandbox |
| `GET` `POST` `PATCH` `DELETE` `/memory/items` | Structured memory |
| `GET /skills` | Skill catalog with tools and gate state |
| `GET /audio/devices` | Microphones and speakers, with the Windows defaults flagged |
| `/trading/*` | Trading Lab sessions, candles, analysis and workspace |
| `POST /debug/emit` | Push any event to the dashboard without a voice session |

Exercise the dashboard with no microphone or quota:

```bash
curl -X POST http://localhost:8000/debug/emit -H "Content-Type: application/json" \
  -d '{"type":"agent","payload":{"id":"res-1","agent":"researcher","task":"Compare GPUs","status":"working","step":"web_search"}}'
```

</details>

### Tests

Offline: no microphone, no API quota, no network. Run from the project root.

```powershell
.\venv\Scripts\python.exe -m pytest -q test_scripts\test_live_routing.py test_scripts\test_voice_lifecycle.py `
  test_scripts\test_session_resilience.py test_scripts\test_find_documents.py test_scripts\test_systemone.py `
  test_scripts\test_activity_overlay.py test_scripts\test_trading_open.py test_scripts\test_quota_fixes.py `
  test_scripts\test_api_key_auth.py test_scripts\test_audio_devices.py test_scripts\test_persona.py
```

They cover the live loop against a fake Gemini session (including the one-job-at-a-time queue),
fallbacks, key handling, audio devices, the personality setup, search, the Trading Lab and the
activity pill. Other files in `test_scripts\` need a real key or hardware.

<details>
<summary><b>Script checks</b></summary>
<br>

```powershell
.\venv\Scripts\python.exe test_scripts\test_smoke.py       # config, skills, gates, safety
.\venv\Scripts\python.exe test_scripts\test_shaders.py     # GLSL compiles, every effect draws
.\venv\Scripts\python.exe test_scripts\test_awareness.py   # windows, focus, declarations
.\venv\Scripts\python.exe test_scripts\test_search.py      # index ranking and live search
.\venv\Scripts\python.exe test_scripts\test_organizer.py   # tidy / undo round trip
```

Run `test_smoke.py` before a release: it proves a fresh clone's config loads, every skill imports,
every declared tool has a handler, nothing harmless asks for approval, and the safety gate still
refuses to write into Windows or move a git repo.

</details>

---

<p align="center">
  <sub>MIT License &copy; 2026 Ihan Hansaja &middot; see <a href="./LICENSE">LICENSE</a> and <a href="docs/THIRD_PARTY_NOTICES.md">third-party notices</a></sub>
</p>
