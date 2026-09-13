"""Half-duplex speaker protection; a loudness threshold is not echo cancellation."""
import time


class EchoGate:
    def __init__(self, enabled=True, tail_seconds=0.45, clock=time.monotonic):
        self.enabled = enabled
        self.tail_seconds = tail_seconds
        self.clock = clock
        self.playing = False
        self.block_until = 0.0

    def begin_playback(self):
        self.playing = True

    def end_playback(self):
        self.playing = False
        self.block_until = self.clock() + self.tail_seconds

    def blocks(self, model_speaking=False):
        return self.enabled and (model_speaking or self.playing or self.clock() < self.block_until)
