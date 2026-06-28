# 🌌 Freya v3.0

🚀 **The Cybernetic Voice Assistant & Agent Interface**

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Gemini API](https://img.shields.io/badge/Google_Gemini-Live_API-orange?style=for-the-badge&logo=google-gemini&logoColor=white)](https://ai.google.dev/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org/)
[![OS](https://img.shields.io/badge/Platform-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)](#)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](./LICENSE)

---

Freya 3.5 is a local, real-time voice assistant establishing a low-latency bi-directional audio stream with Google Gemini Live API. Running on your Windows desktop, she acts as a conversational **agent**, dynamically executing automation on command and providing visual feedback through a browser-based dashboard.

Armed with **45+ tools**, specialized **background sub-agents**, a **proactive speech channel**, and **dynamic persona switching**, Freya doesn't just run tools; she drives your computer, researches autonomously, and extends her own capabilities.

---

## 🌟 Key Capabilities

*   🔊 **Zero-Latency Live Conversation**: Optimized 16kHz audio input and 24kHz output create a fluid, hands-free conversational loop.
*   🧠 **Self-Updating Synaptic Memory**: Details and session context are auto-extracted by `gemini-2.5-flash-lite` and appended directly to your memory bank.
*   🖥️ **Web Dashboard (freya-ui)**: Next.js 16 browser interface with real-time state visualization, tool logs, memory editing, and live audio transcripts connected via WebSockets.
*   🔄 **Dynamic System Modes**: Hot-swap Freya's personality and tools (e.g., 'coding', 'learning', 'horny') directly via voice command.

---

## 🦾 Superpowers & Autonomous Agents

Freya leverages specialized background sub-agents and advanced tools for complex, non-blocking automation.

| Superpower | What she can do | Key Tools |
| :--- | :--- | :--- |
| 📰 **Top News** | Fetches and reads the latest global / topic headlines aloud. | `get_world_news`, `get_news` |
| 🤖 **Sub-Agents** | Delegates multi-step research, coding, or UI tasks to background agents. | `dispatch_agent`, `check_agents` |
| 🌐 **Browser Use** | Autonomously drives a Chromium browser to browse or complete web tasks. | `browser_task` |
| 🎯 **System Automation** | Full control: clipboard, standard files, window management, volume/media, shut/sleep. | `clipboard_*`, `read_file`, `set_volume`, … |
| 🧩 **Modes & Persona** | Change Freya's active mode on the fly with system prompt overrides. | `switch_mode` |
| 👁️ **Ambient Awareness** | Proactively watches the screen and alerts you when conditions are met. | `watch_screen`, `stop_watching` |
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
├── config/             # Config loading, settings, device indices, mode profiles
├── core/               # System logic: audio, sub-agents, memory, model loop, tools
├── freya-ui/           # Next.js Web dashboard frontend
├── memory/             # Local long-term memory Markdown files
├── test_scripts/       # Diagnostic tools for audio, memory, and devices
├── .env                # API Keys (GEMINI_API_KEY) - Git ignored
├── main.py             # CLI entrypoint
├── server.py           # Web UI backend (FastAPI + WebSocket server)
└── requirements.txt    # Backend dependencies
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

## 🪐 License

This project is licensed under the MIT License.
