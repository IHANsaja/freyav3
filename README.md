# Freya 3.0

Freya 3.0 is a local, real-time voice assistant that streams microphone audio to Google Gemini Live (native audio output) and plays the returned audio through your speakers using PyAudio.

## What it does
- Captures microphone audio at **16kHz (PCM, mono)**.
- Connects to **Google Gemini Live** with **AUDIO** response modality.
- Streams the model’s realtime audio back to a speaker output stream at **24kHz**.

## Project structure
See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the high-level layout:
- `main.py` – app entry point
- `config/freya_config.json` – assistant config (model, voice, personality, device indices)
- `core/audio.py` – PyAudio microphone/speaker streaming utilities
- `core/model.py` – Gemini Live connection + realtime send/receive loop
- `list_models.py` – prints available Gemini model names
- `test_devices.py` – quick input-device validation

## Requirements
### Software
- Python 3.10+ (recommended)
- A working audio setup (microphone + output device)
- Google Gemini API access

### Dependencies
Install via:
```bash
pip install -r requirements.txt
```

`requirements.txt` includes:
- `google-genai`
- `python-dotenv`
- `pyaudio`
- `keyboard` (note: hotkey behavior is not implemented in the code shown here)

## Setup
### 1) Configure your API key
`main.py` loads the API key via `GEMINI_API_KEY` from your environment (`.env` is supported).

Create a `.env` file in the project root:
```env
GEMINI_API_KEY=your_real_key_here
```

> Do not commit your `.env` file.

### 2) Configure Freya
Edit `config/freya_config.json`:
- `active_model` – which Gemini live model to use
- `providers.gemini.active_voice` – the prebuilt voice name for Gemini speech
- `freya.personality` – the system instruction (tone + speaking style)
- `audio.input_device_index` / `audio.output_device_index` – PyAudio device indices
- `freya.hotkey` / `freya.input_mode` are present in config, but the current runtime flow shown in `main.py` does not implement hotkey/VAD logic; audio streaming starts immediately.

## Run
```bash
python main.py
```

Expected behavior:
- The app connects to the selected Gemini live model.
- “Freya is live! Start talking.” appears.
- Press `Ctrl+C` to stop.

## Audio device selection (important)
If you get errors, silence, or wrong-device audio, update device indices in `config/freya_config.json`.

### Find working input devices
Run:
```bash
python test_devices.py
```

It will print which input device indices can be opened and read successfully.

Then set:
- `config/freya_config.json -> audio.input_device_index`
- `config/freya_config.json -> audio.output_device_index`

## Useful scripts
### List available Gemini models
```bash
python list_models.py
```

### Test microphone/device I/O
```bash
python test_devices.py
```

## Troubleshooting
### “GEMINI_API_KEY not found in .env file!”
- Ensure your `.env` file exists in the repo root.
- Ensure it contains `GEMINI_API_KEY=...`.
- Ensure you are running commands from the project root.

### PyAudio device index issues
- Re-run `python test_devices.py`.
- Update `audio.input_device_index` / `audio.output_device_index` in `config/freya_config.json`.

### Connection / realtime streaming issues
- Verify the `active_model` value is correct for Gemini Live audio.
- Ensure your voice name exists in `providers.gemini.voices` and matches what Gemini expects.

## License
See [`LICENSE`](./LICENSE).

