# My Voice: answering calls in your own voice

Freya can pick up a WhatsApp or Phone Link call and say what you dictate **in your own cloned voice**:

> "Answer the WhatsApp call and tell them I'm in a meeting, I'll call back at 5."

She speaks the lines **you** give her. She does not hold a conversation with the caller on her own, and
she never answers a call unless you ask.

## How it works

| Piece | Role |
| :--- | :--- |
| [Voicebox](https://github.com/jamiepine/voicebox) (MIT, separate app) | Clones your voice locally and generates English speech. Freya uses its REST API on `127.0.0.1:17493`. |
| Gemini TTS (`gemini-3.8-flash-tts`) | Sinhala and Tamil, which no Voicebox engine speaks. This is a **stand-in voice, not yours**, and Freya always says so. |
| [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) (free) | Call apps only hear a microphone. Freya plays your voice into **CABLE Input**; WhatsApp and Phone Link use **CABLE Output** as their mic. |
| Mic passthrough (optional) | Mirrors your real mic into the cable, so you can still talk in calls. Muted while Freya speaks for you, and while she handles a call until you say "put me through". |

## Setup

1. **Install Voicebox** from its [releases](https://github.com/jamiepine/voicebox/releases) and open it.
   In Voicebox, download the **LuxTTS** model. On a PC without an NVIDIA GPU, it is the practical choice
   (English, about 1 GB). Larger models work but take several seconds per sentence.
2. **Install VB-Audio Virtual Cable** and restart Freya.
3. **Point the call apps at the cable:**
   - WhatsApp: *Settings > Calls > Microphone* = **CABLE Output**.
   - Phone Link: *Windows Settings > System > Sound > Volume mixer > Phone Link > Input device* =
     **CABLE Output**.
4. **Record your voice:** Freya dashboard > Settings > **MY_VOICE** > *Start recording*. Read the on-screen
   script (about 20 seconds). It includes a consent sentence and four random code words, so only a fresh
   recording of you can be enrolled. The recording goes to Voicebox; Freya does not keep a copy.
5. **Test it** with *Play test*, which plays on your speakers only.
6. Turn on *Send my own mic into calls too* if you also want to talk in calls yourself.
7. Use **headphones** for calls, so the caller's voice doesn't reach Freya's microphone.

The checklist at the top of the panel shows which of these steps are still missing.

## Using it

| Say | Tool |
| :--- | :--- |
| "Answer the WhatsApp call and tell them I'll call back in ten minutes" | `answer_call` |
| "Tell them I'm driving" (during the call) | `speak_in_my_voice` |
| "Say it's my assistant" | adds the disclosure line (`disclose`) |
| "Put me through" / "mute me" | `set_call_mic` |
| "Hang up" | `hang_up_call` |
| "Is my voice set up?" | `voice_setup_status` |

The audio is generated **before** she presses answer, so the caller hears you about a second after pick-up.

## Safeguards

- **Only you, in conversation.** Missions, sub-agents and browser tasks are refused, so no web page or
  document can make Freya speak as you.
- **You confirm the exact words.** Every answer, and by default the first line of each call
  (*Ask me to confirm*: every line / first line of each call / only when answering). This holds even when
  approvals are switched off elsewhere.
- **Click-only during a call.** While a call is being handled, a spoken "yes" is refused, because the
  caller's voice can reach the microphone.
- **Only a ringing call is answered.** Freya presses answer only when a real answer button and a
  decline button are both showing.
- **Limits:** 400 characters per line, 6 lines a minute.
- **A record of everything said as you** in `memory/voice_log.jsonl` (private, gitignored), shown in the
  panel.
- **Stand-in voices are always named** (on the approval card and in her reply).
- **Delete** your voice from Freya and Voicebox any time with *Delete my voice*.

Laws on recording calls and on AI voices differ by country, and some require telling the other person.
Freya only says it's your assistant when you ask her to, so that part is up to you.

## Configuration

`voice_clone` in `config/freya_config.json`. Off until you record your voice. Notable keys:

| Key | Default | |
| :--- | :--- | :--- |
| `voicebox_url` | `http://127.0.0.1:17493` | Where Voicebox listens. |
| `voicebox_engine` | `auto` | Prefers LuxTTS, then the 0.6B Qwen model. |
| `allow_fallback_voice` | `true` | Use the labelled Gemini stand-in when Voicebox is down or for Sinhala/Tamil; `false` refuses instead. |
| `cable_output_name` | `CABLE Input` | The playback device that feeds the call apps. |
| `confirm` | `first_per_call` | `every_line`, `first_per_call` or `off_after_answer`. |
| `max_chars` / `max_lines_per_minute` | `400` / `6` | Limits per line and per minute. |
| `apps.<whatsapp\|phone_link>` | | Override `accept` / `decline` / `hangup` button labels if your app is in another language. |
| `disclosure` | | The line said when you ask for it, per language; `{name}` comes from `memory/MEMORY.md`. |

## Not yet

- Cloning your voice for Sinhala and Tamil (Gemini voice replication, where available on your project).
- Checking the spoken code words by transcription during enrollment.
- An "incoming call from X, want me to answer?" prompt. It will ask; it will never answer by itself.
