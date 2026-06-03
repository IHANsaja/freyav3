# Save this as test_devices.py in your freyav3 folder
import pyaudio

p = pyaudio.PyAudio()
CHUNK = 1024

input_devices = [i for i in range(p.get_device_count()) 
                 if p.get_device_info_by_index(i)['maxInputChannels'] > 0]

print("Testing input devices...\n")
for idx in input_devices:
    name = p.get_device_info_by_index(idx)['name']
    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            input_device_index=idx,
            frames_per_buffer=CHUNK
        )
        stream.read(CHUNK, exception_on_overflow=False)
        stream.stop_stream()
        stream.close()
        print(f"  ✅ [{idx}] {name} — WORKS")
    except Exception as e:
        print(f"  ❌ [{idx}] {name} — FAILED: {e}")

p.terminate()