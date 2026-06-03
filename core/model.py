import asyncio
from google import genai
from google.genai import types

class FreyaModel:
    def __init__(self, api_key, model_id, voice, personality):
        self.client = genai.Client(api_key=api_key)
        self.model_id = model_id
        self.voice = voice
        self.personality = personality
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
            )
        )

    async def run(self, mic_stream, speaker_stream):
        print(f"\nConnecting to {self.model_id}...")

        audio_queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        async with self.client.aio.live.connect(
            model=self.model_id,
            config=self.get_config()
        ) as session:
            self.session = session
            print("Freya is live! Start talking. (Ctrl+C to stop)\n")

            async def send_audio():
                while True:
                    # Run blocking mic read in thread pool so it doesn't block event loop
                    data = await loop.run_in_executor(None, mic_stream.read)
                    await session.send_realtime_input(
                        audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                    )

            async def receive_audio():
                while True:
                    async for response in session.receive():
                        if response.server_content is None:
                            continue
                        if response.server_content.model_turn is None:
                            continue
                        for part in response.server_content.model_turn.parts:
                            if part.inline_data is not None:
                                await audio_queue.put(part.inline_data.data)

            async def play_audio():
                while True:
                    data = await audio_queue.get()
                    # Run blocking speaker write in thread pool too
                    await loop.run_in_executor(None, speaker_stream.write, data)
                    audio_queue.task_done()

            await asyncio.gather(
                send_audio(),
                receive_audio(),
                play_audio()
            )