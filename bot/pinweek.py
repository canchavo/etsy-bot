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
    """After a new week's pins are built: short note (pins arrive in Telegram 3 a day)."""
    meta = storage.load_meta()
    pw = meta.get("pinweek", {})
    meta["pin_cursor"] = 0
    storage.save_meta(meta)
    telegram.send(f"📌 <b>Bu haftanın {pw.get('rows', '?')} Pinterest pini hazır.</b>\n"
                  "Her gün 17:00'de 3 tanesi buraya hazır gelecek: görseli kaydet, başlık/açıklama/linki yapıştır, "
                  "panoyu seç, yayınla. Hemen istersen /pin yaz.")


def send_daily(n=3):
    """Send the next n pins of this week's list to Telegram, ready to post by hand."""
    f = PINS_DIR / "latest.csv"
    if not f.exists():
        raise RuntimeError("Bu haftanın pin listesi yok, /pinler ile oluşturun.")
    rows = list(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8"))))
    meta = storage.load_meta()
    cur = int(meta.get("pin_cursor", 0))
    batch = rows[cur:cur + n]
    if not batch:
        telegram.send("📌 Bu haftanın pinleri bitti. Pazartesi yenileri gelecek (hemen istersen /pinler).")
        return 0
    for k, r in enumerate(batch, cur + 1):
        img = PINS_DIR / r["Media URL"].rsplit("/", 1)[-1]
        cap = (f"📌 <b>Pin {k}/{len(rows)}</b>  •  Pano: <b>{esc(r['Pinterest board'])}</b>\n\n"
               f"<b>Başlık:</b>\n<code>{esc(r['Title'])}</code>\n\n"
               f"<b>Açıklama:</b>\n<code>{esc(r['Description'][:600])}</code>\n\n"
               f"<b>Bağlantı:</b>\n<code>{esc(r['Link'])}</code>")[:1024]
        if img.exists():
            telegram.call("sendPhoto", {"chat_id": config.TELEGRAM_CHAT_ID, "caption": cap, "parse_mode": "HTML"},
                          files={"photo": (img.name, img.read_bytes(), "image/jpeg")}, timeout=120)
        else:
            telegram.send(cap + f"\n\nGörsel: {esc(r['Media URL'])}")
    meta["pin_cursor"] = cur + len(batch)
    storage.save_meta(meta)
    left = len(rows) - meta["pin_cursor"]
    telegram.send("👆 Pinterest'te: <b>Oluştur → Pin oluşturun</b> → görseli yükle → kutulara yapıştır → panoyu seç → Yayınla."
                  + (f"\n({left} pin bu hafta sırada)" if left else ""))
    return len(batch)


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
