"""Text generation. Primary: Google Gemini (free tier). Fallback: Cloudflare Workers AI LLM.
All calls ask for JSON and return a parsed object."""
import json
import re
import time

import requests

from . import config

_GEMINI_MODELS = None
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
CF_TEXT_MODELS = [
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/meta/llama-3.1-8b-instruct",
]


class LLMError(Exception):
    pass


def _version_key(name: str):
    m = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2) or 0))


def gemini_models() -> list:
    """Pick usable text models from the account's model list, best first."""
    global _GEMINI_MODELS
    if _GEMINI_MODELS is not None:
        return _GEMINI_MODELS
    preferred_env = config.env("GEMINI_MODEL")
    names = []
    try:
        r = requests.get(f"{GEMINI_BASE}/models", params={"key": config.GEMINI_API_KEY, "pageSize": 200}, timeout=30)
        r.raise_for_status()
        for m in r.json().get("models", []):
            n = m["name"].split("/", 1)[-1]
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            if not n.startswith("gemini-"):
                continue
            if any(x in n for x in ("tts", "image", "live", "audio", "embedding", "transcribe", "translate", "robotics", "computer-use", "omni")):
                continue
            names.append(n)
    except Exception as e:
        print(f"[llm] Gemini model listesi alınamadı: {e}")

    def rank(n):
        flash = "flash" in n
        lite = "lite" in n
        pro = "pro" in n
        preview = "preview" in n or "exp" in n
        tier = 0 if (flash and not lite) else 1 if lite else 2 if pro else 3
        return (tier, preview, tuple(-x for x in _version_key(n)), n)

    names = sorted(set(names), key=rank)
    if preferred_env:
        names = [preferred_env] + [n for n in names if n != preferred_env]
    if not names:
        names = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest"]
    _GEMINI_MODELS = names[:6]
    print(f"[llm] Gemini modelleri: {_GEMINI_MODELS}")
    return _GEMINI_MODELS


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        s, e = text.find(open_c), text.rfind(close_c)
        if s != -1 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except Exception:
                continue
    raise LLMError("Yanıt JSON değil: " + text[:300])


def _gemini(prompt: str, system: str, temperature: float):
    last = None
    for model in gemini_models():
        for attempt in range(3):
            try:
                body = {
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
                }
                if system:
                    body["systemInstruction"] = {"parts": [{"text": system}]}
                r = requests.post(
                    f"{GEMINI_BASE}/models/{model}:generateContent",
                    params={"key": config.GEMINI_API_KEY},
                    json=body,
                    timeout=180,
                )
                if r.status_code == 404:
                    raise LLMError(f"{model} yok")
                if r.status_code >= 500:
                    # overloaded model: try the next model quickly instead of waiting
                    last = f"{model}: HTTP {r.status_code}"
                    print(f"[llm] {last} — sıradaki modele geçiliyor")
                    time.sleep(3)
                    break
                if r.status_code == 429:
                    last = f"{model}: HTTP 429 {r.text[:200]}"
                    if "per day" in r.text.lower() or "PerDay" in r.text:
                        break  # daily quota of this model used up
                    wait = 20 * (attempt + 1)
                    print(f"[llm] {last} — {wait}s bekleniyor")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                data = r.json()
                parts = data["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                return extract_json(text)
            except LLMError as e:
                last = str(e)
                break
            except Exception as e:
                last = f"{model}: {e}"
                print(f"[llm] {last}")
                time.sleep(5)
    raise LLMError(f"Gemini başarısız: {last}")


def _cloudflare(prompt: str, system: str, temperature: float):
    last = None
    for model in CF_TEXT_MODELS:
        try:
            r = requests.post(
                f"https://api.cloudflare.com/client/v4/accounts/{config.CLOUDFLARE_ACCOUNT_ID}/ai/run/{model}",
                headers={"Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}"},
                json={
                    "messages": [
                        {"role": "system", "content": (system or "") + "\nReply with valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": 4096,
                },
                timeout=180,
            )
            r.raise_for_status()
            res = r.json().get("result", {})
            out = res.get("response")
            if isinstance(out, (dict, list)):
                return out
            return extract_json(out or "")
        except Exception as e:
            last = f"{model}: {e}"
            print(f"[llm] Cloudflare {last}")
    raise LLMError(f"Cloudflare LLM başarısız: {last}")


def ask_json(prompt: str, system: str = "", temperature: float = 0.8):
    errors = []
    if config.GEMINI_API_KEY:
        try:
            return _gemini(prompt, system, temperature)
        except Exception as e:
            errors.append(str(e))
    if config.CLOUDFLARE_ACCOUNT_ID and config.CLOUDFLARE_API_TOKEN:
        try:
            return _cloudflare(prompt, system, temperature)
        except Exception as e:
            errors.append(str(e))
    raise LLMError("Hiçbir metin yapay zekâsı çalışmadı: " + " | ".join(errors or ["anahtar yok"]))
