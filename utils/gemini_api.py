import os
import random
from dotenv import load_dotenv
import google.generativeai as genai

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
    genai.configure(api_key=get_api_key())
    return genai.GenerativeModel("models/gemini-flash-latest")


def analyze_text_with_gemini(text):
    model = get_model()
    response = model.generate_content(f"Đây là bài làm của học sinh:\n{text}\nHãy nhận xét và đề xuất cải thiện.")
    return response.text

