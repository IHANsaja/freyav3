# 🌌 Freya v3.0

🚀 **The Cybernetic Voice Assistant**

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Gemini API](https://img.shields.io/badge/Google_Gemini-Live_API-orange?style=for-the-badge&logo=google-gemini&logoColor=white)](https://ai.google.dev/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org/)
[![Modality](https://img.shields.io/badge/Modality-Realtime_Audio-purple?style=for-the-badge&logo=audio&logoColor=white)](#)
[![OS](https://img.shields.io/badge/Platform-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)](#)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](./LICENSE)

---

Freya 3.0 is a local, real-time voice assistant that establishes a low-latency bi-directional audio stream with Google Gemini Live API. Running on your Windows desktop, Freya continuously feeds microphone input to the model and streams high-fidelity synthetic voice output back to your speakers, creating an interactive, hands-free conversational loop.

Armed with **15 custom local system tools**, a **dynamic self-updating memory system**, and a **Next.js web dashboard**, Freya remembers details about you, executes operating-system-level automation on command, and provides real-time visual feedback through a browser-based control interface.

---

## 🌟 Key Capabilities

*   🔊 **Zero-Latency Live Conversation**: Captures microphone audio at **16kHz (PCM, mono)** and plays speaker output at **24kHz** for natural, uninterrupted conversations.
*   🧠 **Self-Updating Synaptic Memory**: Auto-saves details about your preferences. On session shutdown, a secondary model (`gemini-2.5-flash-lite`) compiles the chat logs and appends new facts directly to Freya's memory bank (`memory/freya_memory.md`).
*   🖥️ **Web Dashboard (freya-ui)**: A Next.js 16 + React 19 + Tailwind CSS 4 browser interface providing real-time state visualization, live transcript streaming, tool call logs, memory editor, and model/voice configuration — all connected via WebSocket.
*   🛠️ **Deep OS & Web Integration**:
    *   **App Control**: Launch or shut down programs (e.g., Valorant, Photoshop, VS Code, Discord, Steam).
    *   **Developer Toolkit**: Run safe terminal commands, search official documentations (Python, React, Docker, etc.), and diagnose code tracebacks directly using StackOverflow integration.
    *   **Desktop Utilities**: Take screenshots, open file folders, set speak-back voice reminders, and retrieve current weather or news.

---

## 🛰️ Architecture Overview

Freya operates as a dual-process system: a **Python backend** (FastAPI + PyAudio + Gemini Live WebSocket) and a **Next.js frontend** connected over a local WebSocket bridge.

```
freyav3/
├── config/
│   ├── __init__.py             # Config loading helpers (API keys, model, voice, personality)
│   └── freya_config.json       # Device indices, app paths, model/voice settings
│
├── core/
│   ├── audio.py                # Low-latency Mic & Speaker streams (PyAudio)
│   ├── memory.py               # Context building & auto-updating memory engine
│   ├── model.py                # Gemini Live WebSocket event loop (FreyaModel)
│   └── tools.py                # Function calling dispatcher (15 system tools)
│
├── freya-ui/                   # Next.js 16 web dashboard
│   ├── app/
│   │   ├── components/
│   │   │   ├── ActivityIndicator.tsx   # Live status animation
│   │   │   ├── ArchivalPanel.tsx       # Transcript feed, memory view, tool log
│   │   │   └── SettingsModal.tsx       # Model/voice selector, memory editor
│   │   ├── hooks/
│   │   │   └── useFreyaSocket.ts       # WebSocket client hook (state, transcript, tools)
│   │   ├── globals.css                 # Tailwind CSS 4 theme
│   │   ├── layout.tsx                  # Root layout
│   │   └── page.tsx                    # Main dashboard page
│   └── package.json            # Next.js 16, React 19, Tailwind CSS 4
│
├── memory/
│   ├── freya_memory.example.md # Template memory configuration (tracked)
│   └── freya_memory.md         # Personal memory storage (git-ignored)
│
├── test_scripts/
│   ├── list_models.py          # Utility to list available Gemini model IDs
│   ├── test_devices.py         # Audio I/O validation tool
│   ├── test_interrupt.py       # Interrupt testing script
│   └── test_memory_api.py      # Memory engine validation script
│
├── .env                        # API Credentials (git-ignored)
├── main.py                     # CLI entrypoint (headless, terminal-only)
├── server.py                   # Web UI entrypoint (FastAPI + WebSocket server)
└── requirements.txt            # Python dependencies
```

> [!NOTE]
> For a detailed dive into the modular design, thread topologies, data pathways, and the dual-process architecture, see the [Architecture Documentation](./ARCHITECTURE.md).

---

## ⚡ Quick Start

### 1️⃣ Clone and Prepare Environment

Ensure you have **Python 3.10+**, **Node.js 18+**, and a working C/C++ compiler installed on your system (required to build `pyaudio` on Windows).

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
# Primary API Key for Gemini Live API
GEMINI_API_KEY=AIzaSyYourGeminiApiKeyHere

# Optional: Separate key for memory extraction (defaults to GEMINI_API_KEY)
GEMINI_MEMORY_API_KEY=AIzaSyYourSeparateApiKeyHere
```

> [!WARNING]
> Keep your API keys private. Never commit the `.env` file to public repositories.

### 3️⃣ Initialize Personal Memory

Freya uses a local Markdown file to build and recall facts about you. This file is excluded from version control (`.gitignore`) to keep your data private.

1. Locate the template file `memory/freya_memory.example.md`.
2. Copy the template to create your active memory file:
   ```bash
   copy memory\freya_memory.example.md memory\freya_memory.md
   ```
3. Open `memory/freya_memory.md` and modify the placeholders to match your name, location, preferred software tools, and settings.

### 🧠 How the Memory Engine Works
When you start a session, Freya parses `freya_memory.md` and injects its contents directly into the system personality prompt. During your conversation, a transcript collector logs the dialogue. Once you shut down the assistant, Freya automatically sends the session transcript to `gemini-2.5-flash-lite`, which filters out new facts, writes a short bullet-point summary of the session, and appends it to your `freya_memory.md` file.

---

## 🎛️ Configuration & Audio Routing

Configure the assistant behavior, device paths, and hardware bindings in `config/freya_config.json`:

```json
{
  "freya": {
    "name": "Freya",
    "personality": "You are Freya, a smart and friendly personal AI voice assistant built for Ihan..."
  },
  "active_provider": "gemini",
  "active_model": "gemini-3.1-flash-live-preview",
  "providers": {
    "gemini": {
      "models": [
        { "id": "gemini-3.1-flash-live-preview", "label": "Gemini 3.1 Flash Live Preview" },
        { "id": "gemini-2.5-flash-native-audio-preview-12-2025", "label": "Gemini 2.5 Flash Native Audio (fallback)" }
      ],
      "voices": ["Aoede", "Kore", "Zephyr"],
      "active_voice": "Zephyr"
    }
  },
  "audio": {
    "input_device_index": 0,
    "output_device_index": 3
  }
}
```

### 🎙️ Audio Hardware Calibration

To locate the correct index for your microphone and speaker devices, run:

```bash
python test_scripts/test_devices.py
```

This utility will list all index numbers corresponding to the active audio hardware connected to your machine. Bind these values inside `config/freya_config.json` under `"audio"`.

---

## 🚀 Execution

Freya supports two modes of operation:

### Mode 1: Web Dashboard (Recommended)

Launch the Python backend server and Next.js frontend together:

```bash
# Terminal 1 — Start the FastAPI backend (port 8000)
python server.py

# Terminal 2 — Start the Next.js dashboard (port 3000)
cd freya-ui
npm install   # first time only
npm run dev
```

Open `http://localhost:3000` in your browser. Use the dashboard to start/stop Freya, view live transcripts, monitor tool calls, edit memory, and switch models or voices on the fly.

### Mode 2: Headless CLI

For terminal-only operation without the web dashboard:

```bash
python main.py
```

Press `Ctrl + C` in the terminal to stop the assistant safely. This triggers the memory engine to persist session logs.

### Conversational Mechanics
*   Once launched, you will see `Freya is live! Start talking.`
*   Simply speak into your microphone. Freya will process your voice and speak back to you in real-time.
*   **Echo Protection**: The microphone input automatically mutes while the speaker is active, preventing feedback loops.
*   **Auto-Transcription**: Both your words and Freya's responses are transcribed in real-time using Gemini's built-in audio transcription.

---

## 🛠️ Diagnostics & Utilities

The project includes pre-configured utility scripts inside the `test_scripts/` directory:

*   **List Gemini Models**: Validate API keys and list available model versions.
    ```bash
    python test_scripts/list_models.py
    ```
*   **Verify Audio Channels**: Verify your hardware input devices are recording successfully.
    ```bash
    python test_scripts/test_devices.py
    ```
*   **Verify Memory API**: Test your API connection and ensure the fact-extraction loops execute smoothly.
    ```bash
    python test_scripts/test_memory_api.py
    ```

---

## 🪐 License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details.
