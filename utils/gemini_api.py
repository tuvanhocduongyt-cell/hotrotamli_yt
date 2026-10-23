"""Shared AI client for chat, image grading and structured exam feedback."""
import os
import json
import base64
import urllib.error
import urllib.request
from pathlib import Path
import openai
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", encoding="utf-8-sig")

# ============================================================
# GEMINI / OPENROUTER API CLIENT
# ============================================================
import threading
import time as _time

def _load_gemini_keys():
    """Both singular and plural environment names accept comma-separated keys."""
    for name in ("GEMINI_API_KEYS", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        keys = list(dict.fromkeys(k.strip() for k in os.getenv(name, "").split(",") if k.strip()))
        if keys:
            return keys
    return []


GEMINI_KEYS = _load_gemini_keys()

_keys_env = os.getenv("OPENROUTER_API_KEYS")
if _keys_env:
    OPENROUTER_KEYS = [k.strip() for k in _keys_env.split(",") if k.strip()]
else:
    _single = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_KEYS = [_single] if _single else []

if not GEMINI_KEYS and not OPENROUTER_KEYS:
    raise ValueError("Không tìm thấy GEMINI_API_KEY/GOOGLE_API_KEY hoặc OPENROUTER_API_KEY")

_gemini_counter = 0
_gemini_lock = threading.Lock()
_gemini_cooldowns = {}
_or_counter = 0
_or_lock = threading.Lock()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv('GEMINI_FALLBACK_MODELS', '').split(',')
                          if m.strip() and m.strip() != GEMINI_MODEL]
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "google/gemini-2.5-flash"

def _get_gemini_key():
    """Keep using the current key until it is unavailable; skip cooling keys."""
    global _gemini_counter
    with _gemini_lock:
        now = _time.monotonic()
        candidates = [(_gemini_counter + offset) % len(GEMINI_KEYS)
                      for offset in range(len(GEMINI_KEYS))]
        index = next((i for i in candidates if _gemini_cooldowns.get(GEMINI_KEYS[i], 0) <= now), None)
        if index is None:
            index = min(candidates, key=lambda i: _gemini_cooldowns.get(GEMINI_KEYS[i], 0))
        _gemini_counter = index
        key = GEMINI_KEYS[index]
        return key, max(0, _gemini_cooldowns.get(key, 0) - now)


def _cooldown_gemini_key(key, delay):
    with _gemini_lock:
        _gemini_cooldowns[key] = _time.monotonic() + delay


def _gemini_retry_delay(body, status, attempt):
    delay = 60 if status == 429 else min(2 ** (attempt + 1), 60)
    try:
        details = json.loads(body).get("error", {}).get("details", [])
        for detail in details:
            if detail.get("@type", "").endswith("RetryInfo"):
                return max(1, float(detail["retryDelay"].removesuffix("s")) + 1)
        if any("PerDay" in violation.get("quotaId", "")
               for detail in details for violation in detail.get("violations", [])):
            return 86400
    except (ValueError, TypeError, KeyError):
        pass
    return delay

def _get_openrouter_key():
    """Round-Robin qua danh sách key OpenRouter."""
    global _or_counter
    with _or_lock:
        key = OPENROUTER_KEYS[_or_counter % len(OPENROUTER_KEYS)]
        _or_counter += 1
    return key

class _FakeResponse:
    """Wrapper để tương thích với code cũ dùng response.text"""
    def __init__(self, text, model=None):
        self.text = text
        self.model = model

def _build_gemini_parts(prompt_or_parts):
    if not isinstance(prompt_or_parts, list):
        return [{"text": str(prompt_or_parts)}]

    parts = []
    for part in prompt_or_parts:
        try:
            from PIL import Image as _PILImage
            if isinstance(part, _PILImage.Image):
                import io as _io
                buf = _io.BytesIO()
                part.convert("RGB").save(buf, format="JPEG", quality=85)
                parts.append({
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(buf.getvalue()).decode("utf-8"),
                    }
                })
                continue
        except ImportError:
            pass
        if isinstance(part, str):
            parts.append({"text": part})
    return parts or [{"text": ""}]

