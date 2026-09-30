"""Speaking in the user's cloned voice: engines, playback, calls and safeguards."""

import asyncio
import json
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from core.voice_clone import VoiceError, calls, engine, passthrough, policy, settings, setup, tools, wavplay
from core.voice_clone.voicebox import VoiceboxClient


def wav16(seconds=0.5, rate=24000, amp=8000, channels=1):
    n = int(seconds * rate)
    tone = (np.sin(np.linspace(0, 440 * 2 * np.pi * seconds, n)) * amp).astype("<i2")
    if channels == 2:
        tone = np.repeat(tone, 2)
    return wavplay.make_wav(tone.tobytes(), rate) if channels == 1 else _wav(tone.tobytes(), rate, 1, 16, 2)


def _wav(data, rate, tag, bits, channels):
    block = channels * bits // 8
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE", b"fmt ", 16, tag,
                       channels, rate, rate * block, block, bits, b"data", len(data)) + data


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "_LOG_PATH", str(tmp_path / "voice_log.jsonl"))
    policy._recent.clear()
    calls.state.end()
    yield
    calls.state.end()


# -- engine ------------------------------------------------------------------

def test_language_by_script_and_hint():
    assert engine.detect_lang("I'll call you back") == "en"
    assert engine.detect_lang("මම පස්සේ කතා කරන්නම්") == "si"
    assert engine.detect_lang("நான் பிறகு அழைக்கிறேன்") == "ta"
    assert engine.detect_lang("hello", "Tamil") == "ta"


def test_sentences_split_and_long_ones_cut():
    assert engine.split_sentences("Hi there. I'm busy! Call later?") == ["Hi there.", "I'm busy!", "Call later?"]
    parts = engine.split_sentences("word " * 100, max_chars=60)
    assert all(len(p) <= 61 for p in parts) and " ".join(parts).split() == ["word"] * 100


def test_english_goes_to_voicebox_and_others_are_marked_stand_in(monkeypatch):
    monkeypatch.setattr(VoiceboxClient, "generate", lambda self, *a, **k: wav16())
    stand_in = AsyncMock(return_value=wav16())
    monkeypatch.setattr("core.voice_clone.gemini_tts.synthesize", stand_in)
    cfg = {"voice_clone": {"voicebox_profile_id": "p1"}}
    chunks = asyncio.run(engine.prepare("I'm busy. මම කාර්යබහුලයි.", cfg))
    assert [(c.engine, c.cloned, c.lang) for c in chunks] == [("voicebox", True, "en"), ("gemini", False, "si")]


def test_voicebox_down_falls_back_only_when_allowed(monkeypatch):
    def down(self, *a, **k):
        raise VoiceError("Voicebox isn't running.")
    monkeypatch.setattr(VoiceboxClient, "generate", down)
    monkeypatch.setattr("core.voice_clone.gemini_tts.synthesize", AsyncMock(return_value=wav16()))
    ok = asyncio.run(engine.prepare("Hello.", {"voice_clone": {"voicebox_profile_id": "p1"}}))
    assert ok[0].cloned is False
    with pytest.raises(VoiceError, match="running"):
        asyncio.run(engine.prepare("Hello.", {"voice_clone": {"voicebox_profile_id": "p1",
                                                               "allow_fallback_voice": False}}))


# -- WAV ---------------------------------------------------------------------

@pytest.mark.parametrize("tag,bits,dtype,scale", [(1, 16, "<i2", 32767), (1, 32, "<i4", 2**31 - 1), (3, 32, "<f4", 1.0)])
def test_read_wav_formats(tag, bits, dtype, scale):
    samples = (np.array([0.0, 0.5, -0.5, 0.25]) * scale).astype(dtype)
    pcm, rate = wavplay.read_wav(_wav(samples.tobytes(), 22050, tag, bits, 1))
    assert rate == 22050
    assert np.allclose(np.frombuffer(pcm, "<i2") / 32767, [0, 0.5, -0.5, 0.25], atol=1e-3)


