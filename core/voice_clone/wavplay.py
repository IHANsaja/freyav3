"""WAV decoding and playback on a chosen output device (the virtual cable).

A small RIFF reader instead of the stdlib `wave` module, which rejects float
WAV files (format 3) that some TTS engines write. numpy does the conversion;
`audioop` is avoided because Python 3.13 removed it.
"""
import struct
import threading

import numpy as np

from core.voice_clone import VoiceError

# One writer to the cable at a time: a generated line and the mic passthrough
# must never talk over each other.
cable_lock = threading.Lock()
_SLICE_S = 0.25


def read_wav(data: bytes) -> tuple[bytes, int]:
    """(mono 16-bit PCM bytes, sample rate) from WAV file bytes."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise VoiceError("The generated audio is not a WAV file.")
    pos, fmt, pcm = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:          # WAVE_FORMAT_EXTENSIBLE
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, channels, rate, bits)
        elif cid == b"data":
            pcm = body
        pos += 8 + size + (size & 1)
    if fmt is None or pcm is None:
        raise VoiceError("The generated WAV has no audio data.")
    tag, channels, rate, bits = fmt
    if tag == 3 and bits == 32:
        samples = np.frombuffer(pcm[:len(pcm) // 4 * 4], dtype="<f4")
    elif tag == 1 and bits == 16:
        samples = np.frombuffer(pcm[:len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768
    elif tag == 1 and bits == 24:
        raw = np.frombuffer(pcm[:len(pcm) // 3 * 3], dtype=np.uint8).reshape(-1, 3)
        ints = (raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8)
                | (raw[:, 2].astype(np.int32) << 16))
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        samples = ints.astype(np.float32) / 8388608
    elif tag == 1 and bits == 32:
        samples = np.frombuffer(pcm[:len(pcm) // 4 * 4], dtype="<i4").astype(np.float32) / 2147483648
    else:
        raise VoiceError(f"Unsupported WAV format (format {tag}, {bits}-bit).")
    if channels > 1:
        samples = samples[:len(samples) // channels * channels].reshape(-1, channels).mean(axis=1)
    mono = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    return mono.tobytes(), int(rate)


def make_wav(pcm: bytes, rate: int) -> bytes:
    """A 16-bit mono WAV around raw PCM."""
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16,
                         1, 1, rate, rate * 2, 2, 16, b"data", len(pcm))
    return header + pcm


def duration_s(pcm: bytes, rate: int) -> float:
    return len(pcm) / 2 / rate if rate else 0.0


def rms(pcm: bytes) -> float:
    samples = np.frombuffer(pcm[:len(pcm) // 2 * 2], dtype="<i2").astype(np.float32)
    return float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0


def cable_device(config: dict) -> int:
    """PyAudio index of the virtual cable's playback side ("CABLE Input").

    Never Freya's own speaker: her Gemini voice plays there, and a clone line
    must not go out to the room - nor her voice into the call."""
    from core import audio
    from core.voice_clone import settings
    vc = settings(config)
    outputs = audio.list_audio_devices()["output"]
    index = audio.resolve_device(vc.get("cable_output_index"), "output",
                                 vc.get("cable_output_name") if vc.get("cable_output_index") is not None else None,
                                 quiet=True)
    if index is None:
        wanted = (vc.get("cable_output_name") or "CABLE Input").lower()
        index = next((d["index"] for d in outputs if d["name"].lower().startswith(wanted)), None)
    if index is None:
        raise VoiceError("I can't find the virtual audio cable (\"CABLE Input\"). Install VB-Audio "
                         "Virtual Cable and pick it under My Voice in settings.")
    freya = audio.resolve_device((config.get("audio") or {}).get("output_device_index"), "output",
                                 (config.get("audio") or {}).get("output_device_name"), quiet=True)
    default = next((d["index"] for d in outputs if d.get("default")), None)
    if index == (freya if freya is not None else default):
        raise VoiceError("The call device is the same as my speaker. Choose \"CABLE Input\" for calls, "
                         "so my own voice never goes into the call.")
    return index


class WavPlayer:
    """Plays mono 16-bit PCM on one output device, stoppable between slices."""

    def __init__(self, device_index: int | None):
        self.device_index = device_index
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def play(self, pcm: bytes, rate: int) -> float:
        """Blocking. Returns seconds played. The MME host API resamples to the
        device, so the stream opens at the audio's own rate."""
        import pyaudio
        self._stop.clear()
        p = pyaudio.PyAudio()
        stream = None
        played = 0
        try:
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=int(rate), output=True,
                            output_device_index=self.device_index,
                            frames_per_buffer=max(256, int(rate * 0.05)))
            step = int(rate * _SLICE_S) * 2
            for i in range(0, len(pcm), step):
                if self._stop.is_set():
                    break
                chunk = pcm[i:i + step]
                stream.write(chunk)
                played += len(chunk)
        except OSError as e:
            raise VoiceError(f"Couldn't play on that audio device: {e}") from e
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            p.terminate()
        return played / 2 / rate
