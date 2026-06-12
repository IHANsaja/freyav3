from dotenv import load_dotenv
from google import genai
import os

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

print("API Key found:", api_key is not None)

client = genai.Client(api_key=api_key)

for model in client.models.list():
    print(model.name)