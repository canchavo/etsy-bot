"""One-off maintenance: shorten long, keyword-stuffed titles of active Etsy listings
(Etsy's 'make your titles clearer' recommendation)."""
import html

from . import etsy, research, storage, telegram
from .telegram import esc


def run(dry_run=False):
    listings = etsy.shop_listings("active")
    todo = []
    for l in listings:
        title = html.unescape(l.get("title", ""))
        if research.title_problems(title):
            todo.append({"id": str(l["listing_id"]), "title": title, "tags": [html.unescape(t) for t in l.get("tags", [])]})
    print(f"[retitle] {len(listings)} aktif ilan, {len(todo)} tanesinin başlığı uzun/karışık")
    if not todo:
        telegram.send("✅ Tüm ilan başlıkları zaten kısa ve net.")
        return []
    new = research.short_titles(todo)
    by_listing = {str(p.get("etsy", {}).get("listing_id")): p for p in storage.all_products() if p.get("etsy")}
    done, failed = [], []
    for item in todo:
        t = new.get(item["id"])
        if not t:
            failed.append((item, "yeni başlık üretilemedi"))
            continue
        print(f"[retitle] {item['id']}: {item['title']!r} -> {t!r}")
        if dry_run:
            done.append((item, t))
            continue
        try:
            etsy.update_title(item["id"], t)
            done.append((item, t))
            p = by_listing.get(item["id"])
            if p:
                p["title"] = t
                storage.add_event(p, "başlık kısaltıldı (Etsy önerisi)")
                storage.save_product(p)
        except Exception as e:
            failed.append((item, str(e)[:200]))
    head = "🧪 <b>Başlık önizlemesi (değiştirilmedi)</b>" if dry_run else "✏️ <b>İlan başlıkları güncellendi</b>"
    lines = [f"{head}: {len(done)}/{len(todo)}"]
    for item, t in done[:25]:
        lines.append(f"• <s>{esc(item['title'][:70])}</s>\n   → <b>{esc(t)}</b>")
    for item, err in failed[:10]:
        lines.append(f"⚠️ {esc(item['title'][:60])}: {esc(err)}")
    msg = "\n".join(lines)
    for i in range(0, len(msg), 3900):
        telegram.send(msg[i:i + 3900])
    return done
