import pyaudio
import json
import os

with open("config/freya_config.json", "r") as f:
    config = json.load(f)

output_idx = config["audio"]["output_device_index"]
print(f"Configured output device index: {output_idx}")

p = pyaudio.PyAudio()
try:
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=24000,
        output=True,
        output_device_index=output_idx,
    )
    print("✅ Speaker stream opened successfully!")
    stream.close()
except Exception as e:
    print(f"❌ Failed to open speaker stream: {e}")
finally:
    p.terminate()