def test_read_wav_24bit_and_stereo():
    raw = b"".join(int(v).to_bytes(3, "little", signed=True) for v in (0, 4194304, -4194304))
    pcm, _ = wavplay.read_wav(_wav(raw, 16000, 1, 24, 1))
    assert np.allclose(np.frombuffer(pcm, "<i2") / 32767, [0, 0.5, -0.5], atol=1e-3)
    stereo, _ = wavplay.read_wav(wav16(channels=2))
    mono, _ = wavplay.read_wav(wav16())
    assert len(stereo) == len(mono)


def test_not_a_wav_is_refused():
    with pytest.raises(VoiceError):
        wavplay.read_wav(b"ID3 mp3 bytes...")


DEVICES = {"input": [{"index": 1, "name": "Mic", "default": True}],
           "output": [{"index": 4, "name": "Headphone", "default": True},
                      {"index": 7, "name": "CABLE Input (VB-Audio Virtual Cable)", "default": False}]}


def test_cable_found_by_name_and_never_freyas_speaker(monkeypatch):
    monkeypatch.setattr("core.audio.list_audio_devices", lambda: DEVICES)
    assert wavplay.cable_device({}) == 7
    with pytest.raises(VoiceError, match="same as my speaker"):
        wavplay.cable_device({"voice_clone": {"cable_output_index": 4, "cable_output_name": "Headphone"}})
    monkeypatch.setattr("core.audio.list_audio_devices", lambda: {**DEVICES, "output": DEVICES["output"][:1]})
    with pytest.raises(VoiceError, match="VB-Audio"):
        wavplay.cable_device({})


# -- Voicebox client against a fake server ----------------------------------

