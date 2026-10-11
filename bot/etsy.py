"""Etsy Open API v3: OAuth 2.0 (PKCE), shop info, public search, listing publishing."""
import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse

import requests

from . import config, storage

API = "https://openapi.etsy.com/v3/application"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
SCOPES = "listings_w listings_r listings_d shops_r shops_w transactions_r"


class EtsyError(Exception):
    pass


def _api_key():
    if not (config.ETSY_KEYSTRING and config.ETSY_SHARED_SECRET):
        raise EtsyError("ETSY_KEYSTRING / ETSY_SHARED_SECRET tanımlı değil")
    return f"{config.ETSY_KEYSTRING}:{config.ETSY_SHARED_SECRET}"


# ---------------- OAuth ----------------

def _verifier(state: str) -> str:
    # derive the PKCE verifier from the state so nothing has to be stored between steps
    digest = hmac.new(config.STATE_KEY.encode(), ("etsy-pkce:" + state).encode(), hashlib.sha256).digest()
    digest += hmac.new(config.STATE_KEY.encode(), ("etsy-pkce2:" + state).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:64]


def auth_url() -> str:
    redirect = config.etsy_redirect_uri()
    if not redirect:
        raise EtsyError("Yönlendirme adresi (callback) belirlenemedi")
    state = secrets.token_hex(12)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(_verifier(state).encode()).digest()).decode().rstrip("=")
    q = {
        "response_type": "code",
        "redirect_uri": redirect,
        "scope": SCOPES,
        "client_id": config.ETSY_KEYSTRING,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return "https://www.etsy.com/oauth/connect?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


def exchange(callback_url_or_code: str, state: str = None) -> dict:
    text = callback_url_or_code.strip()
    if "code=" in text:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(text).query)
        if "error" in qs:
            raise EtsyError(f"Etsy izin vermedi: {qs.get('error_description', qs['error'])[0]}")
        code = qs["code"][0]
        state = qs.get("state", [state])[0]
    else:
        code = text
    if not state:
        raise EtsyError("Bağlantı adresinde 'state' yok. Lütfen adres çubuğundaki adresin tamamını kopyalayın.")
    r = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "client_id": config.ETSY_KEYSTRING,
        "redirect_uri": config.etsy_redirect_uri(),
        "code": code,
        "code_verifier": _verifier(state),
    }, timeout=30)
    if r.status_code != 200:
        raise EtsyError(f"Etsy jetonu alınamadı: HTTP {r.status_code} {r.text[:300]}")
    tok = _store_token(r.json(), {})
    shop = get_shop(tok)
    tok.update({"shop_id": shop["shop_id"], "shop_name": shop.get("shop_name"), "shop_url": shop.get("url"),
                "currency": shop.get("currency_code", "USD")})
    storage.save_etsy(tok)
    return tok


def _store_token(data: dict, old: dict) -> dict:
    tok = dict(old)
    tok["access_token"] = data["access_token"]
    if data.get("refresh_token"):
        tok["refresh_token"] = data["refresh_token"]
        tok["refreshed_at"] = int(time.time())
    tok["expires_at"] = int(time.time()) + int(data.get("expires_in", 3600)) - 120
    tok["user_id"] = data["access_token"].split(".")[0]
    storage.save_etsy(tok)
    return tok


def token(force_refresh=False) -> dict:
    tok = storage.load_etsy()
    if not tok.get("refresh_token"):
        raise EtsyError("Etsy bağlı değil. Telegram'da /etsy yazarak bağlayın.")
    if force_refresh or time.time() >= tok.get("expires_at", 0):
        r = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": config.ETSY_KEYSTRING,
            "refresh_token": tok["refresh_token"],
        }, timeout=30)
        if r.status_code != 200:
            raise EtsyError(f"Etsy oturumu yenilenemedi (yeniden /etsy ile bağlayın): HTTP {r.status_code} {r.text[:200]}")
        tok = _store_token(r.json(), tok)
    return tok


def keepalive() -> bool:
    """Refresh tokens every few days so the 90-day refresh token never expires."""
    tok = storage.load_etsy()
    if tok.get("refresh_token") and time.time() - tok.get("refreshed_at", 0) > 5 * 86400:
        token(force_refresh=True)
        return True
    return False


def _req(method, path, tok=None, **kw):
    headers = kw.pop("headers", {})
    headers["x-api-key"] = _api_key()
    if tok:
        headers["Authorization"] = f"Bearer {tok['access_token']}"
    timeout = kw.pop("timeout", 120)
    for attempt in range(4):
        r = requests.request(method, API + path, headers=headers, timeout=timeout, **kw)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 415 and "json" in kw:
            # endpoint wants form encoding
            body = kw.pop("json")
            kw["data"] = {k: (",".join(v) if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else v)
                          for k, v in body.items()}
            continue
        break
    if r.status_code >= 400:
        raise EtsyError(f"{method} {path}: HTTP {r.status_code} {r.text[:400]}")
    return r.json() if r.content else {}


def get_shop(tok=None) -> dict:
    tok = tok or token()
    return _req("GET", f"/users/{tok['user_id']}/shops", tok)


# ---------------- public market data ----------------

def search_active(keywords: str, limit=25) -> dict:
    return _req("GET", "/listings/active", params={
        "keywords": keywords, "limit": limit, "sort_on": "score", "sort_order": "desc",
    }, timeout=30)


_TAXONOMY = None


def taxonomy_id(names: list, fallback: int) -> int:
    global _TAXONOMY
    try:
        if _TAXONOMY is None:
            nodes = _req("GET", "/seller-taxonomy/nodes").get("results", [])
            flat = {}

            def walk(ns):
                for n in ns:
                    if not n.get("children"):
                        flat.setdefault(n["name"].lower(), n["id"])
                    walk(n.get("children") or [])
            walk(nodes)
            _TAXONOMY = flat
        for name in names:
            if name.lower() in _TAXONOMY:
                return _TAXONOMY[name.lower()]
    except Exception as e:
        print(f"[etsy] kategori listesi alınamadı: {e}")
    return fallback


