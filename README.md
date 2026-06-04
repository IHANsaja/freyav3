# 🌌 Freya v3.0

🚀 **The Cybernetic Voice Assistant**

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Gemini API](https://img.shields.io/badge/Google_Gemini-Live_API-orange?style=for-the-badge&logo=google-gemini&logoColor=white)](https://ai.google.dev/)
[![Modality](https://img.shields.io/badge/Modality-Realtime_Audio-purple?style=for-the-badge&logo=audio&logoColor=white)](#)
[![OS](https://img.shields.io/badge/Platform-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)](#)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](./LICENSE)

---

Freya 3.0 is a local, real-time voice assistant that establishes a low-latency bi-directional stream with Google Gemini Live API. Running directly on your Windows desktop, Freya continuously feeds microphone input to the model and streams high-fidelity synthetic voice output back to your speakers, creating an interactive, hands-free conversational loop.

Armed with **15 custom local system tools** and a **dynamic self-updating memory system**, Freya remembers details about you and executes operating-system-level automation on command.

---

## 🌟 Key Capabilities

*   🔊 **Zero-Latency Live Conversation**: Captures microphone audio at **16kHz (PCM, mono)** and plays speaker output at **24kHz** for natural, uninterrupted conversations.
*   🧠 **Self-Updating Synaptic Memory**: Auto-saves details about your preferences. On session shutdown, a secondary model (`gemini-2.5-flash-lite`) compiles the chat logs and appends new facts directly to Freya's memory bank (`memory/freya_memory.md`).
*   🛠️ **Deep OS & Web Integration**:
    *   **App Control**: Launch or shut down programs (e.g., Valorant, Photoshop, VS Code, Discord, Steam).
    *   **Developer Toolkit**: Run safe terminal commands, search official documentations (Python, React, Docker, etc.), and diagnose code tracebacks directly using StackOverflow integration.
    *   **Desktop Utilities**: Take screenshots, open file folders, set speak-back voice reminders, and retrieve current weather or news.

---

## 🛰️ Architecture Overview

Freya’s architecture decouples hardware audio streaming from the core WebSocket event loops.

```
freyav3/
├── config/
│   ├── __init__.py           # Config loading helpers
│   └── freya_config.json     # Device indices, app paths, voice models
│
├── core/
│   ├── audio.py              # Low-latency Mic & Speaker streams (PyAudio)
│   ├── memory.py             # Context building & auto-updating memory engine
│   ├── model.py              # Gemini Live WebSocket event loop handlers
│   └── tools.py              # Function calling dispatcher (15 system tools)
│
├── memory/
│   ├── freya_memory.example.md # Template memory configuration (tracked)
│   └── freya_memory.md       # Personal memory storage (git-ignored)
│
├── test_scripts/
│   ├── list_models.py        # Utility to list available Gemini model IDs
│   ├── test_devices.py       # Audio I/O validation tool
│   ├── test_interrupt.py     # Interrupt testing script
│   └── test_memory_api.py    # Memory engine validation script
│
├── .env                      # API Credentials (ignored by git)
├── main.py                   # System entrypoint
└── requirements.txt          # Python dependencies
```

> [!NOTE]
> For a detailed dive into the modular design, thread topologies, and data pathways, see the [Architecture Documentation](./ARCHITECTURE.md).

---

## ⚡ Quick Start

### 1️⃣ Clone and Prepare Environment

Ensure you have **Python 3.10+** and a working C/C++ compiler installed on your system (required to build `pyaudio` on Windows).

```bash
# Clone the repository
git clone https://github.com/your-username/freyav3.git
cd freyav3

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate

# Install required dependencies
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

1. Locate the template file [memory/freya_memory.example.md](file:///f:/Projects/Freya/freyav3/memory/freya_memory.example.md).
2. Copy the template to create your active memory file:
   ```bash
   cp memory/freya_memory.example.md memory/freya_memory.md
   ```
3. Open `memory/freya_memory.md` and modify the placeholders to match your name, location, preferred software tools, and settings.

### 🧠 How the Memory Engine Works
When you start a session, Freya parses `freya_memory.md` and injects its contents directly into the system personality prompt. During your conversation, a thread collector logs the dialogue. Once you shut down the assistant using `Ctrl + C`, Freya automatically sends the session transcript to `gemini-2.5-flash-lite`, which filters out new facts, writes a short bullet-point summary of the session, and appends it to your `freya_memory.md` file.

---

## 🎛️ Configuration & Audio Routing

Configure the assistant behavior, device paths, and hardware bindings in [config/freya_config.json](file:///f:/Projects/Freya/freyav3/config/freya_config.json):

```json
{
  "freya": {
    "name": "Freya",
    "personality": "You are Freya, a smart and friendly personal AI voice assistant built for Ihan..."
  },
  "active_provider": "gemini",
  "active_model": "gemini-3.1-flash-live-preview",
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

Launch Freya with the active python runtime:

```bash
python main.py
```

### Conversational Mechanics
*   Once launched, you will see `Freya is live! Start talking.`
*   Simply speak into your microphone. Freya will process your voice and speak back to you in real-time.
*   **Echo Protection**: The microphone input automatically ignores audio captured while the speaker is active, preventing feedback loops.
*   Press `Ctrl + C` in the terminal to stop the assistant safely. This triggers the memory engine to persist session logs.

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
