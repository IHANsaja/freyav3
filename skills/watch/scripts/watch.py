"""
watch.py — analyse a video and answer a question about it.

Adapted from the claude-video `/watch` skill (github.com/bradautomates/claude-video),
which builds a yt-dlp → ffmpeg → Whisper pipeline and hands frames to a multimodal
coding agent. Freya's runtime is different in two ways that make that pipeline the
wrong shape here:

  • No Groq/OpenAI key is configured (Whisper is unavailable), but Gemini keys are
    — and Gemini is natively multimodal over video, audio AND frames at once.
  • Gemini ingests a YouTube URL directly, so the common case needs no download,
    no frame extraction, and no local ffmpeg/yt-dlp at all.

So this keeps the skill's interface (source + question + --start/--end/--detail)
and replaces the internals with Gemini video understanding. Local files are sent
through the Files API. yt-dlp is used only as a fallback for non-YouTube URLs,
and is optional — if it's missing we say so instead of crashing.

Usage:
    watch.py <url-or-path> <question> [--start MM:SS] [--end MM:SS] [--detail high]
"""

import argparse
import os
import re
import sys
import time

# Run standalone via run_skill_script → make the project importable for config.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

MODEL = "gemini-2.5-flash"
UPLOAD_TIMEOUT = 600  # seconds to wait for the Files API to finish processing
_YT = re.compile(r"(youtube\.com/|youtu\.be/)", re.I)


def _secs(stamp: str | None) -> int | None:
    """'2:30' / '1:12:00' / '90' → seconds."""
    if not stamp:
        return None
    parts = str(stamp).strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    total = 0
    for n in nums:
        total = total * 60 + n
    return total


def _clock(sec: int) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def _client():
    try:
        from config import get_agent_api_key
        key = get_agent_api_key()
    except Exception:
        key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("No Gemini API key is configured, so I can't watch video. "
              "Set GEMINI_API_KEY in the project's .env.")
        sys.exit(1)
    from google import genai
    return genai.Client(api_key=key)


def _download(url: str) -> str:
    """Fetch a non-YouTube URL with yt-dlp (optional dependency)."""
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("yt-dlp"):
        print("That link isn't YouTube, and yt-dlp isn't installed so I can't download it. "
              "Install it with 'pip install yt-dlp', or give me a YouTube link or a local file.")
        sys.exit(1)
    out = os.path.join(tempfile.mkdtemp(), "video.%(ext)s")
    try:
        subprocess.run(
            ["yt-dlp", "-f", "mp4/best", "-o", out, url],
            check=True, capture_output=True, text=True, timeout=600,
        )
    except subprocess.CalledProcessError as e:
        print(f"Couldn't download that video: {(e.stderr or '').strip()[:300]}")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("That download took too long, so I gave up on it.")
        sys.exit(1)
    folder = os.path.dirname(out)
    files = [f for f in os.listdir(folder) if f.startswith("video.")]
    if not files:
        print("The download finished but produced no video file.")
        sys.exit(1)
    return os.path.join(folder, files[0])


def _upload(client, path: str):
    """Upload a local file and block until Gemini has finished processing it."""
    if not os.path.isfile(path):
        print(f"There's no video file at {path}.")
        sys.exit(1)
    handle = client.files.upload(file=path)
    deadline = time.time() + UPLOAD_TIMEOUT
    while getattr(handle.state, "name", handle.state) == "PROCESSING":
        if time.time() > deadline:
            print("Gemini was still processing that video after ten minutes, so I stopped waiting. "
                  "Try a shorter clip, or narrow it with --start and --end.")
            sys.exit(1)
        time.sleep(3)
        handle = client.files.get(name=handle.name)
    if getattr(handle.state, "name", handle.state) == "FAILED":
        print("Gemini couldn't process that video file — it may be corrupt or an unsupported format.")
        sys.exit(1)
    return handle


def main() -> None:
    ap = argparse.ArgumentParser(description="Watch a video and answer a question about it.")
    ap.add_argument("source", help="YouTube URL, other video URL, or local file path")
    ap.add_argument("question", nargs="?", default="Summarise this video.",
                    help="What to find out about the video")
    ap.add_argument("--start", help="Start timestamp, e.g. 1:12")
    ap.add_argument("--end", help="End timestamp, e.g. 2:30")
    ap.add_argument("--detail", choices=["normal", "high"], default="normal",
                    help="'high' reads on-screen text and fine visual detail")
    a = ap.parse_args()

    from google.genai import types
    client = _client()
    source = a.source.strip()

    # ── Build the video part ────────────────────────────────────────────────
    # Clip windows ride along as video_metadata so Gemini only samples that
    # range — far cheaper and more accurate than asking it to skip ahead.
    start_s, end_s = _secs(a.start), _secs(a.end)
    meta = None
    if start_s is not None or end_s is not None:
        meta = types.VideoMetadata(
            start_offset=f"{start_s or 0}s",
            end_offset=f"{end_s}s" if end_s is not None else None,
        )

    uploaded = None
    if source.lower().startswith(("http://", "https://")):
        if _YT.search(source):
            part = types.Part(
                file_data=types.FileData(file_uri=source),
                video_metadata=meta,
            )
        else:
            uploaded = _upload(client, _download(source))
            part = types.Part(
                file_data=types.FileData(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
                video_metadata=meta,
            )
    else:
        uploaded = _upload(client, os.path.abspath(os.path.expanduser(source)))
        part = types.Part(
            file_data=types.FileData(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
            video_metadata=meta,
        )

    window = ""
    if start_s is not None or end_s is not None:
        window = (f" Focus only on {_clock(start_s or 0)}"
                  f"{' to ' + _clock(end_s) if end_s is not None else ' onwards'}.")
    detail = (" Read any on-screen text, code or UI labels carefully and quote them exactly."
              if a.detail == "high" else "")

    prompt = (
        f"You are watching this video for someone who cannot see it, and they asked: "
        f"\"{a.question}\".{window}{detail}\n\n"
        "Answer that question directly and concretely, citing timestamps for anything you "
        "reference. Describe what actually happens on screen and what is said. Be specific "
        "rather than vague, and keep it tight enough to be read aloud."
    )

    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=types.Content(role="user", parts=[part, types.Part(text=prompt)]),
        )
        print((resp.text or "").strip() or "I watched it but couldn't make anything out.")
    except Exception as e:
        msg = str(e)
        if "PERMISSION_DENIED" in msg or "private" in msg.lower():
            print("I can't access that video — it looks private, age-restricted or members-only.")
        elif "quota" in msg.lower() or "RESOURCE_EXHAUSTED" in msg or "429" in msg:
            print("I've hit the API quota for video analysis. Try again in a bit.")
        else:
            print(f"I couldn't analyse that video: {msg[:300]}")
        sys.exit(1)
    finally:
        if uploaded is not None:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass


if __name__ == "__main__":
    main()
