"""Read-only check of an old (Abacus) product's delivery files: what does the buyer actually get?"""
import io
import re
import zipfile

import requests
from PIL import Image

from . import config, telegram
from .telegram import esc

Image.MAX_IMAGE_PIXELS = None


def _get(url):
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    return r.content


def _describe(name, data):
    low = name.lower()
    if low.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
        try:
            im = Image.open(io.BytesIO(data))
            dpi = im.info.get("dpi", (None, None))[0]
            w, h = im.size
            at300 = f"{w / 300 * 2.54:.0f}x{h / 300 * 2.54:.0f} cm @300dpi"
            return f"{name}: {w}x{h}px, dpi={round(dpi) if dpi else '-'}, {len(data) / 1e6:.1f} MB → {at300}"
        except Exception as e:
            return f"{name}: görsel açılamadı ({e})"
    if low.endswith(".pdf"):
        boxes = re.findall(rb"/MediaBox\s*\[\s*([\d.\s-]+)\]", data)
        pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
        imgs = re.findall(rb"/Width\s+(\d+)\s*/Height\s+(\d+)|/Height\s+(\d+)\s*/Width\s+(\d+)", data)
        size = ""
        if boxes:
            v = [float(x) for x in boxes[0].split()[:4]]
            size = f"{(v[2] - v[0]) / 72 * 2.54:.1f}x{(v[3] - v[1]) / 72 * 2.54:.1f} cm"
        dims = []
        for m in imgs[:3]:
            w, h = (m[0], m[1]) if m[0] else (m[3], m[2])
            dims.append(f"{int(w)}x{int(h)}px")
        return f"{name}: PDF {pages} sayfa, sayfa {size}, gömülü görsel {', '.join(dims) or '?'}, {len(data) / 1e6:.1f} MB"
    return f"{name}: {len(data) / 1e3:.0f} KB"


def describe_blob(name, data, depth=0):
    if name.lower().endswith(".zip") and depth < 2:
        z = zipfile.ZipFile(io.BytesIO(data))
        lines = [f"📦 {name} ({len(data) / 1e6:.2f} MB, {len(z.namelist())} dosya)"]
        for n in z.namelist():
            if n.endswith("/"):
                continue
            lines += ["   " + l for l in describe_blob(n, z.read(n), depth + 1)]
        return lines
    return [_describe(name, data)]


def run(query: str):
    import psycopg2
    dsn = config.env("ABACUS_DATABASE_URL")
    if not dsn:
        raise RuntimeError("ABACUS_DATABASE_URL yok")
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute('select "productId", status, title, "deliveryFiles", "deliveryAssets" from "Product" '
                'where title ilike %s order by "createdAt"', (f"%{query}%",))
    rows = cur.fetchall()
    if not rows:
        telegram.send(f"🔎 Abacus kayıtlarında '{esc(query)}' bulunamadı.")
        return []
    report = []
    for pid, status, title, files, clean in rows:
        report.append(f"🔎 <b>{esc(title)}</b> ({esc(str(status))})")
        for u in files or []:
            name = u.split("?")[0].rsplit("/", 1)[-1] or "file"
            try:
                report += [esc(l) for l in describe_blob(name, _get(u))]
            except Exception as e:
                report.append(f"⚠️ {esc(name)} indirilemedi: {esc(str(e)[:120])}")
        for u in (clean or [])[:6]:
            name = "temiz-tasarım:" + (u.split("?")[0].rsplit("/", 1)[-1] or "img")
            try:
                report.append(esc(_describe(name + ".png", _get(u))))
            except Exception as e:
                report.append(f"⚠️ {esc(name)}: {esc(str(e)[:120])}")
    text = "\n".join(report)
    print(text)
    for i in range(0, len(text), 3800):
        telegram.send(text[i:i + 3800])
    return report
