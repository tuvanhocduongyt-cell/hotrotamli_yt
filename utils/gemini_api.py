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

# helper to rotate

def get_api_key():
    return random.choice(API_KEYS)

def analyze_text_with_openrouter(text):
    openai.api_key = get_api_key()
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": text}]
    )
    return response["choices"][0]["message"]["content"]

