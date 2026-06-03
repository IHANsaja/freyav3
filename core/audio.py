import pyaudio

# These are the exact settings Gemini Live API expects
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000   # mic input → Gemini
RECEIVE_SAMPLE_RATE = 24000  # Gemini output → speaker

def get_audio_devices():
    p = pyaudio.PyAudio()
    print("\nAvailable audio devices:")
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        print(f"  [{i}] {info['name']} - inputs: {info['maxInputChannels']} outputs: {info['maxOutputChannels']}")
    p.terminate()

class MicStream:
    def __init__(self, device_index=None):
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.device_index = device_index

    def start(self):
        self.stream = self.p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SEND_SAMPLE_RATE,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=CHUNK
        )
        print("Mic stream started.")

    def read(self):
        return self.stream.read(CHUNK, exception_on_overflow=False)

    def stop(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.p.terminate()
        print("Mic stream stopped.")

class SpeakerStream:
    def __init__(self, device_index=None):
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.device_index = device_index

    def start(self):
        self.stream = self.p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
            output_device_index=self.device_index,
        )
        print("Speaker stream started.")

    def write(self, data):
        self.stream.write(data)

    def stop(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.p.terminate()
        print("Speaker stream stopped.")