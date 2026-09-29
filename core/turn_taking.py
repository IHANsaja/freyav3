"""Turn-taking: letting the user cut in while Freya talks, and telling her so.

Two problems, solved separately:

1. Hearing the user over her own voice. With speakers (no headphones) the mic
   picks up everything she says, so EchoGate mutes the mic while she talks and
   she could not be interrupted at all. DoubleTalkDetector is a classic
   double-talk check: it learns how loud her own voice comes back through the
   mic (the echo "coupling") relative to what is being played, and only calls
   it the user when the mic is clearly louder than that echo for a sustained
   stretch. It is a loudness model, not echo cancellation, so it errs toward
   caution: a false alarm only pauses her briefly (see TurnTaker), it never
   drops her reply.

2. Knowing it was an interruption. Gemini streams audio faster than it plays,
   so the server believes she said a whole paragraph when the user heard one
   sentence. heard_fraction()/trim_to_fraction() estimate what was actually
   played, and interruption_note() tells her exactly where she was cut off.

Everything here is pure (no audio devices, no network) so it can be tested.
"""
import time
from collections import deque

# Spoken guidance added to the system instruction.
TURN_TAKING = (
    "TURN-TAKING: The user can cut in while you are speaking; your audio stops the moment they do. "
    "When a note says you were interrupted, they heard you only up to the quoted point and nothing after it. "
    "Their interruption takes priority: answer their question or follow their correction or new direction "
    "right away, without repeating what they already heard. If they only made a brief acknowledgement "
    "(yeah, mm-hmm, right, okay, go on), carry on from where you were cut off in a few words, without "
    "starting over. If they told you to stop, wait or be quiet, stop and acknowledge in a couple of words. "
    "Never scold them for interrupting and never apologise at length."
)


def trim_to_fraction(text: str, fraction: float) -> str:
    """The first `fraction` of `text`, cut back to a whole word."""
    text = (text or "").strip()
    if fraction >= 0.999 or not text:
        return text
    if fraction <= 0:
        return ""
    cut = int(len(text) * fraction)
    if cut >= len(text):
        return text
    space = text.rfind(" ", 0, cut + 1)
    return text[:space].rstrip(" ,;:-") if space > 0 else ""


def interruption_note(heard: str, cut_short: bool) -> str:
    """The [SYSTEM NOTE] telling her she was interrupted and what was heard."""
    tail = " ".join(heard.split()[-30:])
    if tail and cut_short:
        where = f'They heard you only up to: "…{tail}" and nothing after that.'
    elif tail:
        where = f'You had just finished saying: "…{tail}".'
    else:
        where = "They cut in before hearing anything of your reply."
    return ("[SYSTEM NOTE: the user just interrupted you while you were speaking. " + where +
            " What they say now is an interruption: respond to it directly. If it is only a brief "
            "acknowledgement, pick up where you were cut off without starting over. "
            "Do not mention this note.]")


