from asyncio import selector_events
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from google import genai
from google.genai import types
from core.tools import dispatch
from core import runtime
from core.registry import build_declarations, dispatch as registry_dispatch, ToolContext
import base64

# ─────────────────────────────────────────────
#  TOOL DEFINITIONS  (Gemini function calling)
# ─────────────────────────────────────────────
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
        description="Switch Freya into a different operational mode, e.g. coding or language learning.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "mode": types.Schema(
                    type=types.Type.STRING,
                    description="Mode identifier: 'default', 'language_learning', 'coding', or other custom modes."
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
    types.FunctionDeclaration(
        name="open_project",
        description="Open a project folder in VS Code by project name.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "project_name": types.Schema(type=types.Type.STRING,
                    description="Project name configured in config e.g. freyav3")
            },
            required=["project_name"]
        )
    ),
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
        description="Make Freya perform a random dance animation when the user asks her to dance (e.g., 'can you dance for me', 'show me a dance', 'dance').",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={},
            required=[]
        )
    ),
    types.FunctionDeclaration(
        name="capture_screen",
        description="Capture the user's screen so you can see what's on it. Use when user says 'look at my screen', 'what do you see', 'can you see this', 'look at this'.",
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
    "1008",
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
                 resume_handle=None):
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
        self.session = None
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

        prompt_tokens = len(self.personality or "") // 4
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
        declarations = TOOL_DECLARATIONS + build_declarations(self.config)
        trigger_tokens, target_tokens = self._compression_budget(declarations)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part(text=self.personality)]
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
                busy = speaking is not None and speaking.is_set()
                mid_exchange = runtime.seconds_since_activity() < GAP_S
                if not busy and not mid_exchange:
                    break
                await asyncio.sleep(POLL)
                waited += POLL

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
                        "[SESSION RECONNECTED — the previous connection dropped. This is the "
                        "transcript of the conversation you and the user were having moments ago. "
                        "Treat it as your own memory of the last few minutes and simply carry "
                        "on from where you left off. Do NOT announce the reconnection, do NOT "
                        "ask him to repeat himself or re-share his screen, and do NOT greet him "
                        "again — just continue naturally.]\n\n" + "\n".join(tail)
                    ))],
                ),
                turn_complete=False,
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
        model_turn_complete = True

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

            async def send_audio():
                last_paused = False
                while True:
                    data = await loop.run_in_executor(audio_pool, mic_stream.read)
                    # Pause-listening: drain the mic but DON'T forward it, so movie /
                    # ambient audio never reaches Gemini and can't trigger her.
                    paused = runtime.is_paused()
                    if paused != last_paused:
                        last_paused = paused
                        print("  🔇 Mic paused." if paused else "  🔊 Mic resumed.")
                        await runtime.emit("mic", {"paused": paused})
                    if paused:
                        continue
                    if model_speaking.is_set():
                        # While Freya speaks, only let *intentional* speech
                        # through. The energy gate filters out her own voice
                        # bleeding from the speakers, which previously caused
                        # false barge-ins (she kept interrupting herself).
                        if not barge_in or _rms(data) < rms_threshold:
                            continue
                    await session.send_realtime_input(
                        audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                    )

            async def receive_audio():
                nonlocal pending_playback_chunks, model_turn_complete
                freya_buffer = ""
                user_buffer = ""

                async def flush_user():
                    # Emit the user's words as ONE complete utterance instead
                    # of fragment-by-fragment transcript lines.
                    nonlocal user_buffer
                    full = user_buffer.strip()
                    user_buffer = ""
                    if full:
                        print(f"  You  : {full}")
                        # Speech is presence. Without this the context tracker
                        # reads a long spoken session as an empty chair.
                        runtime.note_user_turn()
                        if self.transcript:
                            self.transcript.add("User", full)
                        self._note_day_turn(full)
                        await self.on_transcript("User", full)

                async def flush_freya(cut: bool = False):
                    nonlocal freya_buffer
                    full = freya_buffer.strip()
                    freya_buffer = ""
                    if full:
                        if cut:
                            full += " …"
                        print(f"  Freya: {full}")
                        runtime.note_model_turn()
                        if self.transcript:
                            self.transcript.add("Freya", full)
                        await self.on_transcript("Freya", full)

                while True:
                    async for response in session.receive():
                        # ── Keep the resumption token fresh ──
                        # The server emits a new handle throughout the session.
                        # Stashing the latest one means a reconnect (planned or
                        # not) resumes the real conversation rather than
                        # starting from nothing.
                        sru = getattr(response, "session_resumption_update", None)
                        if sru is not None:
                            if getattr(sru, "resumable", False) and getattr(sru, "new_handle", None):
                                self.resume_handle = sru.new_handle
                            continue

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

                        if response.server_content is None:
                            if response.tool_call is not None:
                                for fc in response.tool_call.function_calls:
                                    tool_name = fc.name
                                    tool_args = dict(fc.args) if fc.args else {}
                                    call_id = fc.id
                                    print(f"  Tool : {tool_name}({tool_args})")
                                    ctx = ToolContext(self.config, session=session)
                                    result = await registry_dispatch(tool_name, tool_args, ctx)
                                    print(f"  Result: {result}")
                                    await self.on_tool(tool_name, tool_args, result)

                                    # ── VISION: send screenshot to Gemini as image ──
                                    if result == "VISION_REQUESTED":
                                        from core.vision import capture_screen, get_capture_grid
                                        import base64
                                        print("  Capturing screen...")
                                        b64_image = capture_screen()
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
                                        # the tool response that follows is what resumes the model
                                        # — with the image guaranteed already in context.
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
                                        print("  Screen sent to Gemini (client_content).")
                                    else:
                                        await session.send_tool_response(
                                            function_responses=[types.FunctionResponse(
                                                id=call_id,
                                                name=tool_name,
                                                response={"result": result}
                                            )]
                                        )
                                        # Clear speaking block to unmute mic if the tool execution finishes
                                        pending_playback_chunks = 0
                                        model_turn_complete = True
                                        model_speaking.clear()
                                        await self.on_state("listening")
                            continue

                        sc = response.server_content

                        # ── BARGE-IN: user interrupted Freya mid-sentence ──
                        if getattr(sc, 'interrupted', False):
                            # Drop all queued (unplayed) audio so she stops instantly
                            while not audio_queue.empty():
                                try:
                                    audio_queue.get_nowait()
                                    audio_queue.task_done()
                                except asyncio.QueueEmpty:
                                    break
                            # Keep what she managed to say, marked as cut off
                            await flush_freya(cut=True)
                            pending_playback_chunks = 0
                            model_turn_complete = True
                            model_speaking.clear()
                            await self.on_state("interrupted")
                            continue

                        # Accumulate input transcription fragments silently
                        inp = getattr(sc, 'input_transcription', None)
                        if inp:
                            text = getattr(inp, 'text', str(inp)).strip()
                            if text:
                                user_buffer += " " + text

                        # Buffer Freya's words — don't emit yet
                        out = getattr(sc, 'output_transcription', None)
                        if out:
                            text = getattr(out, 'text', str(out)).strip()
                            if text:
                                # Model started answering → the user's turn is over
                                await flush_user()
                                freya_buffer += " " + text
                                model_turn_complete = False
                                # Stream the fragment live so the UI can type it out
                                # in the center of the scene as she speaks.
                                await runtime.emit("speech", {"text": text})

                        # Turn complete → emit full buffered sentences
                        if getattr(sc, 'turn_complete', False):
                            await flush_user()
                            await flush_freya()
                            model_turn_complete = True
                            if pending_playback_chunks == 0:
                                model_speaking.clear()
                                await self.on_state("listening")
                            continue

                        if sc.model_turn is None:
                            continue

                        for part in sc.model_turn.parts:
                            if part.inline_data is not None:
                                if not model_speaking.is_set():
                                    model_speaking.set()
                                    await self.on_state("speaking")
                                model_turn_complete = False
                                pending_playback_chunks += 1
                                await audio_queue.put(part.inline_data.data)

            async def play_audio():
                nonlocal pending_playback_chunks
                while True:
                    data = await audio_queue.get()
                    await loop.run_in_executor(audio_pool, speaker_stream.write, data)
                    audio_queue.task_done()
                    pending_playback_chunks = max(0, pending_playback_chunks - 1)
                    if pending_playback_chunks == 0 and model_turn_complete:
                        model_speaking.clear()
                        await self.on_state("listening")

            try:
                await asyncio.gather(
                    send_audio(),
                    receive_audio(),
                    play_audio()
                )
            finally:
                # Release the proactive channels and background loops bound to
                # this session so the next reconnect starts clean.
                runtime.clear_channels()
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