"""Which engine speaks each sentence, and in what order.

English goes to Voicebox (the user's cloned voice). Sinhala and Tamil go to a
Gemini voice, because no Voicebox engine speaks them - and that chunk is marked
cloned=False so it is never passed off as the user's own voice.
"""
import asyncio
import re
from dataclasses import dataclass

from core.voice_clone import VoiceError, settings
from core.voice_clone.wavplay import read_wav

_SINHALA = re.compile(r"[඀-෿]")
_TAMIL = re.compile(r"[஀-௿]")
_SENTENCE_END = re.compile(r"(?<=[.!?෴।])\s+")
LANG_NAMES = {"en": "English", "si": "Sinhala", "ta": "Tamil"}


@dataclass
class Chunk:
    pcm: bytes
    rate: int
    text: str
    lang: str
    engine: str      # "voicebox" | "gemini"
    cloned: bool     # True only when it is the user's cloned voice


def detect_lang(text: str, hint: str | None = None) -> str:
    """'si', 'ta' or 'en'. An explicit hint wins; otherwise the script decides."""
    if hint:
        hint = hint.lower().strip()
        for code, name in LANG_NAMES.items():
            if hint in (code, name.lower()):
                return code
    if _SINHALA.search(text):
        return "si"
    if _TAMIL.search(text):
        return "ta"
    return "en"


def split_sentences(text: str, max_chars: int = 220) -> list[str]:
    """Sentences, with any over max_chars cut at a comma or space."""
    out = []
    for sentence in _SENTENCE_END.split(" ".join(text.split())):
        while len(sentence) > max_chars:
            cut = max(sentence.rfind(",", 0, max_chars), sentence.rfind(" ", 0, max_chars))
            cut = cut if cut > max_chars // 3 else max_chars
            out.append(sentence[:cut + 1].strip())
            sentence = sentence[cut + 1:].strip()
        if sentence:
            out.append(sentence)
    return out


async def _one(sentence: str, lang: str, config: dict) -> Chunk:
    vc = settings(config)
    if lang == "en":
        profile = vc.get("voicebox_profile_id")
        try:
            if not profile:
                raise VoiceError("Your voice isn't set up yet - record it under My Voice in settings.")
            from core.voice_clone.voicebox import VoiceboxClient
            client = VoiceboxClient(vc["voicebox_url"])
            wav = await asyncio.to_thread(client.generate, profile, sentence, "en",
                                          vc.get("voicebox_engine", "auto"))
            pcm, rate = read_wav(wav)
            return Chunk(pcm, rate, sentence, lang, "voicebox", True)
        except VoiceError:
            if not vc.get("allow_fallback_voice"):
                raise
    elif not vc.get("allow_fallback_voice"):
        raise VoiceError(f"I can't speak {LANG_NAMES[lang]} in your voice yet, and a stand-in "
                         "voice is switched off.")
    from core.voice_clone import gemini_tts
    wav = await gemini_tts.synthesize(sentence, config)
    pcm, rate = read_wav(wav)
    return Chunk(pcm, rate, sentence, lang, "gemini", False)


async def prepare(text: str, config: dict, lang_hint: str | None = None) -> list[Chunk]:
    """Every sentence, generated up front (used before answering a call, so the
    caller hears no gap after pick-up)."""
    return [c async for c in stream(text, config, lang_hint)]


async def stream(text: str, config: dict, lang_hint: str | None = None):
    """Chunks in order; the next sentence is generated while one is played."""
    sentences = split_sentences(text)
    if not sentences:
        return
    pending = asyncio.ensure_future(_one(sentences[0], detect_lang(sentences[0], lang_hint), config))
    for i in range(len(sentences)):
        chunk = await pending
        if i + 1 < len(sentences):
            nxt = sentences[i + 1]
            pending = asyncio.ensure_future(_one(nxt, detect_lang(nxt, lang_hint), config))
        yield chunk
