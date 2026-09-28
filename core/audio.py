import pyaudio

# These are the exact settings Gemini Live API expects
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000   # mic input → Gemini
RECEIVE_SAMPLE_RATE = 24000  # Gemini output → speaker

# Windows' own routing entries. They are not devices, just "whatever the system
# default is", which the dropdown already offers as its own first option.
_PSEUDO_DEVICES = ("microsoft sound mapper", "primary sound capture driver", "primary sound driver")


def filter_devices(infos, host, default_in=None, default_out=None):
    """Mic and speaker choices for the settings dropdowns, from raw PyAudio
    device infos.

    PyAudio lists every physical device once per Windows host API (MME,
    DirectSound, WASAPI, WDM-KS), so two mics and three speakers came back as
    30-odd look-alike entries. Only PortAudio's default host API is kept: it is
    the one the default device belongs to, and (unlike WASAPI) it resamples to
    the 16/24 kHz mono the streams open with. MME cuts names at 31 characters,
    so each name is completed from the same device under another host API.
    Entries flagged `default` are the ones Windows currently uses.
    """
    def full_name(info, channels):
        name = info["name"].strip()
        longer = [o["name"].strip() for o in infos
                  if o[channels] > 0 and len(o["name"].strip()) > len(name)
                  and o["name"].strip().startswith(name)]
        return min(longer, key=len) if longer else name

    result = {"input": [], "output": []}
    for side, channels, default in (("input", "maxInputChannels", default_in),
                                    ("output", "maxOutputChannels", default_out)):
        seen = set()
        for info in infos:
            if info["hostApi"] != host or info[channels] <= 0:
                continue
            if info["name"].strip().lower().startswith(_PSEUDO_DEVICES):
                continue
            name = full_name(info, channels)
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            result[side].append({"index": info["index"], "name": name,
                                 "default": info["index"] == default})
    return result


def list_audio_devices():
    p = pyaudio.PyAudio()
    try:
        host = p.get_default_host_api_info()["index"]
        defaults = []
        for getter in (p.get_default_input_device_info, p.get_default_output_device_info):
            try:
                defaults.append(getter()["index"])
            except (IOError, OSError):  # no device of that kind at all
                defaults.append(None)
        infos = [p.get_device_info_by_index(i) for i in range(p.get_device_count())]
    finally:
        p.terminate()
    return filter_devices(infos, host, *defaults)


def resolve_device(index, side, name=None, quiet=False):
    """The device a stream should open, or None for the Windows default.

    Indexes are not stable: Windows reorders devices when one is plugged in or
    out, or when the default changes, so a bare index can quietly point at a
    different device. The saved name is matched first; a saved index is only
    trusted on its own for older configs that never stored a name. Anything no
    longer listed (including indexes of the now-hidden duplicates or the
    "Sound Mapper" entries) falls back to the system default.
    """
    if index is None and not name:
        return None
    try:
        listed = list_audio_devices()[side]
    except Exception:
        return index
    if name:
        for d in listed:
            if d["name"] == name:
                return d["index"]
    elif any(d["index"] == index for d in listed):
        return index
    if not quiet:
        print(f"  Saved {side} device {name or '#' + str(index)} is not available - using the system default.")
    return None


class MicStream:
    def __init__(self, device_index=None, device_name=None):
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.device_index = resolve_device(device_index, "input", device_name)

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
    def __init__(self, device_index=None, device_name=None):
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.device_index = resolve_device(device_index, "output", device_name)

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