"""Runs every few minutes: reads Telegram button presses / commands and publishes approved products."""
import time
import traceback

import requests

from . import assets, config, etsy, storage, telegram
from .telegram import esc

HELP = """🤖 <b>Etsy Bot komutları</b>
/durum – ürün sayıları ve Etsy bağlantısı
/bekleyen – onay bekleyen ürünleri tekrar gönder
/uret – şimdi 1 ek ürün üret (/uret 2 → 2 ürün)
/etsy – Etsy mağazanı bağla / yeniden bağla
/kod &lt;adres&gt; – Etsy onayından sonra çıkan adresi gönder
/panel – web panel adresi
/yardim – bu mesaj"""


def _status_line(p):
    icons = {"pending": "⏳", "approved": "🟡", "publishing": "🟡", "published": "✅", "rejected": "❌", "failed": "⚠️"}
    return f"{icons.get(p['status'], '•')} <code>{p['id']}</code> {esc(p['title'][:60])}"


def publish_product(p: dict) -> str:
    """Publish one product to Etsy. Returns a Turkish status text."""
    p["status"] = "publishing"
    storage.save_product(p)
    delivery = [(f["name"], assets.download(p["id"], "file__" + f["name"])) for f in p["files"]]
    photos = [(n, assets.download(p["id"], "photo__" + n)) for n in p["photos"]]
    mode = config.settings().get("publish_mode", "active")
    res = etsy.publish(p, delivery, photos, p["build"], mode=mode)
    p["status"] = "published"
    p["etsy"] = {**p.get("etsy", {}), **res, "published_at": int(time.time())}
    storage.add_event(p, f"Etsy'de yayınlandı ({res['state']})")
    storage.save_product(p)
    return res


def _handle_callback(cb, meta):
    data = cb.get("data", "")
    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    mid = msg.get("message_id")
    action, _, pid = data.partition(":")
    p = storage.load_product(pid)
    if not p:
        telegram.answer(cb["id"], "Ürün bulunamadı")
        return False
    base_text = msg.get("text", p["title"])
    for marker in ("\n\n✅", "\n\n⚠️", "\n\n🟡", "\n\n❌"):
        base_text = base_text.split(marker)[0]
    base_html = esc(base_text)
    if action == "desc":
        telegram.answer(cb["id"])
        telegram.send(f"<b>{esc(p['title'])}</b>\n\n{esc(p['description'])[:3800]}")
        return False
    if action == "files":
        telegram.answer(cb["id"], "Dosyalar gönderiliyor…")
        try:
            for f in p["files"]:
                data = assets.download(pid, "file__" + f["name"])
                telegram.document(f["name"], data, f"📦 {esc(p['title'][:80])}")
        except Exception as e:
            telegram.send(f"⚠️ Dosyalar gönderilemedi: <code>{esc(str(e)[:300])}</code>")
        return False
    if action == "no":
        if p["status"] == "published":
            telegram.answer(cb["id"], "Bu ürün zaten yayınlandı")
            return False
        p["status"] = "rejected"
        storage.add_event(p, "reddedildi")
        storage.save_product(p)
        try:
            assets.delete_all(pid)
        except Exception as e:
            print(f"[poll] dosyalar silinemedi: {e}")
        telegram.answer(cb["id"], "Reddedildi")
        telegram.edit(chat_id, mid, base_html + "\n\n❌ <b>Reddedildi</b>")
        return True
    if action in ("ok", "retry"):
        if p["status"] == "published":
            telegram.answer(cb["id"], "Zaten yayınlandı")
            return False
        if p["status"] == "rejected":
            telegram.answer(cb["id"], "Bu ürün reddedilmişti")
            return False
        telegram.answer(cb["id"], "Etsy'ye gönderiliyor…")
        telegram.edit(chat_id, mid, base_html + "\n\n🟡 <b>Etsy'ye yükleniyor…</b>")
        p["status"] = "approved"
        storage.add_event(p, "onaylandı")
        storage.save_product(p)
        try:
            res = publish_product(p)
            state_tr = "yayında" if res["state"] == "active" else "taslak olarak kaydedildi"
            telegram.edit(chat_id, mid, base_html + f"\n\n✅ <b>Etsy'de {state_tr}</b> – {res['price']} {res['currency']}",
                          [[("🔗 Etsy'de aç", res["url"])]])
        except Exception as e:
            traceback.print_exc()
            p = storage.load_product(pid)
            p["status"] = "failed"
            p.setdefault("etsy", {})["error"] = str(e)[:500]
            storage.add_event(p, f"yayın hatası: {str(e)[:200]}")
            storage.save_product(p)
            telegram.edit(chat_id, mid, base_html + f"\n\n⚠️ <b>Yayınlanamadı:</b> <code>{esc(str(e)[:600])}</code>",
                          [[("🔁 Tekrar dene", f"retry:{pid}"), ("❌ Reddet", f"no:{pid}")]])
        return True
    telegram.answer(cb["id"])
    return False


