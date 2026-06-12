import asyncio
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
import inspect

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
model_id = "gemini-3.1-flash-live-preview"

async def inspect_session():
    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"]
    )
    async with client.aio.live.connect(model=model_id, config=config) as session:
        print("s.send_realtime_input signature:")
        print(inspect.signature(session.send_realtime_input))
        print("\ns.send_client_content signature:")
        print(inspect.signature(session.send_client_content))
        print("\nAll methods/attributes on session:")
        print([x for x in dir(session) if not x.startswith('_')])

if __name__ == "__main__":
    asyncio.run(inspect_session())
