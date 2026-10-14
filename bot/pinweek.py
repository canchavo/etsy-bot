"""Weekly Pinterest bulk-upload file (no Pinterest API approval needed).

Every week the bot picks published products, draws a 2:3 pin image for each, hosts the images on
the GitHub Pages site (panel/pins/) and writes Pinterest's bulk-create CSV with a publish date per
pin, spread over the coming week. The owner uploads the CSV once in Pinterest (Create > Bulk create
Pins) and the pins go out by themselves during the week."""
import csv
import datetime as dt
import io
import re
import time

from PIL import Image

from . import assets, config, social, storage, telegram
from .pinterest import BOARDS
from .telegram import esc

PINS_DIR = config.ROOT / "panel" / "pins"
HEADERS = ["Title", "Media URL", "Pinterest board", "Thumbnail", "Description", "Link", "Publish date", "Keywords"]
# good times for US buyers, in UTC: 14:00 (morning US), 19:00 (afternoon), 01:00 (evening)
SLOTS_UTC = [(14, 0), (19, 0), (1, 0)]
KEEP_DAYS = 30


def _slug(text, n=40):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n] or "pin"


def pick_products(n: int) -> list:
    """Published products, least-pinned and newest first, so every product gets turns."""
    pub = [p for p in storage.all_products() if p["status"] == "published" and p.get("etsy", {}).get("url")]
    pub.sort(key=lambda p: (len(p.get("pin_history", [])), -p.get("etsy", {}).get("published_at", 0)))
    out = []
    while pub and len(out) < n:
        out += pub[: n - len(out)]  # if there are fewer products than pins, products repeat (other image)
    return out


