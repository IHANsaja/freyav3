"""Speaking in the user's own (cloned) voice - e.g. answering a call with a
message he dictated.

    Voicebox (local app, github.com/jamiepine/voicebox) clones the voice and
    generates English speech; Gemini TTS covers Sinhala and Tamil. The audio is
    played into a virtual audio cable (VB-Audio "CABLE Input") that WhatsApp or
    Phone Link use as their microphone, so the caller hears it.

Modules: voicebox (REST client), gemini_tts, engine (language routing,
sentences), wavplay (WAV decode + playback), passthrough (the user's own mic
into the cable), calls (answer / hang up via UI Automation), policy (who may
trigger it, confirmation, audit log), setup (status + enrollment), tools.
"""
from copy import deepcopy

DEFAULTS = {
    "enabled": False,
    "voicebox_url": "http://127.0.0.1:17493",
    "voicebox_profile_id": None,
    # "auto" prefers LuxTTS (fast on CPU, English), then the smallest Qwen model.
    "voicebox_engine": "auto",
    "gemini_tts_model": "gemini-3.8-flash-tts",
    "gemini_fallback_voice": "Kore",
    # Voicebox down, or a language it cannot speak: use a Gemini voice, always
    # labelled "not your voice". False = refuse instead.
    "allow_fallback_voice": True,
    "cable_output_index": None,
    "cable_output_name": "CABLE Input",
    "passthrough": {"enabled": True, "muted_during_handled_call": True},
    # every_line | first_per_call | off_after_answer
    "confirm": "first_per_call",
    "max_chars": 400,
    "max_lines_per_minute": 6,
    "answer_settle_ms": 1200,
    "disclosure": {
        "en": "Hi, this is {name}'s assistant, speaking in {name}'s voice.",
        "si": "ආයුබෝවන්, මේ {name}ගේ සහායකයා, {name}ගේ කටහඬින් කතා කරනවා.",
        "ta": "வணக்கம், இது {name} அவர்களின் உதவியாளர், {name} அவர்களின் குரலில் பேசுகிறேன்.",
    },
    "apps": {},
    "audit_log": True,
}


def settings(config: dict | None) -> dict:
    """The voice_clone section with every default filled in."""
    merged = deepcopy(DEFAULTS)
    for key, value in ((config or {}).get("voice_clone") or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


class VoiceError(Exception):
    """A plain-language failure meant to be told to the user."""
