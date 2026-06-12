import asyncio
import os
import audioop
import pyaudio
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
model_id = "gemini-3.1-flash-live-preview"

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000

async def main():
    p = pyaudio.PyAudio()
    # Use default input device
    stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK
    )
    print("Mic stream started. Start speaking when connected...")
    
    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"]
    )
    
    print(f"Connecting to {model_id}...")
    try:
        async with client.aio.live.connect(model=model_id, config=config) as session:
            print("Successfully connected!")
            
            loop = asyncio.get_event_loop()
            
            async def send():
                print("Starting send loop...")
                try:
                    while True:
                        data = await loop.run_in_executor(None, stream.read, CHUNK, False)
                        rms = audioop.rms(data, 2)
                        # Print RMS periodically or if there is sound
                        if rms > 1500:
                            print(f"[MIC] Sending audio chunk (RMS={rms})")
                        await session.send_realtime_input(
                            audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                        )
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"Send error: {e}")

            async def recv():
                print("Starting recv loop...")
                try:
                    async for response in session.receive():
                        print(f"\n[SERVER EVENT] response received:")
                        if response.server_content:
                            sc = response.server_content
                            print(f"  server_content: turn_complete={sc.turn_complete}, interrupted={sc.interrupted}")
                            if sc.model_turn:
                                for part in sc.model_turn.parts:
                                    if part.text:
                                        print(f"    Text: {part.text}")
                                    if part.inline_data:
                                        print(f"    Audio chunk: {len(part.inline_data.data)} bytes")
                            if sc.input_transcription:
                                print(f"    Input transcription: {sc.input_transcription}")
                        if response.tool_call:
                            print(f"  tool_call: {response.tool_call}")
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"Recv error: {e}")

            send_task = asyncio.create_task(send())
            recv_task = asyncio.create_task(recv())
            
            # Let it run for 15 seconds so we can test speaking
            await asyncio.sleep(15.0)
            
            send_task.cancel()
            recv_task.cancel()
            await asyncio.gather(send_task, recv_task, return_exceptions=True)
            
    except Exception as e:
        print(f"Connection/API error: {e}")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