# ---------------- publishing ----------------

_FX = {}


def usd_to(currency: str, usd: float) -> float:
    currency = (currency or "USD").upper()
    if currency == "USD":
        return round(usd, 2)
    if currency not in _FX:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=30)
        r.raise_for_status()
        _FX.update(r.json()["rates"])
    v = usd * float(_FX[currency])
    # friendly price ending in .99 (or whole numbers for big currencies)
    if v >= 100:
        return float(int(v)) + 0.99 if currency not in ("JPY", "KRW") else float(round(v))
    return round(int(v) + 0.99 if v >= 2 else v, 2)


def _clean_tags(tags):
    out, seen = [], set()
    for t in tags:
        t = "".join(c for c in str(t) if c.isalnum() or c in " -'").strip()[:20].strip()
        if t and t.lower() not in seen:
            out.append(t)
            seen.add(t.lower())
    return out[:13]


def _when_made():
    y = time.gmtime().tm_year
    return f"{y - y % 10}_{y}" if y % 10 else "made_to_order"


def _create(shop_id, tok, data):
    try:
        return _req("POST", f"/shops/{shop_id}/listings", tok, json=data)
    except EtsyError as e:
        if "HTTP 415" not in str(e) and "content type" not in str(e).lower():
            raise
    form = {k: (",".join(v) if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else v) for k, v in data.items()}
    return _req("POST", f"/shops/{shop_id}/listings", tok, data=form)


import re as _re

_TEXT_WORDS = _re.compile(r"\b(quotes?|sayings?|typography|lettering|affirmations?)\b", _re.I)


def _strip_text_claims(p: dict) -> dict:
    """Our artwork never contains text. If the AI used words like 'quote' in the title/tags,
    remove them so the listing does not promise text, and add a short clarification."""
    hay = f"{p.get('title', '')} {p.get('niche', '')} {' '.join(p.get('tags', []))}"
    if not _TEXT_WORDS.search(hay):
        return p
    q = dict(p)
    t = _TEXT_WORDS.sub("", q["title"])
    t = _re.sub(r"\s{2,}", " ", t)
    t = _re.sub(r"\s+([,|])", r"\1", t)
    t = _re.sub(r"([,|])\s*([,|])", r"\1", t).strip(" ,|-")
    q["title"] = t
    q["tags"] = [x for x in (_re.sub(r"\s{2,}", " ", _TEXT_WORDS.sub("", tg)).strip() for tg in q.get("tags", [])) if len(x) >= 3]
    note = "Please note: these designs are artwork only and do not include any quotes or text."
    if note not in q.get("description", ""):
        q["description"] = q.get("description", "") + "\n\n" + note
    return q


def publish(p: dict, delivery: list, photos: list, build_meta: dict, mode="active") -> dict:
    """delivery: [(name, bytes)] files, photos: [(name, bytes)] jpgs. Returns {listing_id, url, state}."""
    p = _strip_text_claims(p)
    tok = token()
    shop_id = tok.get("shop_id") or get_shop(tok)["shop_id"]
    price = usd_to(tok.get("currency", "USD"), float(p["price_usd"]))
    data = {
        "quantity": 999,
        "title": p["title"][:140],
        "description": p["description"],
        "price": price,
        "who_made": "i_did",
        "when_made": _when_made(),
        "taxonomy_id": taxonomy_id(build_meta.get("taxonomy", []), build_meta.get("taxonomy_fallback_id", 2078)),
        "type": "download",
        "is_supply": bool(build_meta.get("is_supply")),
        "tags": _clean_tags(p.get("tags", [])),
        "should_auto_renew": True,
    }
    sec = config.settings().get("shop_section_id")
    if sec:
        data["shop_section_id"] = sec
    listing_id = p.get("etsy", {}).get("listing_id")
    if not listing_id:
        try:
            res = _create(shop_id, tok, data)
        except EtsyError as e:
            if "when_made" in str(e):
                data["when_made"] = "made_to_order"
                res = _create(shop_id, tok, data)
            else:
                raise
        listing_id = res["listing_id"]
        p.setdefault("etsy", {})["listing_id"] = listing_id
        storage.save_product(p)
    lid = listing_id
    existing = _req("GET", f"/listings/{lid}/images", tok).get("count", 0)
    if not existing:
        for rank, (name, data_bytes) in enumerate(photos[:10], 1):
            _req("POST", f"/shops/{shop_id}/listings/{lid}/images", tok,
                 files={"image": (name, data_bytes, "image/jpeg")}, data={"rank": rank}, timeout=300)
    have_files = _req("GET", f"/shops/{shop_id}/listings/{lid}/files", tok).get("count", 0)
    if not have_files:
        for rank, (name, data_bytes) in enumerate(delivery[:5], 1):
            if len(data_bytes) > 20 * 1024 * 1024:
                raise EtsyError(f"{name} 20 MB'tan büyük")
            ctype = "application/pdf" if name.endswith(".pdf") else "application/zip"
            _req("POST", f"/shops/{shop_id}/listings/{lid}/files", tok,
                 files={"file": (name, data_bytes, ctype)}, data={"name": name, "rank": rank}, timeout=600)
    state = "draft"
    if mode == "active":
        _req("PATCH", f"/shops/{shop_id}/listings/{lid}", tok, json={"state": "active"})
        state = "active"
    return {"listing_id": lid, "url": f"https://www.etsy.com/listing/{lid}", "state": state, "price": price,
            "currency": tok.get("currency", "USD")}