def _dispatch_generate(count=None):
    if not (config.GITHUB_TOKEN and config.GITHUB_REPOSITORY):
        raise RuntimeError("GitHub ortamı yok")
    inputs = {"count": str(count)} if count else {}
    r = requests.post(
        f"https://api.github.com/repos/{config.GITHUB_REPOSITORY}/actions/workflows/daily.yml/dispatches",
        headers={"Authorization": f"Bearer {config.GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
        json={"ref": config.env("GITHUB_REF_NAME", "main"), "inputs": inputs}, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")


def _handle_message(m, meta):
    text = (m.get("text") or "").strip()
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    changed = False
    if cmd in ("/start", "/yardim", "/help"):
        telegram.send(HELP)
    elif cmd == "/durum":
        ps = storage.all_products()
        counts = {}
        for p in ps:
            counts[p["status"]] = counts.get(p["status"], 0) + 1
        tok = storage.load_etsy()
        etsy_line = (f"🟢 Etsy bağlı: {esc(tok.get('shop_name') or str(tok.get('shop_id')))}" if tok.get("refresh_token")
                     else "🔴 Etsy bağlı değil – /etsy yazın")
        lines = [f"📊 Toplam {len(ps)} ürün", *(f"• {k}: {v}" for k, v in sorted(counts.items())), etsy_line]
        last = [p for p in ps][-8:]
        if last:
            lines += ["", "Son ürünler:"] + [_status_line(p) for p in last]
        telegram.send("\n".join(lines))
    elif cmd == "/bekleyen":
        from .generator import approval_buttons, product_caption
        pend = [p for p in storage.all_products() if p["status"] in ("pending", "failed")]
        if not pend:
            telegram.send("Onay bekleyen ürün yok 👍")
        for p in pend[-10:]:
            telegram.send(product_caption(p), approval_buttons(p["id"]) if p["status"] == "pending"
                          else [[("🔁 Tekrar dene", f"retry:{p['id']}"), ("❌ Reddet", f"no:{p['id']}")]])
    elif cmd == "/uret":
        try:
            n = int(arg) if arg.strip().isdigit() else 1  # extra production: 1 product by default
            _dispatch_generate(n)
            telegram.send(f"🚀 {n} ürünlük ek üretim başlatıldı. Hazır olunca buraya gelecek (ürün başına ~5-8 dk).")
        except Exception as e:
            telegram.send(f"⚠️ Üretim başlatılamadı: <code>{esc(str(e))}</code>")
    elif cmd == "/etsy":
        try:
            url = etsy.auth_url()
            telegram.send(
                "🔗 <b>Etsy bağlantısı</b>\n\n1) Aşağıdaki butona basın ve Etsy'de <b>Allow access</b> deyin.\n"
                "2) Açılan sayfadaki <b>kopyala</b> butonuyla adresi kopyalayın.\n"
                "3) Buraya <code>/kod </code> yazıp yapıştırın ve gönderin.\n\n"
                "Daha hızlısı: GitHub'da <i>Etsy bağla</i> işini çalıştırıp adresi oraya yapıştırabilirsiniz.",
                [[("Etsy'de izin ver", url)]])
        except Exception as e:
            telegram.send(f"⚠️ {esc(str(e))}")
    elif cmd == "/kod":
        try:
            tok = etsy.exchange(arg)
            telegram.send(f"🟢 Etsy bağlandı: <b>{esc(tok.get('shop_name') or str(tok['shop_id']))}</b> ({tok.get('currency')})")
            changed = True
        except Exception as e:
            telegram.send(f"⚠️ Etsy bağlanamadı: <code>{esc(str(e)[:500])}</code>\nKod birkaç dakikada geçersiz olabilir; /etsy ile tekrar deneyin.")
    elif cmd == "/panel":
        telegram.send(f"🌐 Panel: {config.pages_url() or 'henüz yok'}")
    return changed


def run(loop_seconds=0):
    """Process Telegram updates. With loop_seconds>0 keep long-polling so buttons react
    within seconds; state is pushed to git after every batch of changes."""
    deadline = time.time() + loop_seconds
    any_change = False
    while True:
        remaining = deadline - time.time()
        changed = _run_once(wait=max(0, min(25, remaining)) if loop_seconds else 0)
        if changed:
            any_change = True
            if loop_seconds:
                storage.commit_and_push("Telegram işlemleri")
        if time.time() >= deadline:
            break
    n = telegram.conflicts()
    print(f"[poll] çakışma sayısı: {n}", flush=True)
    if n >= 3:
        meta = storage.load_meta()
        if meta.get("conflict_warned", 0) < time.time() - 6 * 3600:
            meta["conflict_warned"] = int(time.time())
            storage.save_meta(meta)
            any_change = True
            try:
                telegram.send("⚠️ <b>Bu bota başka bir program da bağlı</b> (muhtemelen eski Abacus otomasyonu). "
                              "Mesajlarınızı ve buton basışlarınızı o alıyor, bu yüzden ben cevap veremiyorum.\n\n"
                              "Çözüm: Abacus'taki eski görevi/agent'ı durdurun veya silin.")
            except Exception as e:
                print(f"[poll] uyarı gönderilemedi: {e}")
    return any_change


def _run_once(wait=0):
    meta = storage.load_meta()
    offset = meta.get("tg_offset", 0)
    changed = False
    ups = telegram.updates(offset, wait)
    for u in ups:
        offset = max(offset, u["update_id"] + 1)
        meta["tg_offset"] = offset
        storage.save_meta(meta)  # never process the same update twice
        changed = True
        try:
            src = u.get("callback_query") or u.get("message") or {}
            chat = (src.get("message", {}).get("chat", {}) if "callback_query" in u else src.get("chat", {}))
            if str(chat.get("id")) != str(config.TELEGRAM_CHAT_ID):
                print(f"[poll] yabancı sohbet yok sayıldı: {chat.get('id')}")
                continue
            if "callback_query" in u:
                changed |= _handle_callback(u["callback_query"], meta)
            elif "message" in u:
                changed |= _handle_message(u["message"], meta)
        except Exception as e:
            traceback.print_exc()
            try:
                telegram.send(f"⚠️ Hata: <code>{esc(str(e)[:500])}</code>")
            except Exception:
                pass
    if meta.get("last_keepalive", 0) > time.time() - 3600:
        return changed
    meta["last_keepalive"] = int(time.time())
    storage.save_meta(meta)
    try:
        if etsy.keepalive():
            changed = True
            if meta.pop("etsy_warned", None):
                storage.save_meta(meta)
    except Exception as e:
        print(f"[poll] Etsy oturum yenileme: {e}")
        if not meta.get("etsy_warned"):
            telegram.send(f"⚠️ Etsy oturumu yenilenemedi, /etsy ile yeniden bağlayın.\n<code>{esc(str(e)[:300])}</code>")
            meta["etsy_warned"] = int(time.time())
            storage.save_meta(meta)
    return changed
