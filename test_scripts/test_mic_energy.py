import pyaudio
import json
import audioop

with open("config/freya_config.json", "r") as f:
    config = json.load(f)

input_idx = config["audio"]["input_device_index"]
print(f"Configured input device index: {input_idx}")

p = pyaudio.PyAudio()
try:
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        input_device_index=input_idx,
        frames_per_buffer=1024
    )
    print("Mic stream opened. Recording for 3 seconds...")
    
    # Read chunks for 3 seconds (about 46 chunks)
    for i in range(46):
        data = stream.read(1024, exception_on_overflow=False)
        rms = audioop.rms(data, 2)
        print(f"Chunk {i}: RMS = {rms}")
        
    stream.stop_stream()
    stream.close()
except Exception as e:
    print(f"Error: {e}")
finally:
    p.terminate()
