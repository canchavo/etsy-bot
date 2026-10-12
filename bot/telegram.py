"""Minimal Telegram Bot API client (HTML parse mode)."""
import html
import json
import time

import requests

from . import config

esc = html.escape


def _url(method):
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def call(method, data=None, files=None, timeout=60):
    if not config.TELEGRAM_BOT_TOKEN:
        print(f"[telegram:{method}] (token yok) {str(data)[:300]}")
        return {}
    for attempt in range(4):
        try:
            r = requests.post(_url(method), data=data, files=files, timeout=timeout)
            j = r.json()
            if j.get("ok"):
                return j["result"]
            if r.status_code == 429:
                time.sleep(int(j.get("parameters", {}).get("retry_after", 5)) + 1)
                continue
            # message unchanged etc. are harmless
            if "message is not modified" in j.get("description", ""):
                return {}
            raise RuntimeError(f"Telegram {method}: {j.get('description')}")
        except requests.RequestException as e:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))
    return {}


def kb(rows):
    return json.dumps({"inline_keyboard": [[{"text": t, "callback_data": d} if not d.startswith("http") else {"text": t, "url": d}
                                            for t, d in row] for row in rows]})


def send(text, buttons=None, chat_id=None, preview=False):
    data = {"chat_id": chat_id or config.TELEGRAM_CHAT_ID, "text": text[:4096], "parse_mode": "HTML",
            "disable_web_page_preview": "false" if preview else "true"}
    if buttons:
        data["reply_markup"] = kb(buttons)
    return call("sendMessage", data)


def edit(chat_id, message_id, text, buttons=None):
    data = {"chat_id": chat_id, "message_id": message_id, "text": text[:4096], "parse_mode": "HTML",
            "disable_web_page_preview": "true", "reply_markup": kb(buttons or [])}
    return call("editMessageText", data)


def answer(callback_id, text=""):
    try:
        call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190]})
    except Exception as e:
        print(f"[telegram] answerCallbackQuery: {e}")


def album(photos, caption=""):
    """photos: [(name, jpeg bytes)] -> sends up to 10 as one album."""
    photos = photos[:10]
    if not photos:
        return []
    if len(photos) == 1:
        return [call("sendPhoto", {"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption[:1024], "parse_mode": "HTML"},
                     files={"photo": photos[0]})]
    media, files = [], {}
    for i, (name, data) in enumerate(photos):
        key = f"p{i}"
        files[key] = (name, data, "image/jpeg")
        item = {"type": "photo", "media": f"attach://{key}"}
        if i == 0 and caption:
            item.update({"caption": caption[:1024], "parse_mode": "HTML"})
        media.append(item)
    return call("sendMediaGroup", {"chat_id": config.TELEGRAM_CHAT_ID, "media": json.dumps(media)}, files=files, timeout=180)


def updates(offset, wait=0):
    try:
        return call("getUpdates", {"offset": offset, "timeout": int(wait),
                                   "allowed_updates": json.dumps(["message", "callback_query"])}, timeout=int(wait) + 30) or []
    except RuntimeError as e:
        if "Conflict" not in str(e):
            raise
        print(f"[telegram] ÇAKIŞMA: {e}", flush=True)
        _CONFLICTS[0] += 1
        if "webhook" in str(e).lower():
            # an old system (e.g. Abacus) registered a webhook and steals every message -> take the bot back
            try:
                info = call("getWebhookInfo")
                print(f"[telegram] eski webhook: {info.get('url', '')[:60]}… kaldırılıyor", flush=True)
                call("deleteWebhook", {"drop_pending_updates": "false"})
            except Exception as e2:
                print(f"[telegram] webhook kaldırılamadı: {e2}", flush=True)
        time.sleep(3)
        return []


_CONFLICTS = [0]


def conflicts():
    return _CONFLICTS[0]


def document(name, data, caption=""):
    return call("sendDocument", {"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption[:1024], "parse_mode": "HTML"},
                files={"document": (name, data)}, timeout=300)
