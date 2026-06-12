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
            # Send a small text or audio chunk to trigger a response
            # Note: in live api we can send text content via session.send
            print("Sending text greeting...")
            await session.send(input="Hello, are you there?", end_of_turn=True)
            
            print("Waiting for response...")
            async for response in session.receive():
                print("Received response:")
                print(response)
                # Break after receiving some response to not hang forever
                break
    except Exception as e:
        print(f"Connection failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_conn())