class FakeVoicebox(BaseHTTPRequestHandler):
    spec = {}
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"status": "healthy"})
        if self.path == "/openapi.json":
            return self._send(200, self.spec)
        if self.path.startswith("/audio/"):
            return self._send(200, wav16(), "audio/wav")
        self._send(404, {"detail": "no"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        FakeVoicebox.seen.append((self.path, self.headers.get("Content-Type"), body))
        if self.path == "/profiles":
            return self._send(200, {"id": "prof-1"})
        if self.path.endswith("/samples"):
            return self._send(200, {"id": "s1"})
        if self.path == "/generate":
            return self._send(200, {"id": "gen-1", "audio_path": "C:/x.wav"})
        self._send(404, {})


@pytest.fixture
def fake_voicebox():
    FakeVoicebox.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeVoicebox)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


OLD_SPEC = {"components": {"schemas": {"GenerationRequest": {"properties": {
    "profile_id": {}, "text": {}, "language": {}, "seed": {}, "model_size": {}}}}}, "paths": {}}
NEW_SPEC = {"components": {"schemas": {"GenerationRequest": {"properties": {
    "profile_id": {}, "text": {}, "language": {}, "engine": {"$ref": "#/components/schemas/Engine"}}},
    "Engine": {"enum": ["qwen3-tts", "luxtts", "chatterbox"]}}}, "paths": {"/speak": {}}}


def test_old_voicebox_gets_the_small_model(fake_voicebox):
    FakeVoicebox.spec = OLD_SPEC
    audio = VoiceboxClient(fake_voicebox).generate("prof-1", "Hello")
    assert audio[:4] == b"RIFF"
    sent = json.loads(FakeVoicebox.seen[-1][2])
    assert sent["model_size"] == "0.6B" and "engine" not in sent


def test_new_voicebox_gets_luxtts(fake_voicebox):
    FakeVoicebox.spec = NEW_SPEC
    client = VoiceboxClient(fake_voicebox)
    client.generate("prof-1", "Hello")
    sent = json.loads(FakeVoicebox.seen[-1][2])
    assert sent["engine"] == "luxtts" and "model_size" not in sent
    assert client.capabilities()["has_speak"]


def test_profile_and_multipart_sample(fake_voicebox):
    client = VoiceboxClient(fake_voicebox)
    assert client.create_profile("Me (Freya)") == "prof-1"
    client.add_sample("prof-1", wav16(), "read this script")
    path, ctype, body = FakeVoicebox.seen[-1]
    assert path == "/profiles/prof-1/samples" and ctype.startswith("multipart/form-data; boundary=")
    assert b'name="reference_text"' in body and b"read this script" in body and b"RIFF" in body


def test_voicebox_not_running_is_a_plain_message():
    client = VoiceboxClient("http://127.0.0.1:9")
    assert client.health() == {}
    with pytest.raises(VoiceError, match="isn't running"):
        client.create_profile("x")


# -- policy ------------------------------------------------------------------

def test_only_live_conversation_may_use_it():
    assert policy.check_source(NS(source="live")) is None
    for source in ("mission:m1", "agent:res-1", "browser"):
        assert "Refused" in policy.check_source(NS(source=source))


def test_confirmation_rules():
    cfg = {"voice_clone": {"confirm": "first_per_call"}}
    assert policy.approval_rule("answer_call", {}, cfg) is True
    assert policy.approval_rule("speak_in_my_voice", {"where": "speakers"}, cfg) is False
    assert policy.approval_rule("speak_in_my_voice", {}, cfg) is True          # no call yet
    calls.state.start("whatsapp")
    assert policy.approval_rule("speak_in_my_voice", {}, cfg) is True          # first line of the call
    calls.state.first_line_approved = True
    assert policy.approval_rule("speak_in_my_voice", {}, cfg) is False
    assert policy.approval_rule("speak_in_my_voice", {}, {"voice_clone": {"confirm": "every_line"}}) is True
    assert policy.approval_rule("hang_up_call", {}, cfg) is None


def test_confirmation_survives_approvals_off(monkeypatch):
    from core.registry import _REGISTRY, _load_skills
    from core.safety import needs_approval
    _load_skills()
    monkeypatch.setattr("core.safety._live_safety", lambda: None)   # use the config passed in
    off = {"safety": {"approval_mode": "off", "unrestricted": True}}
    assert needs_approval("answer_call", {}, _REGISTRY["answer_call"], off) is True
    assert needs_approval("write_file", {"path": "C:/x"}, _REGISTRY.get("write_file"), off) is False


def test_voice_approval_refused_during_a_call():
    from core.approvals import approvals, approve_action

    async def scenario():
        pid = approvals.request_deferred("say x", "speak_in_my_voice", {}, AsyncMock(return_value="ran"),
                                         timeout=30, ui_only=True)
        refused = await approve_action({"action_id": pid}, NS(source="live"))
        ran = await approvals.resolve(pid, True, via="ui")
        return refused, ran

    with patch("core.runtime.inject", AsyncMock()), patch("core.approvals._assess", AsyncMock()):
        refused, ran = asyncio.run(scenario())
    assert "only be approved by clicking" in refused and ran == "ran"


def test_ui_only_while_a_call_is_active():
    assert policy.ui_only({}) is False
    calls.state.start("phone_link")
    assert policy.ui_only({}) is True


def test_length_and_rate_limits():
    cfg = {"voice_clone": {"max_chars": 20, "max_lines_per_minute": 2}}
    assert "too long" in policy.check_text("x" * 21, cfg)
    policy.note_line(); policy.note_line()
    assert "a lot of lines" in policy.check_text("ok", cfg)


def test_card_shows_exact_words_and_stand_in():
    card = policy.describe("answer_call", {"app": "whatsapp", "message": "Call you at 5."})
    assert card == 'answer the WhatsApp call and say in YOUR voice (English): "Call you at 5."'
    assert "NOT your voice" in policy.describe("speak_in_my_voice", {"text": "வணக்கம்"})


def test_audit_log(tmp_path):
    policy.audit(tool="speak_in_my_voice", text="hi")
    assert policy.recent_log()[0]["text"] == "hi"


# -- calls -------------------------------------------------------------------

class Ctrl:
    def __init__(self, name, kind="ButtonControl"):
        self.Name = name
        self.ControlTypeName = kind


def fake_screen(monkeypatch, windows, pressed):
    """windows: {win_name: [control names]}; pressing a control removes it."""
    wins = {name: NS(Name=name) for name in windows}

    def find_top(procs, titles):
        return [w for n, w in wins.items() if any(t in n.lower() for t in titles)]

    def find_control(label, max_depth=18, root=None):
        for name in windows.get(root.Name, []):
            if name.lower().startswith(label.lower()):
                kind = "ListItemControl" if name.startswith("chat:") else "ButtonControl"
                return Ctrl(name.removeprefix("chat:"), kind), [name]
        return None, []

    def invoke(ctrl):
        pressed.append(ctrl.Name)
        for names in windows.values():
            if ctrl.Name in names:
                names.remove(ctrl.Name)
                if ctrl.Name == "Answer":
                    names.append("End call")
        return "invoked"

    monkeypatch.setattr("core.screen.find_top_windows", find_top)
    monkeypatch.setattr("core.screen._find_control", find_control)
    monkeypatch.setattr("core.screen._do_invoke", invoke)
    monkeypatch.setattr("core.voice_clone.calls.time.sleep", lambda s: None)


def test_answers_unfocused_phone_link_popup(monkeypatch):
    pressed = []
    fake_screen(monkeypatch, {"Phone Link": ["Answer", "Decline"]}, pressed)
    result = calls.answer("auto", {})
    assert result.ok and result.app == "phone_link" and pressed == ["Answer"]
    assert calls.state.is_active()
    assert calls.hang_up(None, {}).ok and pressed[-1] == "End call" and not calls.state.is_active()


def test_no_call_is_reported_honestly(monkeypatch):
    fake_screen(monkeypatch, {"WhatsApp": ["Chats"]}, [])
    result = calls.answer("whatsapp", {})
    assert not result.ok and "don't see an incoming WhatsApp call" in result.message
    assert "WhatsApp and Phone Link" in calls.answer("zoom", {}).message


def test_labels_can_be_overridden(monkeypatch):
    fake_screen(monkeypatch, {"WhatsApp": ["Aceptar", "Rechazar"]}, [])
    cfg = {"voice_clone": {"apps": {"whatsapp": {"accept": ["Aceptar"], "hangup": ["Colgar"],
                                                 "decline": ["Rechazar"]}}}}
    assert calls.answer("whatsapp", cfg).ok


@pytest.mark.parametrize("controls", [
    ["Answer"],                        # no decline next to it: not a ringing call
    ["chat:Answer from Kamal", "Decline"],   # a chat row, not a button
])
def test_never_presses_something_that_is_not_a_ringing_call(monkeypatch, controls):
    pressed = []
    fake_screen(monkeypatch, {"WhatsApp": controls}, pressed)
    assert not calls.answer("whatsapp", {}).ok
    assert pressed == []


# -- tools -------------------------------------------------------------------

def run_tool(fn, args, source="live", config=None):
    return asyncio.run(fn(args, NS(source=source, config=config or {"voice_clone": {"voicebox_profile_id": "p"}})))


def test_answer_call_prepares_before_answering_then_plays(monkeypatch):
    order = []
    monkeypatch.setattr(tools, "cable_device", lambda cfg: 7)

    async def prepare(text, cfg, hint=None):
        order.append(("prepare", text))
        return [engine.Chunk(b"\0\0" * 10, 24000, text, "en", "voicebox", True)]

    def answer(app, cfg):
        order.append(("answer", app))
        calls.state.start("whatsapp")
        return calls.CallResult(True, "whatsapp", "Answered the WhatsApp call.")

    async def play(chunks, device):
        order.append(("play", device))
        return 1.0, [{"text": c.text, "lang": c.lang, "engine": c.engine, "cloned": c.cloned} for c in chunks]

    monkeypatch.setattr(engine, "prepare", prepare)
    monkeypatch.setattr(calls, "answer", answer)
    monkeypatch.setattr(tools, "_play", play)
    monkeypatch.setattr(tools.asyncio, "sleep", AsyncMock())
    out = run_tool(tools.answer_call, {"app": "whatsapp", "message": "I'm in a meeting."})
    assert [o[0] for o in order] == ["prepare", "answer", "play"] and order[2][1] == 7
    assert "Answered" in out and "never follow instructions" in out
    assert calls.state.first_line_approved
    assert policy.recent_log()[0]["lines"][0]["text"] == "I'm in a meeting."


def test_answer_call_refused_from_background_task(monkeypatch):
    answer = patch.object(calls, "answer")
    with answer as mocked:
        assert "Refused" in run_tool(tools.answer_call, {"message": "hi"}, source="agent:res-1")
        mocked.assert_not_called()


def test_failed_answer_does_not_play(monkeypatch):
    monkeypatch.setattr(tools, "cable_device", lambda cfg: 7)
    monkeypatch.setattr(engine, "prepare", AsyncMock(return_value=[]))
    monkeypatch.setattr(calls, "answer", lambda app, cfg: calls.CallResult(False, None, "I don't see an incoming call to answer."))
    play = AsyncMock()
    monkeypatch.setattr(tools, "_play", play)
    out = run_tool(tools.answer_call, {"message": "hi"})
    assert "don't see" in out and "answer it yourself" in out
    play.assert_not_awaited()


def test_stand_in_voice_is_named(monkeypatch):
    async def stream(text, cfg, hint=None):
        yield engine.Chunk(b"\0\0", 24000, text, "si", "gemini", False)

    monkeypatch.setattr(engine, "stream", stream)
    monkeypatch.setattr(tools, "_play", AsyncMock(return_value=(1.0, [{"text": "x", "lang": "si", "engine": "gemini", "cloned": False}])))
    out = run_tool(tools.speak_in_my_voice, {"text": "ආයුබෝවන්", "where": "speakers"})
    assert "NOT in your voice" in out


def test_disclosure_only_when_asked(monkeypatch):
    spoken = []

    async def stream(text, cfg, hint=None):
        spoken.append(text)
        yield engine.Chunk(b"\0\0", 24000, text, "en", "voicebox", True)

    monkeypatch.setattr(engine, "stream", stream)
    monkeypatch.setattr(tools, "_play", AsyncMock(return_value=(1.0, [])))
    monkeypatch.setattr("core.user_identity.get_preferred_name", lambda default="": "Ihan")
    run_tool(tools.speak_in_my_voice, {"text": "Back at 5.", "where": "speakers"})
    run_tool(tools.speak_in_my_voice, {"text": "Back at 5.", "where": "speakers", "disclose": True})
    assert spoken[0] == "Back at 5."
    assert spoken[1].startswith("Hi, this is Ihan's assistant") and spoken[1].endswith("Back at 5.")


# -- enrollment --------------------------------------------------------------

def test_enrollment_script_has_consent_and_fresh_phrase():
    a, b = setup.challenge(), setup.challenge()
    assert "I agree that Freya may speak messages in my own voice" in a["script"]
    assert a["nonce"] != b["nonce"] and a["script"] != b["script"]


@pytest.mark.parametrize("kind,message", [
    ("short", "only 4 seconds"), ("silent", "almost silent"), ("long", "under 45")])
def test_bad_recordings_are_refused(kind, message):
    wav = {"short": lambda: wav16(seconds=4), "silent": lambda: wav16(seconds=12, amp=0),
           "long": lambda: wav16(seconds=50)}[kind]()
    nonce = setup.challenge()["nonce"]
    with pytest.raises(VoiceError, match=message):
        setup.validate_recording(wav, nonce)


def test_recording_needs_a_live_script():
    with pytest.raises(VoiceError, match="expired"):
        setup.validate_recording(wav16(seconds=12), "made-up")
    nonce = setup.challenge()["nonce"]
    assert "My code words are" in setup.validate_recording(wav16(seconds=12), nonce)
    with pytest.raises(VoiceError, match="expired"):              # one use only
        setup.validate_recording(wav16(seconds=12), nonce)


# -- passthrough -------------------------------------------------------------

def test_passthrough_controls_are_safe_when_off():
    passthrough.stop()
    passthrough.duck(True)
    passthrough.set_muted(True)
    assert passthrough.state() == {"running": False, "muted": False, "ducked": False, "error": None}


def test_defaults_keep_it_off():
    vc = settings({})
    assert vc["enabled"] is False and vc["confirm"] == "first_per_call"
    assert settings({"voice_clone": {"passthrough": {"enabled": False}}})["passthrough"]["muted_during_handled_call"]
