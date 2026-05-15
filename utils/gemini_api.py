import os
import random
from dotenv import load_dotenv
from google import genai

# ensure .env is loaded in case the importer didn't load it yet
load_dotenv()

# load keys from environment (support comma-separated list)
keys_env = os.getenv("GOOGLE_API_KEYS")
if keys_env:
    API_KEYS = [k.strip() for k in keys_env.split(",") if k.strip()]
else:
    single = os.getenv("GOOGLE_API_KEY")
    API_KEYS = [single] if single else []

if not API_KEYS:
    raise ValueError("Không tìm thấy GOOGLE_API_KEY hoặc GOOGLE_API_KEYS trong environment")

# helper to rotate

def get_api_key():
    return random.choice(API_KEYS)


def get_model():
    return genai.GenerativeModel("models/gemini-flash-latest")


def analyze_text_with_gemini(text):
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[{"role": "user", "text": text}]
    )
    return response.text

