import os
import random
from dotenv import load_dotenv
import openai

# ensure .env is loaded in case the importer didn't load it yet
load_dotenv()

# load keys from environment (support comma-separated list)
keys_env = os.getenv("OPENROUTER_API_KEYS")
if keys_env:
    API_KEYS = [k.strip() for k in keys_env.split(",") if k.strip()]
else:
    single = os.getenv("OPENROUTER_API_KEY")
    API_KEYS = [single] if single else []

if not API_KEYS:
    raise ValueError("Không tìm thấy OPENROUTER_API_KEY hoặc OPENROUTER_API_KEYS trong environment")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "google/gemini-2.0-flash-001"

def get_api_key():
    return random.choice(API_KEYS)

def analyze_text_with_openrouter(text):
    client = openai.OpenAI(
        api_key=get_api_key(),
        base_url=OPENROUTER_BASE_URL,
    )
    response = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=[{"role": "user", "content": text}],
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""
