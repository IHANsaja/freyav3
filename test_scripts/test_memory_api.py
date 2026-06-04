import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_MEMORY_API_KEY")
print("GEMINI_MEMORY_API_KEY loaded:", api_key is not None)

client = genai.Client(api_key=api_key)
try:
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents="Say hello"
    )
    print("Response text:", response.text)
except Exception as e:
    print("Error encountered:", e)
