---
name: watch
description: Watch and analyse a video — a YouTube link or a local video file — and answer questions about what happens in it, including at specific timestamps. Use for "watch this video", "what happens at 2:30", "summarise this clip", "what's in this recording".
version: "1.0"
---

# Watching video

You can actually watch video. Use this whenever Ihan gives you a video link or
points at a video file and wants to know what's in it.

## How to run it

Call `run_skill_script` with skill `watch`, script `watch.py`, and these args:

1. The video — a YouTube URL, any other video URL, or a local file path.
2. The question — what Ihan wants to know. If he didn't ask anything specific,
   pass `summarise this video`.

Optional flags, appended as extra args:

- `--start 1:12` and `--end 2:30` — only look at that window. Use these whenever
  he mentions a moment or a range, so the answer stays focused.
- `--detail high` — slower, but reads on-screen text and fine visual detail.
  Use it for screen recordings, code, slides, or anything text-heavy.

Example arg list for "what happens around the two minute mark in this talk":

    ["https://youtu.be/VIDEO_ID", "what happens around the two minute mark?",
     "--start", "1:45", "--end", "2:30"]

## Talking about what you saw

The script returns your actual analysis of the video. Relay it **conversationally
and out loud** — you watched it, so talk like you watched it. Never read the raw
output verbatim, never narrate the tooling ("the script returned…"), and don't
list timestamps robotically. Lead with the answer to what he actually asked,
then add the interesting bits.

Long videos take a while to process. Say something natural before you start —
"give me a moment, I'm watching it" — so he isn't left in silence.

## When something goes wrong

- **Missing API key** — the script says so; tell him it needs `GEMINI_API_KEY`.
- **Private / age-restricted / members-only** — you cannot watch it. Say so and
  offer to work from a different link.
- **Very long video** — suggest narrowing with `--start` / `--end` rather than
  processing the whole thing.
