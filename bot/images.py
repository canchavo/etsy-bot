"""AI image generation with free providers, tried in order:
1. Cloudflare Workers AI – FLUX.2 [klein] (free daily allowance, needs CF account)
2. Cloudflare Workers AI – FLUX.1 [schnell] (square 1024, cropped to the requested ratio)
3. Pollinations.ai (free, may be slow/rate limited)
"""
import base64
import io
import random
import time
import urllib.parse

import requests
from PIL import Image, ImageOps

from . import config

CF_MULTIPART_MODELS = ["@cf/black-forest-labs/flux-2-klein-4b"]
CF_JSON_MODELS = ["@cf/black-forest-labs/flux-1-schnell"]

_disabled = set()  # providers that hit a daily quota during this run
stats = {"cloudflare": 0, "pollinations": 0, "failed": 0}


class ImageError(Exception):
    pass


QUOTA_MSG = "Cloudflare günlük ücretsiz görsel kotası doldu (her gün 03:00'te yenilenir)"


def quota_exhausted():
    """True when every image provider is out for today."""
    return all(m in _disabled for m in CF_MULTIPART_MODELS + CF_JSON_MODELS) and "pollinations" in _disabled


def _snap(v: int) -> int:
    v = max(256, min(1920, int(v)))
    return v - v % 16


def fit_size(aspect: float, long_side: int = 1920):
    """Width/height for an aspect ratio (w/h) within provider limits."""
    if aspect >= 1:
        w, h = long_side, long_side / aspect
    else:
        w, h = long_side * aspect, long_side
    return _snap(w), _snap(h)


def _decode(b64: str) -> Image.Image:
    img = Image.open(io.BytesIO(base64.b64decode(b64)))
    img.load()
    return img.convert("RGB")


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img, (w, h), Image.LANCZOS)


def _quota_error(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ("neuron", "quota", "daily", "limit exceeded", "allocation", "capacity exceeded", "4006"))


def _cloudflare(prompt, w, h, seed):
    if not (config.CLOUDFLARE_ACCOUNT_ID and config.CLOUDFLARE_API_TOKEN):
        raise ImageError("Cloudflare anahtarı yok")
    base = f"https://api.cloudflare.com/client/v4/accounts/{config.CLOUDFLARE_ACCOUNT_ID}/ai/run/"
    headers = {"Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}"}
    errs = []
    for model in CF_MULTIPART_MODELS:
        if model in _disabled:
            continue
        for attempt in range(3):
            try:
                files = {
                    "prompt": (None, prompt[:2000]),
                    "width": (None, str(w)),
                    "height": (None, str(h)),
                }
                r = requests.post(base + model, headers=headers, files=files, timeout=180)
                if r.status_code == 200:
                    data = r.json()
                    img_b64 = (data.get("result") or {}).get("image")
                    if img_b64:
                        return _decode(img_b64)
                    errs.append(f"{model.split('/')[-1]}: boş yanıt")
                else:
                    errs.append(f"{model.split('/')[-1]}: HTTP {r.status_code} {r.text[:160]}")
                    print(f"[images] {errs[-1]}", flush=True)
                    if _quota_error(r.text) or r.status_code in (401, 403, 429):
                        _disabled.add(model)
                        break
            except Exception as e:
                errs.append(f"{model.split('/')[-1]}: {e}")
            time.sleep(4 * (attempt + 1))
    for model in CF_JSON_MODELS:
        if model in _disabled:
            continue
        try:
            r = requests.post(base + model, headers=headers, json={"prompt": prompt[:2000], "steps": 8}, timeout=180)
            if r.status_code == 200:
                img_b64 = (r.json().get("result") or {}).get("image")
                if img_b64:
                    return _cover(_decode(img_b64), w, h)
            errs.append(f"{model.split('/')[-1]}: HTTP {r.status_code} {r.text[:160]}")
            print(f"[images] {errs[-1]}", flush=True)
            if _quota_error(r.text) or r.status_code in (401, 403, 429):
                _disabled.add(model)
        except Exception as e:
            errs.append(f"{model.split('/')[-1]}: {e}")
    if all(m in _disabled for m in CF_MULTIPART_MODELS + CF_JSON_MODELS) and not errs:
        raise ImageError(QUOTA_MSG)
    raise ImageError(" / ".join(errs) or "Cloudflare kullanılamıyor")


def _pollinations(prompt, w, h, seed):
    if "pollinations" in _disabled:
        raise ImageError("Pollinations devre dışı")
    q = urllib.parse.quote(prompt[:1500], safe="")
    params = {"width": w, "height": h, "seed": seed, "model": "flux", "nologo": "true", "private": "true"}
    urls = []
    headers = {}
    if config.POLLINATIONS_TOKEN:
        headers["Authorization"] = f"Bearer {config.POLLINATIONS_TOKEN}"
        urls.append(f"https://gen.pollinations.ai/image/{q}")
    urls.append(f"https://image.pollinations.ai/prompt/{q}")
    last = ""
    for url in urls:
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, headers=headers, timeout=240)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                    img = Image.open(io.BytesIO(r.content))
                    img.load()
                    return _cover(img.convert("RGB"), w, h)
                last = f"HTTP {r.status_code} {r.text[:150]}"
                if r.status_code in (401, 402, 403):
                    if r.status_code == 402:
                        _disabled.add("pollinations")  # free limit used up for now
                    break
            except Exception as e:
                last = str(e)
            time.sleep(15 * (attempt + 1))
    raise ImageError(f"Pollinations: {last}")


def generate(prompt: str, width: int, height: int, seed: int = None) -> Image.Image:
    w, h = _snap(width), _snap(height)
    seed = seed if seed is not None else random.randint(1, 2**31 - 1)
    errors = []
    for name, fn in (("cloudflare", _cloudflare), ("pollinations", _pollinations)):
        try:
            img = fn(prompt, w, h, seed)
            stats[name] += 1
            return img
        except Exception as e:
            errors.append(f"{name}: {e}")
    stats["failed"] += 1
    if quota_exhausted():
        raise ImageError("Görsel üretilemedi → " + QUOTA_MSG)
    raise ImageError("Görsel üretilemedi → " + " | ".join(errors))
