"""Gemini text-to-speech, for the languages Voicebox cannot speak.

Gemini 3.8 Flash TTS speaks 100+ languages including Sinhala and Tamil and
returns 24 kHz mono 16-bit PCM. This uses a prebuilt Gemini voice, which is NOT
the user's voice; callers of this module must say so. (Gemini also offers voice
replication from reference + consent audio; wiring that in is a later step.)
"""
from google import genai
from google.genai import types

from core.voice_clone import VoiceError, settings
from core.voice_clone.wavplay import make_wav

_RATE = 24000


async def synthesize(text: str, config: dict) -> bytes:
    """WAV bytes of `text` in the configured prebuilt Gemini voice."""
    from config import get_agent_api_key
    from core.quota import generate
    vc = settings(config)
    client = genai.Client(api_key=get_agent_api_key(),
                          http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
    try:
        resp = await generate(
            client, quota_config=config, model=vc["gemini_tts_model"], contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=vc["gemini_fallback_voice"]))),
            ))
    finally:
        close = getattr(client.aio, "aclose", None)
        if close is not None:
            await close()
    for cand in resp.candidates or []:
        for part in (cand.content.parts if cand.content else None) or []:
            blob = getattr(part, "inline_data", None)
            if blob is not None and blob.data:
                data = blob.data
                return data if data[:4] == b"RIFF" else make_wav(data, _rate(blob.mime_type))
    raise VoiceError("Gemini returned no audio for that line.")


def _rate(mime: str | None) -> int:
    """'audio/L16;codec=pcm;rate=24000' -> 24000."""
    for part in (mime or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == "rate" and value.isdigit():
            return int(value)
    return _RATE
