from asyncio import selector_events
import asyncio
import json
from google import genai
from google.genai import types
from core.tools import dispatch

# ─────────────────────────────────────────────
#  TOOL DEFINITIONS  (Gemini function calling)
# ─────────────────────────────────────────────
TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="open_app",
        description="Launch an application by name. Use this when the user says open, launch or start an app.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "name": types.Schema(type=types.Type.STRING,
                    description="App name e.g. valorant, photoshop, discord, steam, word, edge, vscode")
            },
            required=["name"]
        )
    ),
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
        name="web_search",
        description="Search something on Google and open results in browser.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(type=types.Type.STRING,
                    description="The search query")
            },
            required=["query"]
        )
    ),
    types.FunctionDeclaration(
        name="play_youtube",
        description="Search and open YouTube for a video or song.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(type=types.Type.STRING,
                    description="What to search on YouTube")
            },
            required=["query"]
        )
    ),
    types.FunctionDeclaration(
        name="get_news",
        description="Get latest news on a topic and open Google News.",
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
        name="set_reminder",
        description="Set a reminder that Freya will speak after X minutes.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "message": types.Schema(type=types.Type.STRING,
                    description="Reminder message"),
                "minutes": types.Schema(type=types.Type.INTEGER,
                    description="How many minutes from now")
            },
            required=["message", "minutes"]
        )
    ),
    types.FunctionDeclaration(
        name="search_docs",
        description="Search official documentation for a technology or framework.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "technology": types.Schema(type=types.Type.STRING,
                    description="Technology name e.g. python, react, javascript, docker"),
                "query": types.Schema(type=types.Type.STRING,
                    description="What to search for in the docs")
            },
            required=["technology", "query"]
        )
    ),
    types.FunctionDeclaration(
        name="explain_error",
        description="Search for an error message on Stack Overflow to help debug.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "error_text": types.Schema(type=types.Type.STRING,
                    description="The full error message or traceback")
            },
            required=["error_text"]
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
        name="search_stackoverflow",
        description="Search Stack Overflow for a coding question and open the best result.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(type=types.Type.STRING,
                    description="The coding question or problem to search")
            },
            required=["query"]
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
]


class FreyaModel:
    def __init__(self, api_key, model_id, voice, personality, config, transcript=None):
        self.client = genai.Client(api_key=api_key)
        self.model_id = model_id
        self.voice = voice
        self.personality = personality
        self.config = config
        self.transcript = transcript
        self.session = None

    def get_config(self):
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
            tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
        )

    # Add these to FreyaModel class — override in subclass for UI broadcasting
    async def on_transcript(self, speaker_name: str, text: str):
        pass  # overridden in server.py

    async def on_tool(self, name: str, args: dict, result: str):
        pass  # overridden in server.py

    async def on_state(self, value: str):
        pass  # overridden in server.py

    async def run(self, mic_stream, speaker_stream):
        print(f"\nConnecting to {self.model_id}...")

        audio_queue = asyncio.Queue()
        model_speaking = asyncio.Event()
        loop = asyncio.get_event_loop()

        async with self.client.aio.live.connect(
            model=self.model_id,
            config=self.get_config()
        ) as session:
            self.session = session
            print("Freya is live! Start talking. (Ctrl+C to stop)\n")

            async def send_audio():
                while True:
                    data = await loop.run_in_executor(None, mic_stream.read)
                    if not model_speaking.is_set():
                        await session.send_realtime_input(
                            audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                        )

            async def receive_audio():
                freya_buffer = ""
                while True:
                    async for response in session.receive():
                        if response.server_content is None:
                            if response.tool_call is not None:
                                for fc in response.tool_call.function_calls:
                                    tool_name = fc.name
                                    tool_args = dict(fc.args) if fc.args else {}
                                    call_id = fc.id
                                    print(f"  Tool : {tool_name}({tool_args})")
                                    result = dispatch(tool_name, tool_args, self.config)
                                    print(f"  Result: {result}")
                                    await self.on_tool(tool_name, tool_args, result)
                                    await session.send_tool_response(
                                        function_responses=[types.FunctionResponse(
                                            id=call_id,
                                            name=tool_name,
                                            response={"result": result}
                                        )]
                                    )
                            continue

                        sc = response.server_content

                        # Buffer input transcription (your words)
                        inp = getattr(sc, 'input_transcription', None)
                        if inp:
                            text = getattr(inp, 'text', str(inp)).strip()
                            if text:
                                print(f"  You  : {text}")
                                if self.transcript:
                                    self.transcript.add("Ihan", text)
                                await self.on_transcript("Ihan", text)

                        # Buffer Freya's words — don't emit yet
                        out = getattr(sc, 'output_transcription', None)
                        if out:
                            text = getattr(out, 'text', str(out)).strip()
                            if text:
                                freya_buffer += " " + text

                        # Turn complete → emit full buffered sentence
                        if getattr(sc, 'turn_complete', False):
                            full_text = freya_buffer.strip()
                            if full_text:
                                print(f"  Freya: {full_text}")
                                if self.transcript:
                                    self.transcript.add("Freya", full_text)
                                await self.on_transcript("Freya", full_text)
                            freya_buffer = ""  # reset for next turn
                            model_speaking.clear()
                            await self.on_state("listening")
                            continue

                        if sc.model_turn is None:
                            continue

                        for part in sc.model_turn.parts:
                            if part.inline_data is not None:
                                model_speaking.set()
                                await self.on_state("speaking")
                                await audio_queue.put(part.inline_data.data)

            async def play_audio():
                while True:
                    data = await audio_queue.get()
                    await loop.run_in_executor(None, speaker_stream.write, data)
                    audio_queue.task_done()

            await asyncio.gather(
                send_audio(),
                receive_audio(),
                play_audio()
            )