"""Setup status, the consent-script enrollment, and saving settings."""
import json
import os
import secrets
import time

from core.voice_clone import VoiceError, settings

_CONFIG_PATH = os.path.join("config", "freya_config.json")
_CHALLENGE_TTL_S = 300
_challenges: dict[str, dict] = {}

# Read aloud to enroll. Varied sounds for a good clone, plus a consent sentence
# and a random phrase, so the sample has to be a fresh recording of the person
# agreeing - not a clip of someone else.
_PASSAGE = ("The quick brown fox jumps over the lazy dog near the riverbank. "
            "On Thursday morning I checked the weather, packed my bag, and walked to the station. "
            "Could you call me back at five? I'm happy to help, and I'll be there soon.")
_CONSENT = "I agree that Freya may speak messages in my own voice when I ask her to."
_WORDS = ["amber", "canyon", "harbor", "violet", "maple", "comet", "lantern", "meadow", "silver",
          "orchid", "summit", "pepper", "falcon", "island", "copper", "willow", "rocket", "saffron"]

MIN_SECONDS, MAX_SECONDS = 10.0, 45.0
MIN_RMS = 300.0          # 16-bit RMS; quieter than this is effectively silence


def challenge() -> dict:
    """A fresh script to read, valid for five minutes."""
    now = time.time()
    for nonce in [n for n, c in _challenges.items() if c["expires"] < now]:
        _challenges.pop(nonce, None)
    nonce = secrets.token_hex(8)
    phrase = " ".join(secrets.choice(_WORDS) for _ in range(4))
    script = f"{_PASSAGE} {_CONSENT} My code words are {phrase}."
    _challenges[nonce] = {"script": script, "expires": now + _CHALLENGE_TTL_S}
    return {"nonce": nonce, "script": script, "expires": now + _CHALLENGE_TTL_S,
            "min_seconds": MIN_SECONDS, "max_seconds": MAX_SECONDS}


def validate_recording(wav: bytes, nonce: str) -> str:
    """The script the recording must match. Raises VoiceError when unusable."""
    from core.voice_clone.wavplay import duration_s, read_wav, rms
    entry = _challenges.pop(nonce or "", None)
    if entry is None or entry["expires"] < time.time():
        raise VoiceError("That recording's script has expired. Start the recording again.")
    pcm, rate = read_wav(wav)
    seconds = duration_s(pcm, rate)
    if seconds < MIN_SECONDS:
        raise VoiceError(f"That recording is only {seconds:.0f} seconds. Read the whole script "
                         f"(at least {MIN_SECONDS:.0f} seconds).")
    if seconds > MAX_SECONDS:
        raise VoiceError(f"That recording is {seconds:.0f} seconds; keep it under {MAX_SECONDS:.0f}.")
    if rms(pcm) < MIN_RMS:
        raise VoiceError("The recording is almost silent. Check the microphone and try again.")
    return entry["script"]


def enroll(wav: bytes, nonce: str, config: dict) -> dict:
    """Create (or replace) the user's Voicebox profile from his recording."""
    from core.user_identity import get_preferred_name
    from core.voice_clone.voicebox import VoiceboxClient
    script = validate_recording(wav, nonce)
    vc = settings(config)
    client = VoiceboxClient(vc["voicebox_url"])
    if not client.health():
        raise VoiceError("Voicebox isn't running. Open the Voicebox app, then record again.")
    old = vc.get("voicebox_profile_id")
    name = get_preferred_name("") or "Me"
    profile_id = client.create_profile(f"{name} (Freya)", "en",
                                       "Cloned by Freya from a consent recording.")
    try:
        client.add_sample(profile_id, wav, script)
    except VoiceError:
        try:
            client.delete_profile(profile_id)
        except VoiceError:
            pass
        raise
    save({"voicebox_profile_id": profile_id, "enabled": True})
    if old and old != profile_id:
        try:
            client.delete_profile(old)
        except VoiceError:
            pass
    return {"profile_id": profile_id}


def forget(config: dict) -> str:
    """Delete the user's cloned voice from Voicebox and from the settings."""
    from core.voice_clone.voicebox import VoiceboxClient
    vc = settings(config)
    profile_id = vc.get("voicebox_profile_id")
    note = "Your voice is deleted."
    if profile_id:
        try:
            VoiceboxClient(vc["voicebox_url"]).delete_profile(profile_id)
        except VoiceError as e:
            note = f"Removed it from Freya, but Voicebox said: {e}"
    save({"voicebox_profile_id": None, "enabled": False})
    return note


def save(updates: dict) -> None:
    """Merge `updates` into the voice_clone section of the local config."""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    section = cfg.setdefault("voice_clone", {})
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(section.get(key), dict):
            section[key].update(value)
        else:
            section[key] = value
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def status(config: dict) -> dict:
    """Everything the dashboard's My Voice panel shows, plus a checklist."""
    from core import audio
    from core.voice_clone import calls, passthrough
    from core.voice_clone.voicebox import VoiceboxClient
    vc = settings(config)
    client = VoiceboxClient(vc["voicebox_url"])
    health = client.health()
    engines, engine = [], None
    if health:
        caps = client.capabilities()
        engines = caps["engines"]
        engine = client.pick_engine(vc.get("voicebox_engine", "auto")).get("engine")
    try:
        outputs = audio.list_audio_devices()["output"]
    except Exception:
        outputs = []
    wanted = (vc.get("cable_output_name") or "CABLE Input").lower()
    cable = next((d for d in outputs if d["name"].lower().startswith(wanted)), None)
    enrolled = bool(vc.get("voicebox_profile_id"))
    checklist = [
        {"id": "voicebox", "ok": bool(health), "label": "Voicebox is running",
         "hint": "Install Voicebox from github.com/jamiepine/voicebox and open it."},
        {"id": "engine", "ok": bool(health) and (not engines or bool(engine)),
         "label": "A fast engine is available (LuxTTS on this PC)",
         "hint": "In Voicebox, download the LuxTTS model; larger models are slow without an NVIDIA GPU."},
        {"id": "enrolled", "ok": enrolled, "label": "Your voice is recorded",
         "hint": "Record the on-screen script below (about 20 seconds)."},
        {"id": "cable", "ok": cable is not None, "label": "Virtual audio cable installed",
         "hint": "Install VB-Audio Virtual Cable (vb-audio.com/Cable), then restart Freya."},
        {"id": "app_mic", "ok": None, "label": "WhatsApp and Phone Link use the cable as their microphone",
         "hint": "WhatsApp: Settings > Calls > Microphone = CABLE Output. Phone Link: Windows Settings > "
                 "System > Sound > Volume mixer > Phone Link > Input device = CABLE Output."},
        {"id": "headphones", "ok": None, "label": "Use headphones for calls",
         "hint": "So the caller's voice doesn't reach Freya's microphone."},
    ]
    return {
        "enabled": bool(vc.get("enabled")),
        "enrolled": enrolled,
        "voicebox": {"ok": bool(health), "url": vc["voicebox_url"], "engines": engines, "engine": engine},
        "cable": {"present": cable is not None, "name": cable["name"] if cable else None,
                  "index": cable["index"] if cable else None},
        "passthrough": passthrough.state(),
        "call": {"active": calls.state.is_active(), "app": calls.state.app},
        "confirm": vc.get("confirm"),
        "checklist": checklist,
    }


def status_sentence(config: dict) -> str:
    s = status(config)
    missing = [c["label"] for c in s["checklist"] if c["ok"] is False]
    if not missing:
        return "Your voice is ready for calls."
    return "Not ready yet - still needed: " + "; ".join(missing) + "."