def _generate_with_gemini(prompt_or_parts, max_retries=None, response_mime_type=None, model=None):
    model = model or GEMINI_MODEL
    if max_retries is None:
        max_retries = max(len(GEMINI_KEYS), 3)
    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")

    config = {"maxOutputTokens": 8192}
    if response_mime_type:
        config["responseMimeType"] = response_mime_type
    body = json.dumps({
        "contents": [{"role": "user", "parts": _build_gemini_parts(prompt_or_parts)}],
        "generationConfig": config,
    }).encode("utf-8")
    last_error = None

    for attempt in range(max_retries):
        key, wait = _get_gemini_key()
        if wait > 60:
            raise last_error or RuntimeError("All Gemini keys are unavailable; quota has not reset yet.")
        if wait > 0:
            print(f"[GEMINI RETRY] All keys cooling down; waiting {wait:.1f}s")
            _time.sleep(wait)
        try:
            req = urllib.request.Request(
                f"{GEMINI_BASE_URL}/models/{model}:generateContent",
                data=body,
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            candidate = candidates[0] if candidates else {}
            reason = candidate.get("finishReason")
            if reason and reason != "STOP":
                raise RuntimeError(f"Gemini response incomplete or blocked: {reason}")
            result_text = "".join(
                part.get("text", "")
                for part in candidate.get("content", {}).get("parts", [])
                if not part.get("thought")
            )
            if not result_text.strip():
                reason = data.get("promptFeedback", {}).get("blockReason", "EMPTY_RESPONSE")
                raise RuntimeError(f"Gemini returned no text: {reason}")
            with _gemini_lock:
                _gemini_cooldowns.pop(key, None)
            return _FakeResponse(result_text, model=model)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            for secret in GEMINI_KEYS:
                err_body = err_body.replace(secret, "[REDACTED]")
            last_error = RuntimeError(f"Gemini API error {e.code}: {err_body}")
            invalid_key = e.code in (401, 403) or (
                e.code == 400 and ("API_KEY_INVALID" in err_body or "API key not valid" in err_body))
            if invalid_key or e.code in (429, 500, 502, 503, 504):
                delay = 86400 if invalid_key else _gemini_retry_delay(err_body, e.code, attempt)
                _cooldown_gemini_key(key, delay)
                print(f"[GEMINI RETRY] HTTP {e.code}; trying another available key ({attempt+1}/{max_retries})")
                continue
            raise last_error from e
        except (TimeoutError, urllib.error.URLError) as e:
            last_error = RuntimeError("Gemini connection timed out or failed temporarily.")
            _cooldown_gemini_key(key, min(2 ** (attempt + 1), 60))
            print(f"[GEMINI RETRY] Connection error; trying another available key ({attempt+1}/{max_retries})")
            continue
        except Exception as e:
            last_error = e
            raise

    print(f"[GEMINI ROTATE] Tat ca {max_retries} lan thu deu that bai!")
    raise last_error

def generate_with_retry(prompt_or_parts, feature=None, max_retries=None, response_mime_type=None):
    """
    Ưu tiên Gemini, dùng OpenRouter dự phòng nếu có cấu hình khóa.
    Hỗ trợ prompt dạng:
      - string: gửi thẳng
      - list: có thể chứa str và PIL.Image (vision)
    Ảnh PIL được chuyển sang JPEG và gửi theo định dạng của từng nhà cung cấp.
    """
    if GEMINI_KEYS:
        try:
            models = [GEMINI_MODEL] + GEMINI_FALLBACK_MODELS
            for model_index, model in enumerate(models):
                try:
                    return _generate_with_gemini(prompt_or_parts, max_retries=max_retries,
                                                 response_mime_type=response_mime_type, model=model)
                except RuntimeError as error:
                    # Model capacity/transport errors can be model-specific. Quota,
                    # authentication and invalid output must retain their semantics.
                    transient = any(marker in str(error) for marker in (
                        'Gemini API error 500:', 'Gemini API error 502:',
                        'Gemini API error 503:', 'Gemini API error 504:',
                        'Gemini connection timed out'))
                    if not transient or model_index == len(models) - 1:
                        raise
                    print('[GEMINI FALLBACK] Model temporarily unavailable; trying configured fallback model.')
        except Exception as gemini_error:
            if not OPENROUTER_KEYS:
                raise
            print(f"[GEMINI FALLBACK] Gemini loi, thu OpenRouter: {gemini_error}")

    if max_retries is None:
        max_retries = max(len(OPENROUTER_KEYS), 3)

    # Xây dựng message content hỗ trợ multimodal vision
    if isinstance(prompt_or_parts, list):
        content_parts = []
        for part in prompt_or_parts:
            # Kiểm tra PIL Image
            try:
                from PIL import Image as _PILImage
                if isinstance(part, _PILImage.Image):
                    import io as _io
                    buf = _io.BytesIO()
                    part.convert("RGB").save(buf, format="JPEG", quality=85)
                    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                    })
                    continue
            except ImportError:
                pass
            if isinstance(part, str):
                content_parts.append({"type": "text", "text": part})
        message_content = content_parts if content_parts else [{"type": "text", "text": ""}]
    else:
        message_content = [{"type": "text", "text": str(prompt_or_parts)}]

    last_error = None

    for attempt in range(max_retries):
        key = _get_openrouter_key()
        try:
            client = openai.OpenAI(
                api_key=key,
                base_url=OPENROUTER_BASE_URL,
            )
            resp = client.chat.completions.create(
                model=OPENROUTER_MODEL,
                messages=[{"role": "user", "content": message_content}],
                max_tokens=8192,
                **({"response_format": {"type": "json_object"}}
                   if response_mime_type == "application/json" else {}),
            )
            result_text = resp.choices[0].message.content or ""
            return _FakeResponse(result_text, model=OPENROUTER_MODEL)
        except Exception as e:
            last_error = e
            err_str = str(e)
            if '429' in err_str or 'quota' in err_str.lower() or 'rate' in err_str.lower():
                print(f"[OR ROTATE] Request bị giới hạn (attempt {attempt+1}/{max_retries}), thử key khác...")
                _time.sleep(1)
                continue
            raise

    print(f"[OR ROTATE] Tất cả {max_retries} lần thử đều thất bại!")
    raise last_error


def analyze_text_with_gemini(text):
    return generate_with_retry(text).text


def analyze_text_with_openrouter(text):
    """Compatibility alias: uses Gemini when a Gemini key is configured."""
    return analyze_text_with_gemini(text)
