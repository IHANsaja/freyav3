import pyaudio

# These are the exact settings Gemini Live API expects
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000   # mic input → Gemini
RECEIVE_SAMPLE_RATE = 24000  # Gemini output → speaker

def list_audio_devices():
    """Structured device list for the frontend's mic-select dropdown: PyAudio
    lists every device once with both channel counts, split here into
    separate input/output lists (a device can appear in both)."""
    p = pyaudio.PyAudio()
    input_devices = []
    output_devices = []
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        entry = {"index": i, "name": info["name"]}
        if info["maxInputChannels"] > 0:
            input_devices.append(entry)
        if info["maxOutputChannels"] > 0:
            output_devices.append(dict(entry))
    p.terminate()
    return {"input": input_devices, "output": output_devices}


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
            # ~85 ms of PortAudio buffering so a busy event loop can't starve
            # the device between writes.
            frames_per_buffer=2048,
        )
        print("Speaker stream started.")

    # Chunks are written in slices so a stop can skip what's left. interrupt()
    # aborts the stream directly, so the slice size doesn't delay a stop; it
    # just has to be big enough that the gaps between writes (where this
    # thread needs the GIL back) never starve the device. 43 ms slices did,
    # and her voice stuttered.
    _SLICE = 12000  # bytes = 6000 samples, 250 ms at 24 kHz

    interrupted = False

    def write(self, data):
        for i in range(0, len(data), self._SLICE):
            if self.interrupted or not self.stream:
                return
            self.stream.write(data[i:i + self._SLICE])

    def interrupt(self):
        """Silence now: drop the rest of the current chunk and any audio
        already buffered in PortAudio."""
        self.interrupted = True
        try:
            if self.stream and self.stream.is_active():
                self.stream.abort_stream()
        except Exception:
            pass

    def stop(self):
        self.interrupted = True
        if self.stream:
            try:
                # abort, not stop: stop_stream() drains the buffer first, so
                # Freya kept talking after being stopped.
                if self.stream.is_active():
                    self.stream.abort_stream()
            except Exception:
                pass
            self.stream.close()
            self.stream = None
        self.p.terminate()
        print("Speaker stream stopped.")