def _slots(count: int, start: dt.datetime) -> list:
    """count publish datetimes (UTC) spread over the 7 days after start."""
    per_day = max(1, -(-count // 7))
    slots = []
    day = (start + dt.timedelta(days=1)).date()
    while len(slots) < count:
        for h, m in SLOTS_UTC[:per_day]:
            when = dt.datetime.combine(day + dt.timedelta(days=1 if h < 6 else 0), dt.time(h, m))
            slots.append(when)
            if len(slots) >= count:
                break
        day += dt.timedelta(days=1)
    return slots


def _prune():
    if not PINS_DIR.exists():
        return
    cutoff = time.time() - KEEP_DAYS * 86400
    for f in PINS_DIR.glob("*.jpg"):
        if f.stat().st_mtime < cutoff:
            f.unlink()


def sync_titles():
    """Use the titles that are live on Etsy (they may have been edited there)."""
    import html
    from . import etsy
    try:
        live = {str(l["listing_id"]): html.unescape(l.get("title", "")) for l in etsy.shop_listings("active")}
    except Exception as e:
        print(f"[pinweek] Etsy başlıkları alınamadı: {e}")
        return 0
    n = 0
    for p in storage.all_products():
        t = live.get(str(p.get("etsy", {}).get("listing_id")))
        if t and p.get("title") != t:
            p["title"] = t
            storage.save_product(p)
            n += 1
    print(f"[pinweek] {n} ürün başlığı Etsy ile eşitlendi")
    return n


def build(n_pins=None, fresh=False):
    s = config.settings()
    sync_titles()
    if fresh:  # rebuild the last file from scratch: forget the dates it scheduled
        first = (storage.load_meta().get("pinweek", {}).get("first") or "9999")[:10]
        for p in storage.all_products():
            if p.get("pin_history"):
                p["pin_history"] = [d for d in p["pin_history"] if d < first]
                storage.save_product(p)
    n = int(n_pins or s.get("pins_per_week", 21))
    products = pick_products(n)
    if not products:
        raise RuntimeError("Henüz yayınlanmış ürün yok, pin dosyası oluşturulamadı.")
    PINS_DIR.mkdir(parents=True, exist_ok=True)
    _prune()
    base = config.pages_url() + "pins/"
    now = dt.datetime.utcnow()
    week = now.strftime("%Y-%m-%d")
    rows, previews, used = [], [], {}
    for when, p in zip(_slots(len(products), now), products):
        k = used.get(p["id"], 0) + len(p.get("pin_history", []))
        used[p["id"]] = used.get(p["id"], 0) + 1
        photos = [(nm, assets.download(p["id"], "photo__" + nm)) for nm in p["photos"]]
        ims = social._pick_photos(p, photos)
        ims = ims[k % len(ims):] + ims[:k % len(ims)]  # a different hero image each time the product repeats
        jpg = social.pin_image(p, ims)
        fname = f"{week}-{_slug(p['title'])}-{k}.jpg"
        (PINS_DIR / fname).write_bytes(jpg)
        texts = social.texts(p, p["etsy"]["url"])
        rows.append({
            "Title": texts["pin_title"],
            "Media URL": base + fname,
            "Pinterest board": BOARDS.get(p["type"], "Printable Wall Art"),
            "Thumbnail": "",
            "Description": texts["pin_desc"],
            "Link": p["etsy"]["url"],
            "Publish date": when.strftime("%Y-%m-%dT%H:%M:%S"),
            "Keywords": ", ".join(p.get("tags", [])[:10]),
        })
        p.setdefault("pin_history", []).append(when.strftime("%Y-%m-%d"))
        storage.save_product(p)
        if len(previews) < 4:
            previews.append((fname, jpg))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADERS)
    w.writeheader()
    w.writerows(rows)
    csv_bytes = buf.getvalue().encode("utf-8")
    meta = storage.load_meta()
    meta["pinweek"] = {"week": week, "rows": len(rows), "first": rows[0]["Publish date"], "last": rows[-1]["Publish date"]}
    storage.save_meta(meta)
    (PINS_DIR / "latest.csv").write_bytes(csv_bytes)
    return rows, csv_bytes, previews


def notify():
    """Send the CSV + instructions to Telegram (run after the Pages deploy finished)."""
    meta = storage.load_meta().get("pinweek", {})
    f = PINS_DIR / "latest.csv"
    if not f.exists():
        raise RuntimeError("Pin dosyası bulunamadı.")
    boards = "\n".join(f"• <code>{esc(b)}</code>" for b in dict.fromkeys(BOARDS.values()))
    telegram.document(f"pinterest-pinler-{meta.get('week', 'hafta')}.csv", f.read_bytes(),
                      f"📌 <b>Bu haftanın Pinterest pinleri</b>: {meta.get('rows', '?')} pin\n"
                      f"{esc(meta.get('first', '')[:10])} → {esc(meta.get('last', '')[:10])} arası kendiliğinden yayınlanacak.")
    telegram.send(
        "📥 <b>Yükleme (1 dk, bilgisayardan):</b>\n"
        "1) pinterest.com → <b>Oluştur</b> → <b>Toplu Pin oluştur</b> (Create → Bulk create Pins)\n"
        "2) <b>.csv yükle</b> deyip bu dosyayı seç → Yükle\n"
        "3) Pinler 'Planlanan Pinler' bölümüne düşer, tarihleri gelince yayınlanır.\n\n"
        f"Panolar bu adlarla hesapta olmalı:\n{boards}")


def run(n_pins=None, fresh=False):
    rows, _, previews = build(n_pins, fresh)
    print(f"[pinweek] {len(rows)} pin hazırlandı")
    try:
        telegram.album([(n, _jpg_small(b)) for n, b in previews],
                       f"🖼 Bu haftaki pinlerden örnekler ({len(rows)} pin hazırlanıyor, dosya birkaç dakika içinde gelecek)")
    except Exception as e:
        print(f"[pinweek] önizleme gönderilemedi: {e}")
    return rows


def _jpg_small(b):
    im = Image.open(io.BytesIO(b))
    im.thumbnail((700, 1050))
    out = io.BytesIO()
    im.convert("RGB").save(out, "JPEG", quality=85)
    return out.getvalue()
