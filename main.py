import asyncio
from config import load_config, get_api_key, get_active_model, get_active_voice, get_personality
from core.audio import MicStream, SpeakerStream
from core.model import FreyaModel

config = load_config()
api_key = get_api_key()
model_id = get_active_model(config)
voice = get_active_voice(config)
personality = get_personality(config)

input_idx = config["audio"]["input_device_index"]
output_idx = config["audio"]["output_device_index"]

async def main():
    mic = MicStream(device_index=input_idx)
    speaker = SpeakerStream(device_index=output_idx)

    mic.start()
    speaker.start()

    freya = FreyaModel(
        api_key=api_key,
        model_id=model_id,
        voice=voice,
        personality=personality,
        config=config
    )

    try:
        await freya.run(mic, speaker)
    finally:
        mic.stop()
        speaker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Freya stopped manually.")