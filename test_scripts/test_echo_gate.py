import unittest
from core.echo_gate import EchoGate


class EchoGateTests(unittest.TestCase):
    def test_playback_and_echo_tail_block_microphone(self):
        now = [10.0]
        gate = EchoGate(clock=lambda: now[0])
        self.assertFalse(gate.blocks())
        self.assertTrue(gate.blocks(model_speaking=True))
        gate.begin_playback()
        self.assertTrue(gate.blocks())
        gate.end_playback()
        now[0] += .3
        self.assertTrue(gate.blocks())
        now[0] += .2
        self.assertFalse(gate.blocks())

    def test_each_chunk_extends_echo_tail(self):
        now = [10.0]
        gate = EchoGate(clock=lambda: now[0])
        gate.begin_playback(); gate.end_playback()
        now[0] += .4
        gate.begin_playback(); gate.end_playback()
        now[0] += .1
        self.assertTrue(gate.blocks())

    def test_headphone_opt_out_allows_barge_in(self):
        gate = EchoGate(enabled=False)
        gate.begin_playback()
        self.assertFalse(gate.blocks(model_speaking=True))
