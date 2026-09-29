from asyncio import selector_events
import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from google import genai
from google.genai import types
from core.tools import dispatch
from core import runtime

# A tool still running after this long is answered "running in background" so
# the live model can keep talking; the result is injected when it finishes.
SLOW_TOOL_SECONDS = 2.0
# Tools whose response must be the real result (the model's next move depends
# on it immediately, or the result drives session control flow).
# Everything else that runs past SLOW_TOOL_SECONDS goes to the background so she
# can keep talking; its result comes back as a "task finished — carry on" note,
# which is what keeps a find-then-open chain going.
FOREGROUND_TOOLS = {"switch_mode", "look_at_screen", "capture_screen", "search_tools"}
# Instant and read-only: safe to answer immediately even while a job is running,
# so a status question or a facial expression never waits behind real work.
INSTANT_TOOLS = {"set_expression", "set_gesture", "set_idle_state", "trigger_emphasis",
                 "trigger_thinking", "trigger_listening", "animate_transition",
                 "check_agents", "mission_status", "list_pending_actions"}


def _effective_tool(name: str, args: dict) -> str:
    """run_tool(name=X) is X as far as scheduling is concerned."""
    if name == "run_tool":
        return str((args or {}).get("name") or name)
    return name


# A real tool call written into her speech instead of made: ",name:open_path}",
# 'run_tool{"name": "list_dir"...'. Only names that are actual tools count.
_SPOKEN_ANY_CALL = re.compile(r"""(?:\bname\s*["']?\s*[:=]\s*["']?|\b)([a-z]+(?:_[a-z]+)+)\s*["']?\s*[({}]""")
from core.task_policy import TOOLS_FIRST, WORK_RHYTHM
from core.turn_taking import TURN_TAKING, DoubleTalkDetector, TurnTaker, interruption_note, trim_to_fraction
from core.live_protocol import (ModeChange, ThinkingTaskFailed, Interaction, is_thinking,
                                is_thinking_failure, setup_options, tool_behavior, routing_instruction)
from core.registry import build_declarations, dispatch as registry_dispatch, ToolContext
from core import tool_index  # registers search_tools / run_tool
from core import activity_overlay as activity_ui
from core.resilience import breaker, health, DEGRADED, OK
import base64

# ─────────────────────────────────────────────
#  TOOL DEFINITIONS  (Gemini function calling)
# ─────────────────────────────────────────────
# Protocol debris that occasionally lands in the OUTPUT TRANSCRIPTION stream —
# the model narrating its own function call rather than speaking. Observed live:
#
#   Freya: response:trigger_emphasis{}It is now Saturday, August 8th...
#
# The system prompt already tells her never to speak tool names, but this is not
# something she chose to say — it arrives in the transcription channel, so no
# amount of prompting removes it. Left alone it is spoken aloud, printed, shown
# in the dashboard, and then written into memory and day context, where it comes
# back as context on the next turn.
_SPEECH_NOISE = re.compile(
    r"""(?xi)
    response:\s*\w+\s*\{[^{}]*\}   # response:trigger_emphasis{}
    | \btrigger_[a-z_]+\b(?:\s*\{[^{}]*\})?  # bare trigger_thinking / trigger_x{}
    | ^\s*tool_(?:code|outputs?)\s*:? # stray tool_code / tool_output markers
    | \[SILENT[^\]]*\]             # our own silent-note marker, if it ever echoes
    """
)


# Body-language calls the model sometimes SPEAKS instead of calling, e.g.
# "set_expression(expression='calm', intensity=0.7)". The transcription also
# renders it with spaces ("set expression(...)"), so underscores are optional.
_AVATAR_TOOLS = ("set_expression", "set_gesture", "set_idle_state", "trigger_emphasis",
                 "trigger_thinking", "trigger_listening", "animate_transition")
_SPOKEN_CALL = re.compile(
    r"\b(" + "|".join(t.replace("_", r"[_ ]?") for t in _AVATAR_TOOLS) + r")\s*\(([^)]*)\)?",
    re.IGNORECASE,
)
_CALL_ARG = re.compile(r"(\w+)\s*[=:]\s*['\"]?([\w.]+)['\"]?")


def _extract_spoken_calls(text: str) -> tuple[str, list[tuple[str, dict]]]:
    """Pull spoken avatar tool calls out of her text. Returns the text without
    them, plus (tool, args) pairs so they can be run for real instead."""
    calls = []

    def grab(m):
        name = re.sub(r"[_ ]", "", m.group(1).lower())
        tool = next(t for t in _AVATAR_TOOLS if t.replace("_", "") == name)
        args = {}
        for k, v in _CALL_ARG.findall(m.group(2) or ""):
            try:
                args[k] = float(v) if k == "intensity" else v
            except ValueError:
                args[k] = v
        calls.append((tool, args))
        return " "

    return re.sub(r"\s{2,}", " ", _SPOKEN_CALL.sub(grab, text)).strip(), calls


def _trace_frame(response) -> None:
    """Print a Live server frame minus audio bytes and routine transcription."""
    try:
        data = response.model_dump(exclude_none=True, mode="json")
    except Exception as e:
        print(f"  [trace] unprintable frame: {e}")
        return
    sc = data.get("server_content") or {}
    for part in (sc.get("model_turn") or {}).get("parts") or []:
        if "inline_data" in part:
            part["inline_data"] = f"<{part['inline_data'].get('mime_type', 'audio')}>"
    sc.pop("input_transcription", None)
    sc.pop("output_transcription", None)
    if not sc:
        data.pop("server_content", None)
    data.pop("session_resumption_update", None)
    if data.get("server_content", {}).get("model_turn", {}).get("parts") and all(
            isinstance(p.get("inline_data"), str) and len(p) == 1
            for p in data["server_content"]["model_turn"]["parts"]):
        data["server_content"]["model_turn"] = "<audio>"
        if data["server_content"] == {"model_turn": "<audio>"}:
            return  # pure audio chunk: too noisy to print
    if data:
        print(f"  [trace] {json.dumps(data, ensure_ascii=False)[:1500]}")


def _clean_speech(text: str) -> str:
    """Strip protocol debris out of a spoken-transcription fragment."""
    cleaned = _SPEECH_NOISE.sub(" ", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


TOOL_DECLARATIONS = [
    # NOTE: `open_app` is deliberately NOT declared here. It lives in
    # core/machine_index.py as a real @tool, because the declaration is the
    # whole feature: this one used to advertise seven hardcoded config keys
    # while the handler behind it could reach every app on the machine.
    # Declaring it in both places makes Gemini reject the tool list outright.
    types.FunctionDeclaration(
        name="close_app",
        description="Close or kill a running application.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "name": types.Schema(type=types.Type.STRING,
                    description="App name e.g. valorant, discord, steam")
            },
            required=["name"]
        )
    ),
    types.FunctionDeclaration(
        name="switch_mode",
        description="Switch Freyja into a different operational mode, e.g. coding or language learning.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "mode": types.Schema(
                    type=types.Type.STRING,
                    description="Mode identifier: complex_tasks for hard reasoning, debugging or multi-step research; default for normal conversation; language_learning, coding or other custom modes."
                )
            },
            required=["mode"]
        )
    ),
    types.FunctionDeclaration(
        name="get_news",
        description="Latest news on a topic, read aloud and shown with images on the dashboard. "
                    "Never open a browser for news.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "topic": types.Schema(type=types.Type.STRING,
                    description="News topic e.g. technology, world, sports, Sri Lanka")
            },
            required=["topic"]
        )
    ),
    types.FunctionDeclaration(
        name="shutdown_computer",
        description="Shutdown the computer after a delay.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "delay_seconds": types.Schema(type=types.Type.INTEGER,
                    description="Seconds before shutdown. Default is 30.")
            },
            required=[]
        )
    ),
    types.FunctionDeclaration(
        name="take_screenshot",
        description="Take a screenshot and save it to the Desktop.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={},
            required=[]
        )
    ),
    types.FunctionDeclaration(
        name="open_folder",
        description="Open a folder in Windows Explorer.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "name": types.Schema(type=types.Type.STRING,
                    description="Folder name configured in config e.g. work")
            },
            required=["name"]
        )
    ),
    types.FunctionDeclaration(
        name="get_weather",
        description="Get current weather for any city.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "city": types.Schema(type=types.Type.STRING,
                    description="City name e.g. Colombo, London, Tokyo")
            },
            required=["city"]
        )
    ),
    # NOTE: `open_project` is declared in core/machine_index.py alongside
    # `open_app`, for the same reason — this declaration said "configured in
    # config e.g. freyav3", so the model only ever tried the config keys and
    # the handler behind it could only answer "add it to freya_config.json".
    types.FunctionDeclaration(
        name="run_terminal_command",
        description="Run a terminal or shell command and read back the output. Good for git status, pip list, directory listing etc.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "command": types.Schema(type=types.Type.STRING,
                    description="The shell command to run e.g. git status, pip list, dir")
            },
            required=["command"]
        )
    ),
    types.FunctionDeclaration(
        name="dance_for_user",
        description="Make Freyja perform a random dance animation when the user asks her to dance (e.g., 'can you dance for me', 'show me a dance', 'dance').",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={},
            required=[]
        )
    ),
    types.FunctionDeclaration(
        name="capture_screen",
        description="Capture the user's screen so you can see what's on it. Use only for an explicit screen-view request or visual information unavailable through file/DOM/accessibility tools. For 'see what is in this file', use read_document/read_file instead.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={},
            required=[]
        )
    ),
    types.FunctionDeclaration(
        name="type_text",
        description="Type text using the keyboard.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "text": types.Schema(type=types.Type.STRING, description="Text to type"),
            },
            required=["text"]
        )
    ),
    types.FunctionDeclaration(
        name="press_key",
        description="Press a keyboard key or hotkey into the focused window. e.g. 'enter', 'escape', "
                    "'ctrl+c', 'ctrl+shift+t'.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "key": types.Schema(type=types.Type.STRING, description="Key or hotkey combo e.g. enter, ctrl+c"),
            },
            required=["key"]
        )
    ),
]


