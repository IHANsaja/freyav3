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
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def run(self, mic_stream, speaker_stream):
        print(f"\nConnecting to {self.model_id}...")

        audio_queue = asyncio.Queue()
        model_speaking = asyncio.Event()   # set while Freya is talking
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
                    # Don't send mic audio while Freya is speaking
                    # (prevents speaker → mic feedback loop)
                    if not model_speaking.is_set():
                        await session.send_realtime_input(
                            audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                        )

            async def receive_audio():
                while True:
                    async for response in session.receive():
                        if response.server_content is None:
                            continue

                        sc = response.server_content

                        # --- transcription logging ---
                        inp = getattr(sc, 'input_transcription', None)
                        if inp:
                            text = getattr(inp, 'text', str(inp)).strip()
                            if text:
                                print(f"  You  : {text}")

                        out = getattr(sc, 'output_transcription', None)
                        if out:
                            text = getattr(out, 'text', str(out)).strip()
                            if text:
                                print(f"  Freya: {text}")

                        # --- turn complete → unmute mic ---
                        if getattr(sc, 'turn_complete', False):
                            model_speaking.clear()
                            continue

                        if sc.model_turn is None:
                            continue

                        # --- stream audio chunks to speaker ---
                        for part in sc.model_turn.parts:
                            if part.inline_data is not None:
                                model_speaking.set()  # mute mic
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