class DoubleTalkDetector:
    """Is the mic hearing the user, or just Freya's voice coming back?

    Feed every mic frame with `frame(mic_rms, now)` and every chunk handed to
    the speaker with `playback(level, seconds, now)`. `frame` returns True on
    the frame that confirms the user is talking over her.
    """

    def __init__(self, min_rms=500, margin=2.5, min_ms=200, frame_ms=64,
                 lookback_s=0.35, warmup_frames=30, history=400):
        self.min_rms = min_rms
        self.margin = margin
        self.frames_needed = max(1, round(min_ms / frame_ms))
        self.lookback_s = lookback_s
        self.warmup_frames = warmup_frames
        self.noise = 150.0                 # mic level with nobody talking
        self.ratios = deque(maxlen=history)  # echo level / playback level, learned
        self.segments = deque(maxlen=256)  # (start, end, level) of played audio
        self.run = []                      # ratios of the current loud stretch
        self._coupling = None

    # ── inputs ──
    def playback(self, level: float, seconds: float, now: float):
        # Audio plays ~0.1 s after it is handed over (PortAudio buffering).
        self.segments.append((now, now + seconds + 0.1, float(level)))

    def reference(self, now: float) -> float:
        """Loudest thing she played in the recent past (echo arrives late)."""
        since = now - self.lookback_s
        return max((lvl for s, e, lvl in self.segments if e >= since and s <= now), default=0.0)

    @property
    def ready(self) -> bool:
        return len(self.ratios) >= self.warmup_frames

    def coupling(self) -> float:
        if self._coupling is None:
            ordered = sorted(self.ratios)
            self._coupling = ordered[int(0.9 * (len(ordered) - 1))] if ordered else 1.0
        return self._coupling

    def learn(self, ratios):
        """These frames were only her echo (e.g. a false alarm): remember them."""
        for r in ratios:
            self.ratios.append(r)
        self._coupling = None

    def reset_run(self):
        self.run = []

    def frame(self, mic_rms: float, now: float) -> bool:
        ref = self.reference(now)
        if ref < 1:
            # Nothing playing: this is the room. Track its floor (fast down, slow up).
            self.noise = min(mic_rms, self.noise * 1.02 + 1) if mic_rms < self.noise * 4 else self.noise
            self.run = []
            return False
        ratio = max(0.0, mic_rms - self.noise) / ref
        if not self.ready:
            self.learn([ratio])            # still learning what her echo sounds like
            return False
        echo = self.coupling() * ref + self.noise
        if mic_rms > max(self.min_rms, self.noise * 3, echo * self.margin):
            self.run.append(ratio)
            return len(self.run) >= self.frames_needed
        if self.run:
            self.learn(self.run)           # a short blip was echo after all
            self.run = []
        self.learn([ratio])
        return False


class TurnTaker:
    """Who has the floor, and what to do when the user takes it.

    NORMAL   - usual flow.
    HOLD     - the detector heard the user over her: playback is paused and the
               mic is open, waiting for Gemini to confirm (an `interrupted`
               frame, or words in the input transcription). If nothing confirms
               within `confirm_s` it was a false alarm and she carries on.
    CONFIRMED- the user has the floor: her unplayed audio is dropped and the mic
               stays open (no echo-tail muting) until her next reply starts.
    """
    NORMAL, HOLD, CONFIRMED = "normal", "hold", "confirmed"

    def __init__(self, detector=None, confirm_s=1.5, clock=time.monotonic):
        self.detector = detector
        self.confirm_s = confirm_s
        self.clock = clock
        self.state = self.NORMAL
        self.epoch = 0              # bumps when queued audio becomes stale
        self.stale = False          # interrupted generation may still be streaming
        self.hold_since = 0.0
        self.hold_ratios = []
        # Bytes of her audio received / actually played, and where the text now
        # in the transcript buffer started, for estimating what was heard.
        self.received = 0
        self.played = 0
        self.segment_start = 0
        self.inflight = None        # (bytes, started) of the chunk being played now

    @property
    def user_has_floor(self) -> bool:
        return self.state != self.NORMAL

    def hold(self):
        self.state = self.HOLD
        self.hold_since = self.clock()
        if self.detector is not None:
            self.hold_ratios = list(self.detector.run)
            self.detector.reset_run()

    def hold_expired(self) -> bool:
        return self.state == self.HOLD and self.clock() - self.hold_since >= self.confirm_s

    def release(self):
        """False alarm: that was her echo, not the user. Resume playback."""
        if self.detector is not None and self.hold_ratios:
            self.detector.learn(self.hold_ratios)
        self.hold_ratios = []
        self.state = self.NORMAL

    def confirm(self, generation_running: bool):
        """The user really did cut in. Returns False if already confirmed."""
        if self.state == self.CONFIRMED:
            return False
        self.state = self.CONFIRMED
        self.stale = generation_running
        self.epoch += 1
        self.hold_ratios = []
        return True

    def reply_started(self):
        self.state = self.NORMAL
        self.stale = False

    BYTES_PER_S = 48000             # 24 kHz, 16-bit mono

    def chunk_started(self, size: int):
        self.inflight = (size, self.clock())

    def chunk_finished(self, played: int, current: bool):
        self.inflight = None
        if current:
            self.played += played

    def heard_fraction(self) -> float:
        span = self.received - self.segment_start
        if span <= 0:
            return 1.0
        played = self.played
        if self.inflight:
            # The chunk on the speaker right now counts for as long as it has played.
            size, started = self.inflight
            played += min(size, int((self.clock() - started) * self.BYTES_PER_S))
        return min(1.0, max(0.0, (played - self.segment_start) / span))
