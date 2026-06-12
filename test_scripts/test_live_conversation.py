import asyncio
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
model_id = "gemini-3.1-flash-live-preview"

async def test_conn():
    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"]
    )
    print(f"Connecting to {model_id}...")
    try:
        async with client.aio.live.connect(model=model_id, config=config) as session:
            print("Successfully connected!")
            print("Sending text greeting...")
            await session.send(input="Hello, are you there?", end_of_turn=True)
            
            print("Waiting for responses...")
            async for response in session.receive():
                print("\n--- New Message ---")
                if response.server_content:
                    sc = response.server_content
                    print(f"Server content present. turn_complete={sc.turn_complete}, interrupted={sc.interrupted}")
                    if sc.model_turn:
                        print("Model turn present:")
                        for part in sc.model_turn.parts:
                            if part.text:
                                print(f"  Text part: '{part.text}'")
                            if part.inline_data:
                                print(f"  Audio part present (length={len(part.inline_data.data)} bytes)")
                    if sc.input_transcription:
                        print(f"Input transcription: {sc.input_transcription}")
                if response.tool_call:
                    print(f"Tool call present: {response.tool_call}")
                if response.setup_complete:
                    print("Setup complete")
    except Exception as e:
        print(f"Connection failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_conn())
