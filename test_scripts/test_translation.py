import asyncio
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
model_id = "gemini-3.5-live-translate-preview"

async def test_translation():
    client = genai.Client(api_key=api_key)
    
    # Configure stream translation for spanish
    translation_config = types.StreamTranslationConfig(
        target_language_code="es",
        echo_target_language=True
    )
    
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        stream_translation_config=translation_config
    )
    
    print(f"Connecting to translation model {model_id}...")
    try:
        async with client.aio.live.connect(model=model_id, config=config) as session:
            print("Successfully connected!")
            print("Sending text greeting in English to translate to Spanish...")
            await session.send(input="Hello, how are you doing today?", end_of_turn=True)
            
            print("Waiting for responses...")
            async for response in session.receive():
                print("\n--- New Message ---")
                if response.server_content:
                    sc = response.server_content
                    print(f"Server content present. turn_complete={sc.turn_complete}")
                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.text:
                                print(f"  Text: {part.text}")
                            if part.inline_data:
                                print(f"  Audio: {len(part.inline_data.data)} bytes")
                    if sc.output_transcription:
                        print(f"  Output transcription: {sc.output_transcription.text}")
    except Exception as e:
        print(f"Connection failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_translation())
