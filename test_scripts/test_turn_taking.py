import unittest

from core.audio import SpeakerStream
from core.turn_taking import (DoubleTalkDetector, TurnTaker, interruption_note,
                              trim_to_fraction)


def warmed(echo=0.2, **kw):
    """A detector that has heard her voice come back at `echo` x playback."""
    d = DoubleTalkDetector(**kw)
    t = 0.0
    for _ in range(40):
        d.playback(4000, 0.064, t)
        d.frame(150 + 4000 * echo, t + 0.05)
        t += 0.064
    return d, t


class DoubleTalkDetectorTests(unittest.TestCase):
    def test_learns_echo_and_ignores_it(self):
        d, t = warmed()
        self.assertTrue(d.ready)
        for _ in range(20):
            d.playback(4000, 0.064, t)
            self.assertFalse(d.frame(150 + 4000 * 0.22, t + 0.05))
            t += 0.064

    def test_user_over_her_voice_fires_after_sustained_speech(self):
        d, t = warmed()
        results = []
        for _ in range(4):
            d.playback(4000, 0.064, t)
            results.append(d.frame(6000, t + 0.05))
            t += 0.064
        self.assertEqual(results[:2], [False, False])
        self.assertTrue(any(results))

    def test_short_blip_does_not_fire(self):
        d, t = warmed()
        d.playback(4000, 0.064, t)
        self.assertFalse(d.frame(6000, t + 0.05))
        t += 0.064
        d.playback(4000, 0.064, t)
        self.assertFalse(d.frame(900, t + 0.05))

    def test_never_fires_before_warmup(self):
        d = DoubleTalkDetector()
        for i in range(10):
            d.playback(4000, 0.064, i * 0.064)
            self.assertFalse(d.frame(9000, i * 0.064 + 0.05))

    def test_silence_between_turns_is_room_noise(self):
        d, t = warmed()
        self.assertFalse(d.frame(3000, t + 5))   # nothing playing: not a barge-in
        self.assertEqual(d.run, [])


class TurnTakerTests(unittest.TestCase):
    def test_false_alarm_releases_and_learns(self):
        now = [0.0]
        d, _ = warmed()
        tt = TurnTaker(d, confirm_s=1.5, clock=lambda: now[0])
        d.run = [9.0, 9.0, 9.0]
        tt.hold()
        self.assertTrue(tt.user_has_floor)
        now[0] = 1.0
        self.assertFalse(tt.hold_expired())
        now[0] = 1.6
        self.assertTrue(tt.hold_expired())
        before = len(d.ratios)
        tt.release()
        self.assertEqual(tt.state, TurnTaker.NORMAL)
        self.assertGreater(len(d.ratios), before - 1)
        self.assertIn(9.0, d.ratios)

    def test_confirm_makes_queued_audio_stale_once(self):
        tt = TurnTaker()
        tt.hold()
        self.assertTrue(tt.confirm(generation_running=True))
        self.assertEqual(tt.epoch, 1)
        self.assertTrue(tt.stale)
        self.assertFalse(tt.confirm(generation_running=False))
        self.assertEqual(tt.epoch, 1)
        tt.reply_started()
        self.assertEqual(tt.state, TurnTaker.NORMAL)
        self.assertFalse(tt.stale)

    def test_heard_fraction(self):
        tt = TurnTaker()
        tt.segment_start, tt.received, tt.played = 1000, 5000, 2000
        self.assertAlmostEqual(tt.heard_fraction(), 0.25)
        tt.played = 9000
        self.assertEqual(tt.heard_fraction(), 1.0)
        tt.received = tt.segment_start
        self.assertEqual(tt.heard_fraction(), 1.0)

    def test_chunk_on_the_speaker_counts_for_the_time_it_played(self):
        now = [0.0]
        tt = TurnTaker(clock=lambda: now[0])
        tt.received = 48000 * 2            # two seconds of her audio
        tt.chunk_started(48000)
        now[0] = 0.5                       # half a second into the first one
        self.assertAlmostEqual(tt.heard_fraction(), 0.25, places=2)
        tt.chunk_finished(48000, current=True)
        self.assertAlmostEqual(tt.heard_fraction(), 0.5)
        tt.chunk_finished(48000, current=False)   # stale chunk: not counted
        self.assertAlmostEqual(tt.heard_fraction(), 0.5)


class TextTests(unittest.TestCase):
    def test_trim_to_whole_words(self):
        text = "The market opened higher today, and then it fell sharply."
        self.assertEqual(trim_to_fraction(text, 1.0), text)
        self.assertEqual(trim_to_fraction(text, 0.0), "")
        self.assertEqual(trim_to_fraction(text, 0.5), "The market opened higher")

    def test_note_says_where_she_was_cut(self):
        note = interruption_note("so the first thing to know", cut_short=True)
        self.assertIn("interrupted", note)
        self.assertIn("first thing to know", note)
        self.assertIn("nothing after that", note)
        self.assertIn("before hearing anything", interruption_note("", True))


class FakeStream:
    def __init__(self):
        self.written, self.active = [], True

    def write(self, chunk):
        self.written.append(chunk)

    def is_active(self):
        return self.active

    def abort_stream(self):
        self.active = False

    def start_stream(self):
        self.active = True

    def close(self):
        pass


class SpeakerCutTests(unittest.TestCase):
    def make(self):
        s = SpeakerStream.__new__(SpeakerStream)
        s.stream = FakeStream()
        return s

    def test_cut_returns_unplayed_and_resume_restarts(self):
        s = self.make()
        data = bytes(SpeakerStream._SLICE * 3)
        s.cut()
        self.assertEqual(s.write(data), data)
        self.assertFalse(s.stream.active)
        s.resume()
        self.assertTrue(s.stream.active)
        self.assertEqual(s.write(data), b"")
        self.assertEqual(len(s.stream.written), 3)

    def test_shutdown_interrupt_is_not_undone_by_resume(self):
        s = self.make()
        s.interrupt()
        s.cut()
        s.resume()
        self.assertFalse(s.stream.active)
        self.assertEqual(s.write(b"abc"), b"abc")


if __name__ == "__main__":
    unittest.main()
