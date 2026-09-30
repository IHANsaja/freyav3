"""Client for the Voicebox REST API (http://127.0.0.1:17493 by default).

Stable endpoints (docs/openapi.json): POST /profiles, POST /profiles/{id}/samples
(multipart: file + reference_text), POST /generate (profile_id, text, language)
-> {id, audio_path, ...}, GET /audio/{id}, GET /health. Newer releases add
optional request fields such as an engine choice, so the live /openapi.json is
read once and only fields the running version declares are sent.
"""
import json
import time
import urllib.error
import urllib.request
import uuid

from core.voice_clone import VoiceError

_NOT_RUNNING = ("Voicebox isn't running. Open the Voicebox app (it serves my voice-cloning API "
                "on port 17493) and try again.")


class VoiceboxClient:
    def __init__(self, base_url: str = "http://127.0.0.1:17493", timeout: float = 60.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._caps = None

    # -- HTTP ----------------------------------------------------------------
    def _request(self, method, path, body=None, headers=None, timeout=None, raw=False):
        req = urllib.request.Request(self.base + path, data=body, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                data = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise VoiceError(f"Voicebox refused {method} {path} ({e.code}): {detail}") from e
        except (urllib.error.URLError, OSError) as e:
            raise VoiceError(_NOT_RUNNING) from e
        if raw:
            return data
        return json.loads(data.decode("utf-8")) if data else {}

    def _json(self, method, path, payload, timeout=None):
        return self._request(method, path, json.dumps(payload).encode("utf-8"),
                             {"Content-Type": "application/json"}, timeout=timeout)

    # -- Discovery -----------------------------------------------------------
    def health(self) -> dict:
        """{} when Voicebox is not reachable."""
        try:
            return self._request("GET", "/health", timeout=3) or {"status": "ok"}
        except VoiceError:
            return {}

    def capabilities(self) -> dict:
        """What the running version accepts on /generate, read from its schema."""
        if self._caps is not None:
            return self._caps
        fields, engines = set(), []
        try:
            spec = self._request("GET", "/openapi.json", timeout=5)
            schemas = spec.get("components", {}).get("schemas", {})
            props = schemas.get("GenerationRequest", {}).get("properties", {})
            fields = set(props)
            engine = props.get("engine", {})
            options = engine.get("enum") or [o.get("const") for o in engine.get("anyOf", [])
                                             if isinstance(o, dict) and o.get("const")]
            ref = engine.get("$ref") or next((o.get("$ref") for o in engine.get("anyOf", [])
                                              if isinstance(o, dict) and o.get("$ref")), None)
            if ref:
                options = schemas.get(ref.split("/")[-1], {}).get("enum", []) or options
            engines = [str(e) for e in (options or []) if e]
            has_speak = "/speak" in spec.get("paths", {})
        except VoiceError:
            has_speak = False
        self._caps = {"fields": fields, "engines": engines, "has_speak": has_speak}
        return self._caps

    def pick_engine(self, preferred: str = "auto") -> dict:
        """Extra /generate fields for the engine to use on this machine."""
        caps = self.capabilities()
        extra = {}
        if "engine" in caps["fields"]:
            engines = caps["engines"]
            if preferred and preferred != "auto":
                extra["engine"] = preferred
            else:
                lux = next((e for e in engines if "lux" in e.lower()), None)
                if lux:
                    extra["engine"] = lux
        if "model_size" in caps["fields"] and "engine" not in extra:
            extra["model_size"] = "0.6B"   # the smaller Qwen model; the 1.7B default is slow on CPU
        return extra

    # -- Profiles ------------------------------------------------------------
    def list_profiles(self) -> list:
        return self._request("GET", "/profiles") or []

    def create_profile(self, name: str, language: str = "en", description: str = "") -> str:
        profile = self._json("POST", "/profiles", {"name": name, "language": language,
                                                   "description": description or None})
        if not profile.get("id"):
            raise VoiceError("Voicebox did not return a profile id.")
        return profile["id"]

    def add_sample(self, profile_id: str, wav: bytes, reference_text: str) -> dict:
        boundary = uuid.uuid4().hex
        body = b"".join([
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"reference_text\"\r\n\r\n".encode(),
            reference_text.encode("utf-8"), b"\r\n",
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"voice.wav\"\r\n"
            "Content-Type: audio/wav\r\n\r\n".encode(),
            wav, b"\r\n", f"--{boundary}--\r\n".encode(),
        ])
        return self._request("POST", f"/profiles/{profile_id}/samples", body,
                             {"Content-Type": f"multipart/form-data; boundary={boundary}"},
                             timeout=max(self.timeout, 120))

    def delete_profile(self, profile_id: str) -> None:
        self._request("DELETE", f"/profiles/{profile_id}")

    # -- Speech --------------------------------------------------------------
    def generate(self, profile_id: str, text: str, language: str = "en",
                 engine: str = "auto") -> bytes:
        """Speech in the cloned voice, as audio file bytes (WAV)."""
        payload = {"profile_id": profile_id, "text": text, "language": language,
                   **self.pick_engine(engine)}
        result = self._json("POST", "/generate", payload, timeout=max(self.timeout, 120))
        gen_id = result.get("id")
        if not gen_id:
            raise VoiceError("Voicebox did not return a generation id.")
        # Fetched over HTTP rather than read from audio_path: Voicebox may run
        # as another user or keep its files elsewhere. Newer versions generate
        # in the background, so the audio can take a moment to appear.
        deadline = time.monotonic() + max(self.timeout, 120)
        while True:
            try:
                audio = self._request("GET", f"/audio/{gen_id}", raw=True)
                if audio[:4] == b"RIFF" or len(audio) > 1024:
                    return audio
            except VoiceError as e:
                if "404" not in str(e) and "409" not in str(e) and "425" not in str(e):
                    raise
            if time.monotonic() > deadline:
                raise VoiceError("Voicebox took too long to generate the audio.")
            time.sleep(0.25)
