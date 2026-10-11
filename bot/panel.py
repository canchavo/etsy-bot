"""Builds the static web panel (GitHub Pages). Product data is encrypted with
PANEL_PASSWORD (AES-GCM, PBKDF2) and decrypted in the browser."""
import base64
import json
import os
import shutil
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from . import config, storage
from .products import type_label

ITER = 210_000


def encrypt_for_browser(obj, password: str) -> dict:
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode(), None)
    b = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "iter": ITER, "salt": b(salt), "iv": b(iv), "data": b(ct)}


def build(out_dir=None):
    out = config.ROOT / (out_dir or "_site")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(config.ROOT / "panel", out)
    products = storage.all_products()[-120:]
    tok = storage.load_etsy()
    data = {
        "generated_at": int(time.time()),
        "etsy": {"connected": bool(tok.get("refresh_token")), "shop": tok.get("shop_name"), "shop_url": tok.get("shop_url")},
        "products": [
            {
                "id": p["id"], "title": p["title"], "type": type_label(p["type"]),
                "niche": p.get("niche"), "status": p["status"], "price": p.get("price_usd"),
                "created": p.get("created_at"), "tags": p.get("tags", []), "description": p.get("description", ""),
                "files": p.get("files", []), "etsy_url": p.get("etsy", {}).get("url"), "error": p.get("etsy", {}).get("error"),
                "thumb": p.get("thumb"), "research": p.get("research", {}),
            }
            for p in reversed(products)
        ],
    }
    if not config.PANEL_PASSWORD:
        print("[panel] PANEL_PASSWORD yok, panel verisi yazılmadı")
        (out / "data.json").write_text(json.dumps({"v": 0}))
    else:
        (out / "data.json").write_text(json.dumps(encrypt_for_browser(data, config.PANEL_PASSWORD)))
    (out / ".nojekyll").write_text("")
    return out