class SessionRotation(Exception):
    """Not an error — the Live API asked us to move to a fresh connection.

    Gemini caps how long one websocket may live. Shortly before that cap it
    sends a GoAway; if the client keeps talking on the old socket the server
    kills it with `1008 ... failed to close the connection after receiving a
    GoAway signal once the session duration expired`, which is what used to
    surface as Freya randomly stopping mid-conversation.

    We now close voluntarily when GoAway arrives and reconnect with the
    session-resumption handle, so the rotation is invisible to the user and must
    NOT be counted against the reconnect-failure budget.
    """


_ROTATION_MARKERS = (
    "goaway",
    "go away",
    "session duration",
    "deadline exceeded",
    "keepalive ping timeout",
)


def is_rotation(exc: Exception) -> bool:
    """True when a dropped session is a routine lifecycle event, not a fault.

    Rotations must not burn the reconnect-failure budget: the old loop counted
    every session-duration expiry as a failure, so five normal rotations were
    enough to shut Freya down for the rest of the evening.
    """
    if isinstance(exc, SessionRotation):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _ROTATION_MARKERS)


class FreyaModel:
    def __init__(self, api_key, model_id, voice, personality, config, transcript=None,
                 resume_handle=None, continue_task=False):
        self.client = genai.Client(api_key=api_key)
        self.model_id = model_id
        self.voice = voice
        self.personality = personality
        self.config = config
        self.transcript = transcript
        # Server-side conversation state token. Carried across reconnects so a
        # new socket picks up the SAME conversation instead of a blank one —
        # this is what stops Freya forgetting what we were working on.
        self.resume_handle = resume_handle
        self.continue_task = continue_task
        self._interaction = Interaction(is_thinking(model_id))
        activity_ui.configure(config)
        self._pending_tools = 0
        self.session = None
        self.connected = False
        # Serializes proactive speech. Injects arrive from many independent
        # background powers — scheduler, ambient watcher, missions, approvals,
        # finished sub-agents, webcam gesture touches — none of which know about
        # each other. Without a lock two can be pushed into the session at once
        # and their turns interleave; without an idle check one can land while
        # Freya is mid-sentence, which surfaces later as her apparently
        # answering a question nobody asked.
        self._inject_lock = asyncio.Lock()
        # Bound in run() to the session's `model_speaking` event — set while
        # Freya is actually talking, cleared when she stops.
        self._model_speaking = None

    # Conversation is the richest signal for what a day was about, but a line per
    # utterance would drown the day timeline. One sample every few minutes is
    # enough to reconstruct the shape of the day at rotation time.
    _DAY_TURN_INTERVAL_S = 180.0
    _last_day_turn = 0.0

    def _note_day_turn(self, text: str):
        now = time.time()
        if now - self._last_day_turn < self._DAY_TURN_INTERVAL_S or len(text) < 15:
            return
        self._last_day_turn = now
        try:
            from core import day_context
            day_context.note("conversation", text[:200], subject="said")
        except Exception:
            pass

    def _compression_budget(self, declarations) -> tuple[int, int]:
        """(trigger_tokens, target_tokens) for context-window compression.

        This is the single most consequential number in the whole client, and it
        used to be wrong in a way nothing surfaced. The budget has to hold an
        *immovable* baseline — the system instruction plus every tool
        declaration — before it can hold one word of conversation. With ~100
        tools that baseline is around 18k tokens, and the old settings were
        trigger=16k with target unset (the server then assumes trigger/2 = 8k).

        So compression fired on the very first turn and tried to shrink the
        context to less than half of what could not be removed: the sliding
        window evicted the conversation continuously. That is why Freya could
        explain a screenshot of his notes and then, one turn later, have no idea
        what "question 12" referred to — and why she sometimes re-greeted him
        mid-answer, which is what a model does when its history is truncated out
        from under it.

        The fix is to size the budget above the baseline and to say so out loud
        at startup, so this can never again be wrong silently.
        """
        freya_cfg = (self.config or {}).get("freya", {})
        trigger = int(freya_cfg.get("compression_trigger_tokens", 96000))
        target = int(freya_cfg.get("compression_target_tokens", 32000))

        # The SDK requires target < trigger; a config that violates it would be
        # rejected at connect time, so clamp rather than fail.
        if target >= trigger:
            target = max(1000, trigger // 2)

        # Measure what actually goes over the wire. `str(decl)` is the pydantic
        # repr, which pads every unset field with `=None` and overstates the
        # real cost by roughly a third — a meter that lies is worse than none.
        def _decl_chars(d) -> int:
            try:
                return len(d.model_dump_json(exclude_none=True, by_alias=True))
            except Exception:
                return len(str(d))

        prompt_tokens = (len(self.personality or "") + len(getattr(self, "_tool_index_prompt", ""))) // 4
        tool_tokens = sum(_decl_chars(d) for d in declarations) // 4
        baseline = prompt_tokens + tool_tokens

        print(f"  Context budget: baseline ~{baseline:,} tok "
              f"(prompt {prompt_tokens:,} + {len(declarations)} tools {tool_tokens:,})")
        if target <= baseline:
            print(f"  !! COMPRESSION TARGET TOO LOW: target {target:,} <= baseline {baseline:,}. "
                  f"Every turn will be evicted as soon as it is spoken. Raise "
                  f"freya.compression_target_tokens in config/freya_config.json.")
        else:
            print(f"                  trigger {trigger:,} / target {target:,} "
                  f"-> ~{target - baseline:,} tok for conversation")
        return trigger, target

    def get_config(self):
        # ── Native VAD tuning: tighter, more human turn-taking ──
        vad_cfg = (self.config or {}).get("vad", {})
        start_map = {
            "LOW": types.StartSensitivity.START_SENSITIVITY_LOW,
            "HIGH": types.StartSensitivity.START_SENSITIVITY_HIGH,
        }
        end_map = {
            "LOW": types.EndSensitivity.END_SENSITIVITY_LOW,
            "HIGH": types.EndSensitivity.END_SENSITIVITY_HIGH,
        }
        # Built once so the budget can be measured against the exact list that
        # gets sent — the declarations ARE most of the immovable baseline.
        # With tool_index enabled only a core set goes out in full; the rest is
        # listed by name in the prompt and reached via search_tools/run_tool.
        declarations, deferred = tool_index.split(
            TOOL_DECLARATIONS + build_declarations(self.config), self.config)
        self._tool_index_prompt = tool_index.index_prompt(deferred)
        if deferred:
            print(f"  Tool index: {len(declarations)} tools loaded, {len(deferred)} deferred")
        behavior = tool_behavior(self.model_id)
        if behavior:
            declarations = [d.model_copy(update={"behavior": types.Behavior(behavior)}) for d in declarations]
        trigger_tokens, target_tokens = self._compression_budget(declarations)

        return types.LiveConnectConfig(
            **setup_options(self.model_id, self.config),
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part(text=self.personality + "\n\n" + routing_instruction(self.config, self.model_id) + "\n\n" + WORK_RHYTHM + TOOLS_FIRST + "\n" + TURN_TAKING + "\n" +
                    "TRADING LAB: Call get_trading_lab_context with no session_id first before answering questions about the active chart or paper account. It resolves the focused workspace automatically; do not ask the user for a session before trying it. Use its structured facts (chart_legend, recent_candles, market_summary, live_price, indicators, orders) instead of screenshots; never capture_screen for the Trading Lab. For questions about colored lines, use chart_legend and answer the original question directly. Explaining indicator mechanics does not require a thesis. Do not replace the answer with an acknowledgment or offer to explain. "
                    "TRADING TEACHER: In the Trading Lab you are the user's patient, warm trading teacher. Assume they know NOTHING about trading unless get_trading_learner_profile says otherwise; call it at the start of any trading conversation. "
                    "Speak in plain everyday words. Avoid jargon; if a term is unavoidable (candle, EMA, RSI, support, stop loss...), explain it simply with an everyday analogy the first time, and only use terms the profile says they already understand. "
                    "Teach ONE small idea at a time in two to four short sentences, point at something real on their chart (use draw_on_chart when a picture helps, then describe what you drew), and finish with one quick question that checks understanding. "
                    "Whenever they show they understood a concept, struggle with one, or you move on to a new topic, call update_trading_learner_profile, so their knowledge level grows over time and future lessons build on it. Raise the level gradually. "
                    "You can see their drawings in get_trading_lab_context; comment on them kindly and correct misunderstandings. "
                    "DRAWING HONESTY: to draw you MUST call draw_on_chart; saying you drew is not drawing. Only say something is on their chart after draw_on_chart returns visible=true. If it returns visible=false or an error, tell them plainly that the drawing did not appear. Your drawings are violet; the yellow/gold line is the EMA 20 indicator, never yours. "
                    "Never promise profits or give personal financial advice; it is paper trading practice. Respect analysis_locked. The tool already knows which chart the user is on; never ask which session they mean. Answer each question once. "
                    "MISSION ROUTING: When the user asks to start a mission, retain that intent "
                    "while asking for its goal. Once they supply the goal, call start_mission "
                    "with all constraints, even if the goal concerns web research. Do not substitute "
                    "browser_task or dispatch_agent for an explicitly requested mission. "
                    "A request to compare current products, prices and recommendations needs "
                    "research and verification; use start_mission for that multi-step goal. "
                    "Only say a mission started after start_mission returns its id. "
                    "When a research method fails, use available search/fetch alternatives within "
                    "the authorized read-only task instead of asking permission to keep researching."
                    + ("\n\n" + self._tool_index_prompt if self._tool_index_prompt else ""))]
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=start_map.get(
                        str(vad_cfg.get("start_sensitivity", "HIGH")).upper(),
                        types.StartSensitivity.START_SENSITIVITY_HIGH,
                    ),
                    end_of_speech_sensitivity=end_map.get(
                        str(vad_cfg.get("end_sensitivity", "HIGH")).upper(),
                        types.EndSensitivity.END_SENSITIVITY_HIGH,
                    ),
                    prefix_padding_ms=int(vad_cfg.get("prefix_padding_ms", 120)),
                    silence_duration_ms=int(vad_cfg.get("silence_duration_ms", 500)),
                )
            ),
            # Static tools (the original 23) + dynamically registered superpowers
            # (news, screen, sub-agents, MCP servers, self-written skills, …).
            tools=[types.Tool(function_declarations=declarations)],
            # ── Session continuity ──────────────────────────────────────────
            # Ask the server to keep a resumable snapshot of the conversation
            # and hand us back a token for it. Passing that token on the next
            # connect restores the whole context (what we were studying, what
            # she just said, the screenshots she's seen), instead of waking up
            # blank and asking "what were we talking about?".
            session_resumption=types.SessionResumptionConfig(
                handle=self.resume_handle
            ),
            # Sliding-window compression lifts the hard session-duration limit:
            # once the context passes trigger_tokens the server compresses the
            # oldest turns rather than terminating the session. Without this the
            # connection is force-closed after ~10-15 minutes, which is exactly
            # the 1008 GoAway abort Freya kept dying on.
            #
            # `target_tokens` is set EXPLICITLY. Left unset the server assumes
            # trigger/2, and that silent default is what shredded the
            # conversation — see _compression_budget() for the full story.
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=trigger_tokens,
                sliding_window=types.SlidingWindow(target_tokens=target_tokens),
            ),
        )

    # Add these to FreyaModel class — override in subclass for UI broadcasting
    async def on_transcript(self, speaker_name: str, text: str):
        pass  # overridden in server.py

    async def on_tool(self, name: str, args: dict, result: str):
        pass  # overridden in server.py

    async def on_state(self, value: str):
        pass  # overridden in server.py

    async def _set_state(self, value: str):
        # The desktop activity pill follows her state too; server.py's
        # on_state override only reaches the dashboard.
        activity_ui.set_state(value)
        await self.on_state(value)

    async def on_event(self, event_type: str, payload: dict):
        pass  # overridden in server.py — generic events (agent/mcp/schedule/ambient)

    async def _inject_text(self, text: str):
        """Proactive speech: feed a turn into the live session so Freya speaks it.
        Used by the scheduler, ambient watcher, missions, gesture touches and
        finished sub-agents.

        Serialized and turn-gated. Every one of those callers fires
        independently and none of them know what the others are doing, so
        previously two could push turns in simultaneously (interleaved speech),
        or one could land while Freya was mid-sentence — the model would finish
        her current turn and then answer the injected one, which reads as her
        replying to a question that was never asked.

        Now injects queue behind one another and wait for her to stop talking,
        so each proactive line lands in a natural gap. The wait is capped: after
        WAIT_LIMIT seconds we send anyway rather than silently dropping the
        message, since a late reaction beats none at all.
        """
        if not self.session:
            return

        WAIT_LIMIT = 20.0
        POLL = 0.1
        # A conversational gap, not merely silence. Waiting only for
        # `model_speaking` to clear was not enough: the pause between the user
        # finishing a question and Freya starting her answer reads as silence,
        # so an injection could land in that gap and take the turn — which is
        # exactly how "explain this note" got answered with "welcome back from
        # your movie break". The question was never answered at all.
        GAP_S = 6.0

        async with self._inject_lock:
            speaking = self._model_speaking
            waited = 0.0
            while waited < WAIT_LIMIT:
                busy = (speaking is not None and speaking.is_set()) or not self._interaction.idle or self._pending_tools > 0
                mid_exchange = runtime.seconds_since_activity() < GAP_S
                if not busy and not mid_exchange:
                    break
                await asyncio.sleep(POLL)
                waited += POLL

            # Never interrupt extended background work merely because its spoken
            # filler finished. Let the scheduler try again at the next natural gap.
            if not self._interaction.idle or self._pending_tools:
                return
            if not self.session:  # session may have closed while we waited
                return
            try:
                await self.session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[types.Part(text=(
                            "[PROACTIVE — say this to the user out loud now, naturally, in your own "
                            "voice and style. It is an aside: if you were in the middle of "
                            "something with him, deal with this in one sentence and then go "
                            "straight back to what you were both doing. Never treat it as a "
                            "reason to greet him again or change the subject]: " + text
                        ))],
                    ),
                    turn_complete=True,
                )
            except Exception as e:
                print(f"  inject failed: {e}")

    async def _send_recap(self):
        """Re-seed a fresh session with what we were just doing.

        Session resumption normally carries the context for us, but a handle can
        be missing (first failure of a run) or rejected by the server (expired,
        or taken mid-generation when `resumable` was false). In that case the new
        socket starts blank — which is what made Freya reconnect and say she had
        no idea what we were talking about. So when we reconnect WITHOUT a handle
        and there is a transcript, we replay its tail as context. turn_complete
        =False means this only loads context; it does not make her start talking.
        """
        if self.resume_handle or not self.transcript:
            return
        lines = self.transcript.get()
        if not lines:
            return
        tail = lines[-40:]
        try:
            await self.session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=(
                        "[SESSION CONTINUITY — connection or mode changed. This is the "
                        "transcript of the conversation you and the user were having moments ago. "
                        "Treat it as your own memory of the last few minutes and simply carry "
                        "on from where you left off. Do NOT announce the reconnection, do NOT "
                        "ask him to repeat himself or re-share his screen, and do NOT greet him "
                        "again — just continue naturally.]\n\n" + "\n".join(tail)
                    ))],
                ),
                turn_complete=self.continue_task,
            )
            print(f"  Context restored from transcript ({len(tail)} lines).")
        except Exception as e:
            print(f"  Recap failed: {e}")

    async def run(self, mic_stream, speaker_stream):
        print(f"\nConnecting to {self.model_id}...")

        audio_queue = asyncio.Queue()
        model_speaking = asyncio.Event()
        # Publish it so _inject_text can hold proactive lines until she's quiet.
        self._model_speaking = model_speaking
        loop = asyncio.get_event_loop()

        # Dedicated thread pool for the blocking mic/speaker calls.
        #
        # These used to run on the DEFAULT executor — the same pool every sync
        # tool handler uses (see registry._execute). A slow tool (screen
        # capture, a file scan, a sub-agent's web fetch) would occupy those
        # worker threads, and the next mic read or speaker write would sit in
        # the queue behind it. That is audible: Freya's voice stutters or lags
        # exactly when something else is working hard.
        #
        # Two workers, reserved for audio and nothing else, so no amount of
        # tool or agent activity can ever delay the voice path.
        audio_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="freya-audio")

        # Tracking variables for turn-completion and playback sync
        pending_playback_chunks = 0
        tool_queue = asyncio.Queue(maxsize=64)
        cancelled_calls = set()
        _bg_reports = set()  # keeps background-result injections alive
        seen_calls = set()
        # Last time the model / the user produced anything (speech, a call,
        # transcription). The stall watchdog compares these to when a tool
        # result was sent.
        activity = {"model": time.monotonic(), "user": time.monotonic()}
        # Real tool calls since she last said anything. 3.8 Live waits on each
        # call, so a long search was a long silence: 35 calls, nothing spoken.
        silent_calls = {"n": 0}
        # What the current model turn has produced, for spotting empty turns:
        # Gemini Live sometimes closes a turn with no audio, no words and no
        # call — after the user spoke, or after a tool result — and she then
        # sat mute until spoken to again.
        turn = {"output": False, "user_text": "", "after_tool": False, "nudged": False,
                "spoken_fix": False}
        # One job at a time: the tool running in the background right now (None
        # when idle), and calls that arrived meanwhile — answered "queued" at
        # once so she keeps talking, then run in order when the job finishes.
        busy = {"name": None}
        deferred_ids = set()
        report_lock = asyncio.Lock()
        stall_nudge_s = float((self.config or {}).get("live", {}).get("stall_nudge_s", 8))
        # live.trace: print every non-audio server frame (diagnostics only).
        trace_frames = bool((self.config or {}).get("live", {}).get("trace", False))
        # Jev mode routing: only from the default mode, and only when automatic
        # escalation is allowed at all (live.auto_complex_mode).
        from core import systemone
        cfg = self.config or {}
        route_queue = asyncio.Queue() if (
            systemone.enabled(cfg, "mode_routing")
            and cfg.get("live", {}).get("auto_complex_mode", True)
            and cfg.get("active_mode", "default") == "default"
        ) else None

        # Connect any configured MCP servers BEFORE building the tool list so
        # their tools are advertised to Gemini in this session.
        try:
            from core.mcp_client import mcp_manager
            await mcp_manager.start(self.config)
        except Exception as e:
            print(f"  MCP manager unavailable: {e}")

        live_config = self.get_config()

        async with self.client.aio.live.connect(
            model=self.model_id,
            config=live_config
        ) as session:
            self.session = session
            self.connected = True
            # Publish this session's channels so background powers can reach it.
            runtime.set_channels(self._inject_text, self.on_event)
            # Publish the conversation record too, so `recall_conversation` can
            # reach it when the server-side context has dropped something.
            runtime.set_transcript(self.transcript)
            # Kick off scheduler + ambient loops bound to this session.
            try:
                from core.scheduler import scheduler
                scheduler.attach(self.config)
            except Exception:
                pass
            try:
                from core.context_watch import tracker
                tracker.attach(self.config)
            except Exception:
                pass
            try:
                from core.day_context import rotator
                rotator.attach(self.config)
            except Exception as e:
                print(f"  Day context unavailable: {e}")
            try:
                from core.hotkeys import start_pause_hotkey
                start_pause_hotkey(self.config)
            except Exception:
                pass
            if self.resume_handle:
                print("  Resuming previous conversation state.")
            else:
                await self._send_recap()
            print("Freya is live! Start talking. (Ctrl+C to stop)\n")

            freya_cfg = (self.config or {}).get("freya", {})
            vad_cfg = (self.config or {}).get("vad", {})
            barge_in = freya_cfg.get("barge_in", True)
            rms_threshold = int(vad_cfg.get("barge_in_rms_threshold", 1200))
            from core.echo_gate import EchoGate
            echo_gate = EchoGate(enabled=freya_cfg.get("speaker_echo_protection", True))
            # Turn-taking (core/turn_taking.py). On speakers the echo gate mutes
            # the mic while she talks, so she could never be interrupted; the
            # double-talk detector opens it when the user is clearly talking
            # over her. Headphones (gate off) keep the plain RMS barge-in.
            tt_cfg = (self.config or {}).get("turn_taking", {})
            detector = None
            if barge_in and echo_gate.enabled and tt_cfg.get("smart_barge_in", True):
                # Kept across reconnects so her learned echo level survives.
                if getattr(self, "_double_talk", None) is None:
                    self._double_talk = DoubleTalkDetector(
                        min_rms=int(tt_cfg.get("min_rms", 500)),
                        margin=float(tt_cfg.get("echo_margin", 2.5)),
                        min_ms=int(tt_cfg.get("min_speech_ms", 200)),
                    )
                detector = self._double_talk
                detector.reset_run()
            turns = TurnTaker(detector, confirm_s=float(tt_cfg.get("confirm_s", 1.5)))
            interruption_notes = tt_cfg.get("interruption_note", True)
            # Cleared while playback is held for a possible barge-in.
            playable = asyncio.Event()
            playable.set()
            from collections import deque

            def _rms(chunk: bytes) -> int:
                """Energy of a 16-bit PCM chunk — used to gate barge-in."""
                try:
                    import audioop
                    return audioop.rms(chunk, 2)
                except Exception:
                    import array
                    samples = array.array("h", chunk[: len(chunk) // 2 * 2])
                    if not samples:
                        return 0
                    return int((sum(s * s for s in samples) / len(samples)) ** 0.5)

            async def begin_hold():
                turns.hold()
                playable.clear()
                cut = getattr(speaker_stream, "cut", None)
                if cut:
                    cut()
                print("  \u270b Heard you over her voice; pausing her.")
                await self._set_state("listening")

            async def send_audio():
                last_paused = False
                # The last ~0.4 s of mic audio, so a barge-in sends the start of
                # the user's words that arrived while the mic was still gated.
                preroll = deque(maxlen=6)
                while True:
                    # Reject a chunk captured across the playback/listening boundary too.
                    echo_at_capture = echo_gate.blocks(model_speaking.is_set())
                    data = await loop.run_in_executor(audio_pool, mic_stream.read)
                    # Pause-listening: drain the mic but DON'T forward it, so movie /
                    # ambient audio never reaches Gemini and can't trigger her.
                    paused = runtime.is_paused()
                    if paused != last_paused:
                        last_paused = paused
                        print("  🔇 Mic paused." if paused else "  🔊 Mic resumed.")
                        if paused:
                            # The Live API needs audioStreamEnd whenever the mic
                            # stream stops for more than ~1 s. Without it the
                            # server's voice-activity detector is left mid-stream,
                            # and after Resume it stopped noticing when the user
                            # finished talking: turns piled up unanswered.
                            try:
                                await session.send_realtime_input(audio_stream_end=True)
                            except Exception as exc:
                                print(f"  [mic] audio_stream_end failed: {exc}")
                        await runtime.emit("mic", {"paused": paused})
                    if paused:
                        preroll.clear()
                        continue
                    if turns.hold_expired():
                        # Nothing confirmed it: that was her own voice. Carry on.
                        turns.release()
                        print("  \u270b False alarm; she carries on.")
                        playable.set()
                        await self._set_state("speaking")
                    if turns.user_has_floor:
                        await session.send_realtime_input(
                            audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                        )
                        continue
                    if detector is not None and data:
                        preroll.append(data)
                        fired = detector.frame(_rms(data), time.monotonic())
                        if fired and model_speaking.is_set():
                            await begin_hold()
                            for chunk in preroll:
                                await session.send_realtime_input(
                                    audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                                )
                            preroll.clear()
                            continue
                        if fired:
                            detector.reset_run()
                    if echo_at_capture or echo_gate.blocks(model_speaking.is_set()):
                        continue
                    if model_speaking.is_set():
                        # Headphone opt-in only: energy cannot distinguish voice from echo.
                        if not barge_in or _rms(data) < rms_threshold:
                            continue
                    await session.send_realtime_input(
                        audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                    )

            async def watch_for_stall(sent_at: float):
                # Gemini Live sometimes ends its turn silently after a lookup-
                # only step (search_tools → schema) instead of making the next
                # call: she then sat mute mid-task until the user spoke again.
                # One nudge per tool result, so this can never loop.
                wait = stall_nudge_s * (3 if self._interaction.extended else 1)
                await asyncio.sleep(wait)
                if activity["model"] > sent_at or activity["user"] > sent_at:
                    return
                if self._pending_tools or runtime.is_paused() or model_speaking.is_set():
                    return
                if turn["nudged"]:
                    return      # the empty-turn check already nudged this silence
                turn["nudged"] = True
                print(f"  [live] model went quiet {wait:.0f}s after a tool result; nudging it on.")
                try:
                    await session.send_client_content(
                        turns=types.Content(role="user", parts=[types.Part(text=(
                            "[SYSTEM NOTE: you received the tool result above and then stopped. "
                            "Carry on with the user's request now: make the next tool call you "
                            "need, or tell the user the outcome. Do not mention this note.]"))]),
                        turn_complete=True,
                    )
                except Exception as exc:
                    print(f"  [live] stall nudge failed: {exc}")

            async def nudge_empty_turn(user_text: str, after_tool: bool):
                # Give a real reply a moment to start; any new speech, call or
                # user audio in that window means the turn wasn't dead.
                marker = (activity["model"], activity["user"])
                await asyncio.sleep(1.5)
                if (activity["model"], activity["user"]) != marker:
                    return
                if self._pending_tools or runtime.is_paused() or model_speaking.is_set():
                    return
                turn["nudged"] = True
                if user_text:
                    note = (f'[SYSTEM NOTE: the user just said: "{user_text[:500]}" and your turn '
                            "ended with no reply. Respond to it now, making any tool calls it "
                            "needs. Do not mention this note.]")
                else:
                    note = ("[SYSTEM NOTE: your turn ended right after a tool result with no reply. "
                            "Carry on with the user's request: make the next call or tell him the "
                            "outcome. Do not mention this note.]")
                print("  [live] empty model turn; nudging it to respond.")
                try:
                    await session.send_client_content(
                        turns=types.Content(role="user", parts=[types.Part(text=note)]),
                        turn_complete=True,
                    )
                except Exception as exc:
                    print(f"  [live] empty-turn nudge failed: {exc}")

            async def report_finished(tool_name, tool_args, call_id, result, how):
                """A background or queued job is done: log it and tell her to carry
                on. 'Carry on', not just 'report': the old note only asked for
                the outcome, so find-then-open chains stopped after the find."""
                print(f"  Result ({how}): {result}")
                if self.transcript:
                    self.transcript.add("Tool", f"{tool_name}: {str(result)[:1600]}")
                await self.on_tool(tool_name, tool_args, str(result))
                if call_id in cancelled_calls:
                    return
                label = activity_ui.describe(tool_name, tool_args) or tool_name
                note = (f"[Task finished ({label}). Result: {str(result)[:1600]}. Carry on with what the "
                        "user asked: if it needs another step, say in one short sentence what you'll do "
                        "next and do it now; otherwise tell him the outcome briefly.]")

                async def deliver():
                    # Not runtime.inject: that waits for zero pending tools and
                    # DROPS the line after 20 s — with a queued job running, the
                    # result of the one before it was silently lost. Wait only
                    # for her to finish speaking and him to pause, then send.
                    # The lock (FIFO) keeps results in the order jobs finished.
                    async with report_lock:
                        for _ in range(240):                   # ≤ 60 s
                            user_pausing = time.monotonic() - activity["user"] > 1.2
                            if not model_speaking.is_set() and user_pausing:
                                break
                            await asyncio.sleep(0.25)
                        try:
                            await session.send_client_content(
                                turns=types.Content(role="user", parts=[types.Part(text=note)]),
                                turn_complete=True)
                        except Exception as exc:
                            print(f"  [live] could not deliver task result: {exc}")

                # Not awaited, so the next queued job starts right away.
                _bg_reports.add(t := asyncio.create_task(deliver()))
                t.add_done_callback(_bg_reports.discard)

            async def answer_while_busy(fc, queued: bool):
                """A call that arrived while another job is running. Instant,
                read-only calls run now; real work is acknowledged as queued so
                she can keep talking, and runs when the current job is done."""
                name = getattr(fc, "name", "")
                args = dict(fc.args) if getattr(fc, "args", None) else {}
                try:
                    if not queued:
                        result = await settle(registry_dispatch(name, args, ToolContext(self.config, session=session)),
                                              name, args)
                    else:
                        result = (f"Queued: this starts automatically as soon as the current task "
                                  f"({busy['name']}) finishes — one job at a time. Tell the user in one "
                                  "short sentence that it's next, and keep chatting. Don't call it again.")
                        print(f"  Tool queued behind {busy['name']}: {name}({args})")
                    await session.send_tool_response(function_responses=[types.FunctionResponse(
                        id=fc.id, name=name, response={"result": result})])
                except Exception as exc:
                    print(f"  [live] answering a call during a busy job failed: {exc}")
                finally:
                    if not queued:          # a queued call is counted down by the executor
                        self._pending_tools -= 1

            tool_timeout_s = float(cfg.get("live", {}).get("tool_timeout_s", 300))

            async def settle(job, tool_name, tool_args, call_id=None):
                """Await a tool job under the recovery protocol: bounded by
                `live.tool_timeout_s`, recorded in the circuit breaker, and any
                failure turned into a result she can talk about. A hung tool
                used to hold the one-job executor forever, and every call after
                it queued behind a job that would never finish."""
                key = _effective_tool(tool_name, tool_args)
                try:
                    result = await asyncio.wait_for(job, tool_timeout_s)
                except asyncio.CancelledError:
                    raise
                except ModeChange:
                    raise
                except (asyncio.TimeoutError, TimeoutError):
                    tripped = breaker.failure(key)
                    print(f"  Tool TIMEOUT: {key} after {tool_timeout_s:.0f}s")
                    activity_ui.tool_outcome(call_id, "timeout", f"stopped after {tool_timeout_s:.0f}s")
                    if tripped:
                        health.set("tools", DEGRADED, f"{key} is resting after repeated failures")
                    return (f"Tool {key} took longer than {tool_timeout_s:.0f}s and was stopped. "
                            "Tell the user plainly it timed out, then try a lighter way to reach the "
                            "same goal (a narrower search, a different tool) instead of repeating it.")
                except Exception as exc:
                    from core.errors import log_error
                    log_error(f"live.tool.{key}", exc)
                    print(f"  Tool FAILED: {key}: {type(exc).__name__}: {exc}")
                    activity_ui.tool_outcome(call_id, "error", f"{type(exc).__name__}: {exc}")
                    if breaker.failure(key):
                        health.set("tools", DEGRADED, f"{key} is resting after repeated failures")
                    return (f"Tool {key} failed: {type(exc).__name__}: {exc}. Tell the user plainly "
                            "what failed and why; do not retry blindly — try another route if there is one.")
                breaker.success(key)
                # The tool ran but answered with bad news: not the breaker's
                # business (the tool works), but the dashboard shows it as failed.
                if isinstance(result, str) and result.lstrip().lower().startswith(("error", "failed")):
                    activity_ui.tool_outcome(call_id, "error", result.strip()[:160])
                if health.get("tools").state != OK and not breaker.open_tools():
                    health.ok("tools")
                return result

            async def execute_tools():
                # One executor preserves desktop action order while the receiver
                # continues streaming fillers, audio, cancellation and status.
                while True:
                    fc = await tool_queue.get()
                    try:
                        if fc.id in cancelled_calls:
                            continue
                        tool_name = fc.name
                        tool_args = dict(fc.args) if fc.args else {}
                        call_id = fc.id
                        print(f"  Tool : {tool_name}({tool_args})")
                        activity_ui.tool_started(call_id, tool_name, tool_args)
                        ctx = ToolContext(self.config, session=session)
                        effective = _effective_tool(tool_name, tool_args)
                        if breaker.is_open(effective):
                            # Recovery protocol, step 2: a tool that keeps failing
                            # rests instead of costing another full timeout.
                            resting = breaker.resting_message(effective)
                            print(f"  Tool resting: {effective}")
                            activity_ui.tool_outcome(call_id, "resting", "failed repeatedly; resting")
                            if call_id in deferred_ids:
                                deferred_ids.discard(call_id)
                                await report_finished(tool_name, tool_args, call_id, resting, "queued")
                            else:
                                await session.send_tool_response(function_responses=[types.FunctionResponse(
                                    id=call_id, name=tool_name, response={"result": resting})])
                                await self.on_tool(tool_name, tool_args, resting)
                            continue
                        if call_id in deferred_ids:
                            # Already answered "queued"; its turn has come. Run it
                            # to completion and report through the task-finished note.
                            deferred_ids.discard(call_id)
                            busy["name"] = tool_name
                            try:
                                result = await settle(registry_dispatch(tool_name, tool_args, ctx),
                                                      tool_name, tool_args, call_id)
                            finally:
                                busy["name"] = None
                            await report_finished(tool_name, tool_args, call_id, result, "queued")
                            continue
                        # The 3.8 Live model declares tools BLOCKING: it stays
                        # silent until the function response arrives, so a
                        # long tool (running a script, a big file operation)
                        # left her mute for its whole duration. A tool still
                        # running after SLOW_TOOL_SECONDS is answered with a
                        # "running in background" response so she can keep
                        # talking; the real result is injected when it lands.
                        # The executor still awaits it before the next call,
                        # so desktop actions keep their order.
                        job = asyncio.create_task(registry_dispatch(tool_name, tool_args, ctx))
                        try:
                            await asyncio.wait({job}, timeout=SLOW_TOOL_SECONDS)
                            if not job.done() and _effective_tool(tool_name, tool_args) not in FOREGROUND_TOOLS:
                                await session.send_tool_response(
                                    function_responses=[types.FunctionResponse(
                                        id=call_id,
                                        name=tool_name,
                                        response={"result": (
                                            f"{tool_name} is still running. If you haven't yet, tell "
                                            "the user in one short sentence what you're doing, then keep "
                                            "chatting normally. Don't start any other action until it "
                                            "finishes — anything new he asks for will queue and run right "
                                            "after. You'll get the result as soon as it lands; don't claim "
                                            "an outcome yet."
                                        )},
                                    )]
                                )
                                await self.on_tool(tool_name, tool_args, "Running in background…")
                                activity_ui.tool_mode(call_id, "background")
                                busy["name"] = tool_name
                                try:
                                    result = await settle(job, tool_name, tool_args, call_id)
                                finally:
                                    busy["name"] = None
                                await report_finished(tool_name, tool_args, call_id, result, "background")
                                continue
                            result = await settle(job, tool_name, tool_args, call_id)
                        finally:
                            if not job.done():
                                job.cancel()
                        print(f"  Result: {result}")

                        if call_id in cancelled_calls:
                            continue
                        if self.transcript:
                            self.transcript.add("Tool", f"{tool_name}: {str(result)[:1600]}")

                        # ── VISION: send screenshot to Gemini as image ──
                        if result == "VISION_REQUESTED":
                            from core.vision import capture_screen, get_capture_grid
                            import base64
                            print("  Capturing screen...")
                            b64_image = await loop.run_in_executor(None, capture_screen)
                            gw, gh = get_capture_grid()

                            # Show the screenshot she's looking at on the dashboard canvas.
                            try:
                                await runtime.emit("image", {"data": b64_image, "label": "Screen capture"})
                            except Exception:
                                pass

                            # Send the screenshot through send_client_content, NOT
                            # send_realtime_input. Realtime input is the latency-
                            # optimized STREAMING channel (webcam/screen feeds): the
                            # Live API samples frames from it on its own cadence, so a
                            # one-shot image sent there can be ingested late — or
                            # dropped — relative to the conversation stream. The model
                            # then answered from the tool-response text alone (a
                            # hallucinated guess) and only saw the real pixels a turn
                            # later. Client content is appended to the conversation
                            # context deterministically and in order; turn_complete=
                            # False adds the image WITHOUT triggering generation, so
                            # the tool response that follows lands after it — with the
                            # image guaranteed already in context.
                            #
                            # The turn is then closed explicitly below. It has to be:
                            # per the SDK, turn_complete=False means "the model will
                            # wait for you to send additional client_content, and will
                            # not return until you send turn_complete=True". A tool
                            # response does NOT close a client-content turn, so she sat
                            # silent after taking the screenshot and only answered once
                            # the user spoke again and that utterance closed the turn.
                            await session.send_client_content(
                                turns=types.Content(
                                    role="user",
                                    parts=[
                                        types.Part(text=(
                                            f"[SCREEN CAPTURE — {gw}x{gh} screenshot of the user's "
                                            "REAL screen, taken this instant]"
                                        )),
                                        types.Part(inline_data=types.Blob(
                                            data=base64.b64decode(b64_image),
                                            mime_type="image/jpeg",
                                        )),
                                    ],
                                ),
                                turn_complete=False,
                            )
                            await session.send_tool_response(
                                function_responses=[types.FunctionResponse(
                                    id=call_id,
                                    name=tool_name,
                                    response={"result": (
                                        "Screen captured. The screenshot of the user's REAL current "
                                        "screen is already in your context (the image right above "
                                        "this). Describe and interact based STRICTLY on that image "
                                        "- never guess or imagine screen content. All click/move/"
                                        "scroll coordinates must be measured on this exact image."
                                    )}
                                )]
                            )
                            # Close the turn opened above. Without this she never
                            # replies to "look at my screen" — she just waits.
                            await session.send_client_content(turn_complete=True)
                            print("  Screen sent to Gemini (client_content).")
                        else:
                            sent = result
                            # Body-language tools are silent by design; don't count them.
                            if not str(result).startswith("[SILENT"):
                                silent_calls["n"] += 1
                                if silent_calls["n"] % 4 == 0:
                                    sent = (f"{result}\n[NOTE: that's {silent_calls['n']} tool calls "
                                            "without a word to the user. Before your next call, tell "
                                            "him in one short sentence what you're doing or what "
                                            "you've found so far.]")
                            await session.send_tool_response(
                                function_responses=[types.FunctionResponse(
                                    id=call_id,
                                    name=tool_name,
                                    response={"result": sent}
                                )]
                            )
                        # The model's continuation after this result is a new
                        # stretch of the turn: judge it on its own output.
                        turn["output"] = False
                        turn["after_tool"] = True
                        await self.on_tool(tool_name, tool_args, result)
                        _bg_reports.add(w := asyncio.create_task(watch_for_stall(time.monotonic())))
                        w.add_done_callback(_bg_reports.discard)
                        if tool_name == "switch_mode" and result.startswith("MODE_SWITCHED:"):
                            await audio_queue.join()
                            raise ModeChange(result.split(":", 1)[1])
                    except ModeChange:
                        raise
                    except Exception as exc:
                        # A tool failure is the model's problem to report, not a
                        # reason to tear down the voice session. Before this,
                        # anything `dispatch` RAISED (a disabled tool, a broken
                        # approval policy) escaped this coroutine, killed the
                        # task group and reconnected — while the model, which
                        # never got a function response, just said something had
                        # gone wrong. Answer the call with the real error instead.
                        from core.errors import log_error
                        log_error(f"live.tool.{getattr(fc, 'name', '?')}", exc)
                        activity_ui.tool_outcome(getattr(fc, "id", None), "error", f"{type(exc).__name__}: {exc}")
                        print(f"  Tool FAILED: {getattr(fc, 'name', '?')}: "
                              f"{type(exc).__name__}: {exc}")
                        try:
                            await session.send_tool_response(
                                function_responses=[types.FunctionResponse(
                                    id=getattr(fc, "id", None),
                                    name=getattr(fc, "name", None),
                                    response={"result": (
                                        f"Tool {getattr(fc, 'name', '?')} failed: "
                                        f"{type(exc).__name__}: {exc}. Tell the user plainly "
                                        f"what failed and why; do not retry blindly."
                                    )},
                                )]
                            )
                        except Exception as send_exc:
                            log_error("live.tool.send_error_response", send_exc)
                    finally:
                        activity_ui.tool_finished(getattr(fc, "id", None), getattr(fc, "name", ""))
                        self._pending_tools -= 1
                        tool_queue.task_done()

            async def receive_audio():
                nonlocal pending_playback_chunks
                freya_buffer = ""
                user_buffer = ""
                thinking_failed = False

                def queue_call(fc):
                    """Queue one function call, deduped by id.

                    Called from BOTH delivery channels. `response.tool_call` is
                    the classic one; 3.8 Live (thinking) can also deliver a call
                    as a `function_call` PART of the model turn, and those parts
                    used to be dropped on the floor — the loop below only ever
                    looked at `inline_data`. A dropped call never reached
                    `execute_tools`, so nothing was logged, no function response
                    was ever sent, and the model (non-blocking, so it does not
                    wait) reported that something had failed.
                    """
                    if fc is None or not getattr(fc, "name", None):
                        return
                    fc_id = getattr(fc, "id", None)
                    if fc_id and fc_id in seen_calls:
                        return
                    if fc_id:
                        seen_calls.add(fc_id)
                    turn["output"] = True
                    activity_ui.responding()
                    turn["nudged"] = False
                    turn["spoken_fix"] = False
                    self._pending_tools += 1
                    if busy["name"] and getattr(fc, "id", None):
                        # A job is running: answer now (instant tools run, work is
                        # queued) so she isn't frozen until it completes.
                        args = dict(fc.args) if getattr(fc, "args", None) else {}
                        queued = _effective_tool(fc.name, args) not in INSTANT_TOOLS
                        if queued:
                            deferred_ids.add(fc.id)
                            tool_queue.put_nowait(fc)
                        _bg_reports.add(a := asyncio.create_task(answer_while_busy(fc, queued)))
                        a.add_done_callback(_bg_reports.discard)
                        return
                    tool_queue.put_nowait(fc)

                async def flush_user():
                    # Emit the user's words as ONE complete utterance instead
                    # of fragment-by-fragment transcript lines.
                    nonlocal user_buffer
                    full = user_buffer.strip()
                    user_buffer = ""
                    if full:
                        turn["user_text"] = full
                        turn["spoken_fix"] = False
                        print(f"  You  : {full}")
                        # Speech is presence. Without this the context tracker
                        # reads a long spoken session as an empty chair.
                        runtime.note_user_turn()
                        if self.transcript:
                            self.transcript.add("User", full)
                        self._note_day_turn(full)
                        await self.on_transcript("User", full)
                        if route_queue is not None:
                            route_queue.put_nowait(full)

                async def flush_freya(cut: bool = False, heard: float = None):
                    nonlocal freya_buffer, thinking_failed
                    full, spoken_calls = _extract_spoken_calls(freya_buffer.strip())
                    freya_buffer = ""
                    turns.segment_start = turns.received
                    if heard is not None:
                        # Keep only what was actually played before the cut.
                        full = trim_to_fraction(full, heard)
                    said = full
                    if spoken_calls:
                        # She read a body-language call out loud instead of
                        # making it. Show it the proper way (the avatar
                        # actually changes) and keep it out of the transcript.
                        for tool_name, tool_args in spoken_calls:
                            print(f"  Spoken tool call caught: {tool_name}({tool_args})")
                            try:
                                result = await registry_dispatch(
                                    tool_name, tool_args, ToolContext(self.config, session=session))
                                await self.on_tool(tool_name, tool_args, str(result))
                            except Exception as exc:
                                print(f"  Spoken tool call failed: {exc}")
                        try:
                            await session.send_client_content(
                                turns=types.Content(role="user", parts=[types.Part(text=(
                                    "[SYSTEM NOTE: you just said a body-language tool call out "
                                    "loud. Never speak tool names or arguments; call "
                                    "set_expression and the other avatar tools silently. "
                                    "Do not reply to this note.]"))]),
                                turn_complete=False,
                            )
                        except Exception:
                            pass
                    if full and not cut:
                        from core.registry import registered_names
                        # Registry tools plus the legacy ones declared in this file
                        # (run_terminal_command, close_app, ...).
                        known = (set(registered_names()) | {d.name for d in TOOL_DECLARATIONS}
                                 | {"run_tool", "search_tools"})
                        spoken = [n for n in _SPOKEN_ANY_CALL.findall(full)
                                  if n in known and n not in _AVATAR_TOOLS]
                        if spoken:
                            print(f"  Spoken tool call caught: {spoken[0]} ({full[:80]!r})")
                            if len(full) < 80:
                                full = ""      # nothing but call debris: keep it out of the record
                            if not turn.get("spoken_fix"):
                                turn["spoken_fix"] = True
                                try:
                                    await session.send_client_content(
                                        turns=types.Content(role="user", parts=[types.Part(text=(
                                            f"[SYSTEM NOTE: you said a {spoken[0]} call out loud "
                                            "instead of making it. Make the actual function call "
                                            "now — never speak call syntax. Do not mention this "
                                            "note.]"))]),
                                        turn_complete=True,
                                    )
                                except Exception:
                                    pass
                    if full and not cut and self._interaction.extended and is_thinking_failure(full):
                        thinking_failed = True
                    if full:
                        if cut:
                            full += " …"
                        print(f"  Freya: {full}")
                        runtime.note_model_turn()
                        if self.transcript:
                            self.transcript.add("Freya", full)
                        await self.on_transcript("Freya", full)
                    return said

                async def tell_interrupted(heard: str, cut_short: bool, marker: float):
                    """Tell her she was cut off and where, then make sure the
                    user's interruption actually gets an answer."""
                    try:
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[types.Part(
                                text=interruption_note(heard, cut_short))]),
                            turn_complete=False,
                        )
                    except Exception as exc:
                        print(f"  [turns] interruption note failed: {exc}")
                        return
                    started = time.monotonic()
                    while time.monotonic() - started < 30:
                        await asyncio.sleep(0.5)
                        if activity["model"] > marker:
                            return              # she answered
                        if time.monotonic() - activity["user"] < 2.0:
                            continue            # the user is still talking
                        if self._pending_tools or runtime.is_paused() or model_speaking.is_set():
                            continue
                        said = user_buffer.strip() or turn["user_text"]
                        if not said:
                            return
                        print("  [turns] no reply to the interruption; prompting her.")
                        try:
                            await session.send_client_content(
                                turns=types.Content(role="user", parts=[types.Part(text=(
                                    f'[SYSTEM NOTE: the user interrupted you and said: "{said[:500]}". '
                                    "Respond to it now. Do not mention this note.]"))]),
                                turn_complete=True,
                            )
                        except Exception as exc:
                            print(f"  [turns] interruption follow-up failed: {exc}")
                        return

                async def take_floor(source: str):
                    """The user cut in (confirmed by Gemini or by their words):
                    silence her, keep only what was heard, and tell her."""
                    nonlocal pending_playback_chunks
                    fraction = turns.heard_fraction()
                    running = source != "server" and not self._interaction.utterance_complete
                    if not turns.confirm(generation_running=running):
                        return
                    cut = getattr(speaker_stream, "cut", None)
                    if cut:
                        cut()
                    # Drop all queued (unplayed) audio so she stops instantly
                    while not audio_queue.empty():
                        try:
                            audio_queue.get_nowait()
                            audio_queue.task_done()
                        except asyncio.QueueEmpty:
                            break
                    # Keep what she managed to say, marked as cut off
                    heard = await flush_freya(cut=True, heard=fraction) or ""
                    turns.played = turns.received  # the dropped audio will never play
                    turns.segment_start = turns.received
                    pending_playback_chunks = 0
                    model_speaking.clear()
                    playable.set()
                    await self._set_state("interrupted")
                    print(f"  \u270b Interrupted ({source}) after {fraction:.0%} of her line.")
                    if interruption_notes:
                        _bg_reports.add(t := asyncio.create_task(
                            tell_interrupted(heard, fraction < 0.98, activity["model"])))
                        t.add_done_callback(_bg_reports.discard)

                while True:
                    async for response in session.receive():
                        if trace_frames:
                            _trace_frame(response)
                        # ── Keep the resumption token fresh ──
                        # The server emits a new handle throughout the session.
                        # Stashing the latest one means a reconnect (planned or
                        # not) resumes the real conversation rather than
                        # starting from nothing.
                        sru = getattr(response, "session_resumption_update", None)
                        if sru is not None:
                            if getattr(sru, "resumable", False) and getattr(sru, "new_handle", None):
                                self.resume_handle = sru.new_handle

                        # ── GoAway: the socket is about to be closed by Google ──
                        # Leave voluntarily and immediately. Staying is what
                        # earned the 1008 abort mid-sentence.
                        goaway = getattr(response, "go_away", None)
                        if goaway is not None:
                            left = getattr(goaway, "time_left", None)
                            print(f"  ↻ Session rotating (time left: {left}). Reconnecting seamlessly...")
                            await flush_user()
                            await flush_freya(cut=True)
                            raise SessionRotation(str(left))

                        self._interaction.update(response)
                        cancellation = getattr(response, "tool_call_cancellation", None)
                        if cancellation:
                            cancelled_calls.update(cancellation.ids or [])
                        if response.tool_call is not None:
                            activity["model"] = time.monotonic()
                            await flush_user()
                            await flush_freya()
                            for fc in response.tool_call.function_calls:
                                queue_call(fc)
                        if pending_playback_chunks == 0 and self._interaction.utterance_complete:
                            model_speaking.clear()
                            await self._set_state(self._interaction.state_after_playback())
                        if response.server_content is None:
                            continue

                        sc = response.server_content

                        # ── BARGE-IN: user interrupted Freya mid-sentence ──
                        if getattr(sc, 'interrupted', False):
                            if turns.state == TurnTaker.CONFIRMED:
                                turns.stale = False  # the old generation has stopped
                            else:
                                await take_floor("server")
                            continue

                        # The rest of a reply the user already cut off: never play it.
                        if turns.stale and getattr(sc, 'turn_complete', False):
                            turns.stale = False
                            turn.update(output=False, user_text="", after_tool=False)
                            continue

                        # Accumulate input transcription fragments silently
                        inp = getattr(sc, 'input_transcription', None)
                        if inp:
                            text = getattr(inp, 'text', str(inp)).strip()
                            if text:
                                activity_ui.heard()
                                activity["user"] = time.monotonic()
                                user_buffer += " " + text
                                if turns.state == TurnTaker.HOLD:
                                    await take_floor("words")

                        # Buffer Freya's words — don't emit yet
                        out = getattr(sc, 'output_transcription', None)
                        if out and not turns.stale:
                            text = _clean_speech(getattr(out, 'text', str(out)) or "")
                            if text:
                                activity["model"] = time.monotonic()
                                silent_calls["n"] = 0
                                turn["output"] = True
                                activity_ui.responding()
                                turn["nudged"] = False
                                # Model started answering → the user's turn is over
                                await flush_user()
                                freya_buffer += " " + text
                                # Stream the fragment live so the UI can type it out
                                # in the center of the scene as she speaks. A
                                # whole spoken tool call in one fragment is
                                # dropped from the caption; flush_freya handles
                                # the rest.
                                caption, _ = _extract_spoken_calls(text)
                                if caption:
                                    await runtime.emit("speech", {"text": caption})

                        if sc.model_turn is not None:
                            if not turns.stale:
                                activity["model"] = time.monotonic()
                            for part in sc.model_turn.parts:
                                part_call = getattr(part, "function_call", None)
                                if part_call is not None:
                                    await flush_user()
                                    await flush_freya()
                                    queue_call(part_call)
                                if part.inline_data is not None:
                                    if turns.stale:
                                        continue
                                    if turns.state == TurnTaker.CONFIRMED:
                                        turns.reply_started()  # her answer to the interruption
                                    turn["output"] = True
                                    activity_ui.responding()
                                    turn["nudged"] = False
                                    if not model_speaking.is_set():
                                        model_speaking.set()
                                        await self._set_state("speaking")
                                    pending_playback_chunks += 1
                                    turns.received += len(part.inline_data.data)
                                    await audio_queue.put((turns.epoch, part.inline_data.data))

                        if getattr(sc, 'turn_complete', False):
                            await flush_user()
                            await flush_freya()
                            if (not turn["output"] and not turn["nudged"]
                                    and (turn["user_text"] or turn["after_tool"])):
                                _bg_reports.add(n := asyncio.create_task(
                                    nudge_empty_turn(turn["user_text"], turn["after_tool"])))
                                n.add_done_callback(_bg_reports.discard)
                            turn.update(output=False, user_text="", after_tool=False)
                            if pending_playback_chunks == 0:
                                model_speaking.clear()
                                await self._set_state(self._interaction.state_after_playback())
                            if thinking_failed and self._interaction.idle:
                                # Let the apology finish, then hand the task to
                                # the regular Live model (see ThinkingTaskFailed).
                                print("  Extended thinking dropped the task; resuming on the standard model.")
                                if self.transcript:
                                    self.transcript.add("Tool", "live: the reasoning model failed on "
                                                        "Google's side; continue the same task now")
                                await audio_queue.join()
                                raise ThinkingTaskFailed("extended thinking background task failed")

            async def route_modes():
                # The fast model is told to call switch_mode(complex_tasks) for
                # hard work, but it often answers first and escalates late or
                # never. Jev reads each finished utterance in parallel and makes
                # the switch itself when it is confident; the ModeChange path
                # (transcript recap + continue_task) carries the goal across.
                from core import systemone
                from core.tools import switch_mode
                switch_at = float(systemone.setting(self.config, "mode_routing", "switch_at", 0.85))
                while True:
                    utterance = await route_queue.get()
                    if self._pending_tools:
                        continue  # never reconnect under a running tool
                    recent = self.transcript.get()[-6:] if self.transcript else []
                    p = await systemone.noul(
                        {"recent_conversation": recent, "latest_user_turn": utterance},
                        "Does `latest_user_turn` ask for a task that needs multi-step "
                        "reasoning, difficult debugging, architecture, or comparing and "
                        "verifying research?",
                        self.config, "mode_routing",
                        criteria={"true": "Hard task that benefits from slow, careful reasoning",
                                  "false": "Casual talk, a simple command, a straightforward "
                                           "lookup, or a request to stay in the current mode"},
                    )
                    if p is None or p < switch_at:
                        continue
                    result = await loop.run_in_executor(None, switch_mode, "complex_tasks")
                    if not result.startswith("MODE_SWITCHED:"):
                        continue
                    print(f"  [jev] complex task (p={p:.2f}), switching to complex_tasks")
                    if self.transcript:
                        self.transcript.add("Tool", f"switch_mode: {result}")
                    await self.on_tool("switch_mode", {"mode": "complex_tasks", "via": "jev"}, result)
                    await audio_queue.join()  # let her finish the current word
                    raise ModeChange("complex_tasks")

            mode_requests: asyncio.Queue = asyncio.Queue()

            async def request_mode(mode: str, reason: str):
                mode_requests.put_nowait((mode, reason))

            runtime.set_mode_handler(request_mode)

            async def apply_mode_requests():
                # Mode changes asked for from outside the conversation (the
                # Trading Lab opening or closing). Same path as switch_mode:
                # wait for a natural pause, write the mode, reconnect with the
                # transcript recap — so she changes hats without losing the thread.
                from core import tools as mode_tools
                while True:
                    mode, reason = await mode_requests.get()
                    for _ in range(80):          # up to ~20 s for a gap
                        if not self._pending_tools and not model_speaking.is_set():
                            break
                        await asyncio.sleep(0.25)
                    if self._pending_tools:
                        continue                 # never reconnect under a running tool
                    result = await loop.run_in_executor(None, mode_tools.switch_mode, mode)
                    if not result.startswith("MODE_SWITCHED:"):
                        continue
                    print(f"  Mode -> {mode} ({reason or 'requested'})")
                    if self.transcript:
                        self.transcript.add("Tool", f"switch_mode: {result} ({reason})")
                    await self.on_tool("switch_mode", {"mode": mode, "via": reason or "request"}, result)
                    await audio_queue.join()
                    raise ModeChange(mode)

            async def play_audio():
                nonlocal pending_playback_chunks
                while True:
                    epoch, data = await audio_queue.get()
                    try:
                        while data:
                            await playable.wait()        # held during a possible barge-in
                            if epoch != turns.epoch:
                                break                    # cut off: never play it
                            resume = getattr(speaker_stream, "resume", None)
                            if resume:
                                resume()
                            if detector is not None and isinstance(data, (bytes, bytearray)):
                                detector.playback(_rms(data), len(data) / 48000, time.monotonic())
                            echo_gate.begin_playback()
                            turns.chunk_started(len(data))
                            rest = b""
                            try:
                                rest = await loop.run_in_executor(audio_pool, speaker_stream.write, data)
                            finally:
                                echo_gate.end_playback()
                                rest = rest if isinstance(rest, (bytes, bytearray)) else b""
                                turns.chunk_finished(len(data) - len(rest), epoch == turns.epoch)
                            # Held mid-chunk: finish it if she resumes.
                            data = rest if (rest and epoch == turns.epoch
                                            and turns.state == TurnTaker.HOLD) else b""
                    finally:
                        audio_queue.task_done()
                    if epoch != turns.epoch:
                        continue
                    pending_playback_chunks = max(0, pending_playback_chunks - 1)
                    if pending_playback_chunks == 0 and self._interaction.utterance_complete:
                        model_speaking.clear()
                        await self._set_state(self._interaction.state_after_playback())

            try:
                from core.voice_tasks import run_voice_tasks
                workers = [send_audio(), receive_audio(), play_audio(), execute_tools(),
                           apply_mode_requests()]
                if route_queue is not None:
                    workers.append(route_modes())
                await run_voice_tasks(*workers)
            finally:
                # Release the proactive channels and background loops bound to
                # this session so the next reconnect starts clean.
                self.session = None
                runtime.clear_channels()
                activity_ui.clear()     # nothing she was doing survives the session
                try:
                    from core.scheduler import scheduler
                    scheduler.detach()
                except Exception:
                    pass
                try:
                    from core.context_watch import tracker
                    tracker.detach()
                except Exception:
                    pass
                try:
                    from core.day_context import rotator
                    rotator.detach()
                except Exception:
                    pass
                try:
                    from core.ambient import ambient
                    ambient.stop_all()
                except Exception:
                    pass
                # Don't wait on the audio threads: a mic read can sit blocked in
                # PortAudio for a while, and shutdown shouldn't hang on it.
                audio_pool.shutdown(wait=False)
