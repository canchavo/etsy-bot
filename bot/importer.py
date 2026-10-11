"""One-time import of the products that the old Abacus system prepared (status pending).
Reads the old database (ABACUS_DATABASE_URL secret), downloads the images and
delivery files and adds them as pending products, then asks for approval on Telegram."""
import io
import time

import requests
from PIL import Image

from . import assets, config, mockups, research, storage, telegram
from .imgutil import jpeg_bytes, make_zips, thumb_b64, upscale

IMPORTED_LABEL = "Abacus'tan aktarılan ürün"


def _taxonomy(text):
    t = text.lower()
    if "recipe card" in t:
        return ["Recipe Cards"], 1314, False
    if "invitation" in t or "invite" in t:
        return ["Invitation Templates", "Invitations"], 1294, False
    if "planner" in t:
        return ["Planner Templates", "Planners"], 12476, False
    if any(k in t for k in ("clipart", "clip art", "svg", "sublimation", "png", "tumbler", "digital paper", "gift tag")):
        return ["Clip Art & Image Files"], 6844, True
    return ["Digital Prints"], 2078, False


def _get(url):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return r.content


def run():
    import psycopg2
    dsn = config.env("ABACUS_DATABASE_URL")
    if not dsn:
        raise RuntimeError("ABACUS_DATABASE_URL gizli anahtarı yok")
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute('select "productId", status, niche, title, description, tags, "priceUsd", images, "deliveryAssets", "deliveryFiles", "createdAt" '
                'from "Product" order by "createdAt"')
    rows = cur.fetchall()
    existing = {p.get("import_id") for p in storage.all_products()}
    done, skipped = [], []
    for (pid_old, status, niche, title, desc, tags, price, imgs, clean, files, created) in rows:
        if pid_old in existing:
            continue
        if status not in ("pending", "approved"):
            skipped.append(f"{pid_old} ({status})")
            continue
        if research.is_banned(f"{title} {niche}"):
            skipped.append(f"{pid_old}: Etsy kurallarına aykırı ({title[:40]})")
            continue
        try:
            photos = []
            for i, u in enumerate((imgs or [])[:8], 1):
                im = Image.open(io.BytesIO(_get(u))).convert("RGB")
                im.thumbnail((2400, 2400), Image.LANCZOS)
                photos.append((f"{i:02d}-photo.jpg", jpeg_bytes(im, 88, dpi=72)))
            delivery = []
            for u in files or []:
                try:
                    data = _get(u)
                    if len(data) < 20 * 1024 * 1024:
                        delivery.append((u.split("?")[0].rsplit("/", 1)[-1] or "files.zip", data))
                except Exception as e:
                    print(f"[import] teslimat dosyası indirilemedi ({e}), temiz tasarımlardan oluşturulacak")
            if not delivery:
                hi = []
                for i, u in enumerate((clean or [])[:10], 1):
                    im = Image.open(io.BytesIO(_get(u))).convert("RGB")
                    s = 5400 / max(im.size)
                    if s > 1:
                        im = upscale(im, int(im.width * s), int(im.height * s))
                    hi.append((f"design-{i:02d}.jpg", jpeg_bytes(im, 90)))
                if not hi:
                    raise RuntimeError("temiz tasarım dosyası yok")
                delivery = make_zips(research.slugify(title, 40), hi, f"{title}\n\nThank you for your purchase!\nHigh resolution 300 DPI files.\n")
            if not photos:
                raise RuntimeError("ilan görseli yok")
            tax_names, tax_id, supply = _taxonomy(f"{title} {niche}")
            day = time.strftime("%Y%m%d", time.gmtime(created.timestamp() if created else time.time()))
            pid = f"{day}-a{len(done) + 1:02d}"
            p = {
                "id": pid, "import_id": pid_old, "created_at": int(time.time()), "day": "abacus", "status": "pending",
                "type": "imported", "niche": niche or "", "title": (title or "")[:140], "description": desc or "",
                "tags": [t[:20] for t in (tags or [])][:13], "price_usd": float(price or 4.99) or 4.99,
                "build": {"taxonomy": tax_names, "taxonomy_fallback_id": tax_id, "is_supply": supply},
                "files": [{"name": n, "size": len(b)} for n, b in delivery[:5]],
                "photos": [n for n, _ in photos],
                "thumb": thumb_b64(Image.open(io.BytesIO(photos[0][1]))),
            }
            storage.add_event(p, f"Abacus'tan aktarıldı ({pid_old})")
            payload = {f"file__{n}": b for n, b in delivery[:5]}
            payload.update({f"photo__{n}": b for n, b in photos})
            assets.upload(pid, payload)
            storage.save_product(p)
            storage.commit_and_push(f"Aktarılan ürün {pid}")
            from .generator import approval_buttons, product_caption
            telegram.album(photos)
            telegram.send(product_caption(p), approval_buttons(pid))
            done.append(pid)
        except Exception as e:
            skipped.append(f"{pid_old}: {str(e)[:120]}")
    telegram.send(f"📥 Abacus aktarımı: {len(done)} ürün eklendi, {len(skipped)} atlandı." +
                  ("\n" + "\n".join("• " + telegram.esc(s) for s in skipped[:20]) if skipped else ""))
