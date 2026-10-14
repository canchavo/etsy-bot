"""Pinterest API v5: OAuth for the shop's own account, boards and image Pins."""
import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse

import requests

from . import config, storage

API = "https://api.pinterest.com/v5"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"

# product type -> board name (created automatically when missing)
BOARDS = {
    "wall_art": "Printable Wall Art",
    "coloring": "Coloring Pages for Adults & Kids",
    "clipart": "Clipart & PNG Graphics",
    "pattern": "Digital Paper & Scrapbook Patterns",
    "tumbler": "Tumbler Wrap Designs",
}
BOARD_DESC = "Instant digital downloads from Nuvira Studio (NuviraStudioDigital on Etsy)."


class PinterestError(Exception):
    pass


def configured() -> bool:
    return bool(config.PINTEREST_APP_ID and config.PINTEREST_APP_SECRET)


def connected() -> bool:
    return bool(storage.load_pinterest().get("refresh_token"))


def _sign(nonce: str) -> str:
    return hmac.new(config.STATE_KEY.encode(), ("pin:" + nonce).encode(), hashlib.sha256).hexdigest()[:16]


def is_pinterest_state(state: str) -> bool:
    if not state or not state.startswith("pin"):
        return False
    nonce, _, sig = state[3:].partition("_")
    return hmac.compare_digest(sig, _sign(nonce))


def auth_url() -> str:
    if not configured():
        raise PinterestError("PINTEREST_APP_SECRET GitHub'a eklenmemiş.")
    nonce = secrets.token_hex(8)
    q = {"client_id": config.PINTEREST_APP_ID, "redirect_uri": config.etsy_redirect_uri(),
         "response_type": "code", "scope": SCOPES, "state": f"pin{nonce}_{_sign(nonce)}"}
    return "https://www.pinterest.com/oauth/?" + urllib.parse.urlencode(q)


def _basic():
    raw = f"{config.PINTEREST_APP_ID}:{config.PINTEREST_APP_SECRET}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _token_request(data: dict, old: dict) -> dict:
    r = requests.post(API + "/oauth/token", headers=_basic(), data=data, timeout=30)
    if r.status_code != 200:
        raise PinterestError(f"Pinterest jetonu alınamadı: HTTP {r.status_code} {r.text[:300]}")
    j = r.json()
    tok = dict(old)
    tok["access_token"] = j["access_token"]
    tok["expires_at"] = int(time.time()) + int(j.get("expires_in", 2592000)) - 3600
    if j.get("refresh_token"):
        tok["refresh_token"] = j["refresh_token"]
        tok["refresh_expires_at"] = int(time.time()) + int(j.get("refresh_token_expires_in", 31536000))
    tok["refreshed_at"] = int(time.time())
    storage.save_pinterest(tok)
    return tok


def exchange(callback_url: str) -> dict:
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(callback_url.strip()).query)
    if "error" in qs:
        raise PinterestError(f"Pinterest izin vermedi: {qs['error'][0]}")
    if not is_pinterest_state(qs.get("state", [""])[0]):
        raise PinterestError("Bu adres Pinterest bağlantısına ait değil (state uyuşmuyor).")
    tok = _token_request({"grant_type": "authorization_code", "code": qs["code"][0],
                          "redirect_uri": config.etsy_redirect_uri()}, {})
    me = _req("GET", "/user_account", tok)
    tok["username"] = me.get("username")
    storage.save_pinterest(tok)
    return tok


def token(force_refresh=False) -> dict:
    tok = storage.load_pinterest()
    if not tok.get("refresh_token"):
        raise PinterestError("Pinterest bağlı değil. Telegram'da /pinterest yazın.")
    if force_refresh or time.time() >= tok.get("expires_at", 0) - 2 * 86400:
        tok = _token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}, tok)
    return tok


def keepalive() -> bool:
    tok = storage.load_pinterest()
    if tok.get("refresh_token") and time.time() - tok.get("refreshed_at", 0) > 7 * 86400:
        token(force_refresh=True)
        return True
    return False


def _req(method, path, tok=None, **kw):
    tok = tok or token()
    for attempt in range(3):
        r = requests.request(method, API + path, headers={"Authorization": f"Bearer {tok['access_token']}"},
                             timeout=120, **kw)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        break
    if r.status_code >= 400:
        raise PinterestError(f"{method} {path}: HTTP {r.status_code} {r.text[:300]}")
    return r.json() if r.content else {}


def board_id(ptype: str) -> str:
    tok = token()
    name = BOARDS.get(ptype, "Printable Wall Art")
    cache = tok.setdefault("boards", {})
    if name in cache:
        return cache[name]
    bookmark = None
    while True:
        res = _req("GET", "/boards", tok, params={"page_size": 100, **({"bookmark": bookmark} if bookmark else {})})
        for b in res.get("items", []):
            cache[b["name"]] = b["id"]
        bookmark = res.get("bookmark")
        if not bookmark:
            break
    if name not in cache:
        b = _req("POST", "/boards", tok, json={"name": name, "description": BOARD_DESC, "privacy": "PUBLIC"})
        cache[name] = b["id"]
    storage.save_pinterest(tok)
    return cache[name]


def create_pin(ptype: str, image_jpeg: bytes, title: str, description: str, link: str, alt: str = "") -> dict:
    body = {
        "board_id": board_id(ptype),
        "title": title[:100],
        "description": description[:500],
        "link": link,
        "alt_text": (alt or title)[:500],
        "media_source": {"source_type": "image_base64", "content_type": "image/jpeg",
                         "data": base64.b64encode(image_jpeg).decode()},
    }
    pin = _req("POST", "/pins", json=body)
    return {"id": pin.get("id"), "url": f"https://www.pinterest.com/pin/{pin.get('id')}/"}
