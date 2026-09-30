"""The user's real microphone, mirrored into the virtual cable.

When WhatsApp or Phone Link take their mic from the cable, the user's own voice
would no longer reach his calls. This copies the real mic into the cable, and
goes silent while a cloned line plays (muted), while a call is being handled for
him (muted until "put me through"), and while Freya's own voice plays on the
speakers (ducked) so the room's sound doesn't leak into the call.

It opens its own streams rather than sharing MicStream, which runs at 16 kHz
for Gemini and belongs to the live session. MME allows both at once.
"""
import threading

_RATE = 48000
_BLOCK = 960            # 20 ms
_SILENCE = b"\x00\x00" * _BLOCK

_lock = threading.Lock()
_instance = None


class MicPassthrough:
    def __init__(self, input_index, output_index):
        self.input_index = input_index
        self.output_index = output_index
        self.muted = False
        self.ducked = False
        self._stop = threading.Event()
        self._thread = None
        self.error = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="voice-passthrough")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self):
        import pyaudio
        from core.voice_clone.wavplay import cable_lock
        p = pyaudio.PyAudio()
        mic = out = None
        try:
            mic = p.open(format=pyaudio.paInt16, channels=1, rate=_RATE, input=True,
                         input_device_index=self.input_index, frames_per_buffer=_BLOCK)
            out = p.open(format=pyaudio.paInt16, channels=1, rate=_RATE, output=True,
                         output_device_index=self.output_index, frames_per_buffer=_BLOCK)
            while not self._stop.is_set():
                data = mic.read(_BLOCK, exception_on_overflow=False)
                if self.muted or self.ducked:
                    data = _SILENCE          # silence, not a stop: no clicks on the cable
                # A cloned line holds the lock while it plays; skip rather than wait.
                if cable_lock.acquire(blocking=False):
                    try:
                        out.write(data)
                    finally:
                        cable_lock.release()
        except Exception as e:     # device gone, in use, etc.
            self.error = str(e)
        finally:
            for stream in (mic, out):
                if stream is not None:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
            p.terminate()


def get():
    return _instance


def start(config: dict) -> str:
    """Start mirroring the mic into the cable. Returns a status sentence."""
    global _instance
    from core import audio
    from core.voice_clone.wavplay import cable_device
    cable = cable_device(config)
    mic = audio.resolve_device((config.get("audio") or {}).get("input_device_index"), "input",
                               (config.get("audio") or {}).get("input_device_name"), quiet=True)
    with _lock:
        if _instance is not None and _instance.running:
            return "Your mic is already going into calls."
        _instance = MicPassthrough(mic, cable)
        _instance.start()
    return "Your mic now goes into calls through the cable."


def stop() -> None:
    global _instance
    with _lock:
        if _instance is not None:
            _instance.stop()
        _instance = None


def set_muted(on: bool) -> None:
    if _instance is not None:
        _instance.muted = bool(on)


def duck(on: bool) -> None:
    """Called around Freya's own speech (core/model.py); a no-op when off."""
    if _instance is not None:
        _instance.ducked = bool(on)


def state() -> dict:
    inst = _instance
    if inst is None:
        return {"running": False, "muted": False, "ducked": False, "error": None}
    return {"running": inst.running, "muted": inst.muted, "ducked": inst.ducked, "error": inst.error}
