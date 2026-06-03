import asyncio
from config import load_config, get_api_key, get_memory_api_key, get_active_model, get_active_voice, get_personality
from core.audio import MicStream, SpeakerStream
from core.model import FreyaModel
from core.memory import load_memory, build_system_prompt, update_memory, TranscriptCollector

config = load_config()
api_key = get_api_key()
model_id = get_active_model(config)
voice = get_active_voice(config)
base_personality = get_personality(config)

input_idx = config["audio"]["input_device_index"]
output_idx = config["audio"]["output_device_index"]

async def main():
    # ── Load memory and build full system prompt ──
    memory = load_memory()
    personality = build_system_prompt(base_personality, memory)
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
        transcript=transcript   # pass transcript collector in
    )

    try:
        await freya.run(mic, speaker)
    finally:
        mic.stop()
        speaker.stop()

        # ── Update memory after session ends ──
        memory_key = get_memory_api_key()
        await update_memory(memory_key, transcript.get(), memory)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Freya stopped manually.")