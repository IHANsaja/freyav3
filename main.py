import asyncio
from config import load_config, get_api_key, get_memory_api_key, get_active_voice, get_personality
from config import get_mode_personality, get_mode_model  # ← add these
from core.audio import MicStream, SpeakerStream
from core.model import FreyaModel
from core.memory import load_memory, build_system_prompt, update_memory, TranscriptCollector

config = load_config()
api_key = get_api_key()
model_id = get_mode_model(config)          # ← was get_active_model(config)
voice = get_active_voice(config)
base_personality = get_personality(config)

input_idx = config["audio"]["input_device_index"]
output_idx = config["audio"]["output_device_index"]

async def main():
    memory = load_memory()
    personality = build_system_prompt(get_mode_personality(config, base_personality), memory)  # ← was just base_personality
    transcript = TranscriptCollector()

    mic = MicStream(device_index=input_idx)
    speaker = SpeakerStream(device_index=output_idx)

    mic.start()
    speaker.start()

    freya = FreyaModel(
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
        mic.stop()
        speaker.stop()
        memory_key = get_memory_api_key()
        await update_memory(memory_key, transcript.get(), memory)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Freya stopped manually.")