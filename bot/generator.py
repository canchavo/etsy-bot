"""Daily run: research niches, build products, store them and ask for approval on Telegram."""
import datetime as dt
import time
import traceback
from zoneinfo import ZoneInfo

from . import assets, config, images, research, storage, telegram
from .products import TYPES, type_label
from .telegram import esc


def notify(text):
    try:
        telegram.send(text)
    except Exception as e:
        print(f"[generate] Telegram mesajı gönderilemedi: {e}")


def today_local():
    return dt.datetime.now(ZoneInfo(config.settings()["timezone"])).date()


def compose_description(spec: dict, built: dict) -> str:
    def section(title, lines):
        return title + "\n" + "\n".join(f"• {l}" for l in lines)

    parts = [spec["intro"].strip()]
    parts.append(section("WHAT'S INCLUDED", built["included"]))
    parts.append(section("FILE DETAILS", built["details"]))
    parts.append(section("HOW TO USE", built["usage"]))
    parts.append(section("PLEASE NOTE", [
        "This is a digital download. No physical item will be shipped.",
        "Your files are available right after purchase under Purchases & Reviews.",
        "Colors may vary slightly between screens and printers.",
        "Artwork created with the help of AI tools, then curated, edited and prepared for print by our shop.",
        built["license"],
    ]))
    return "\n\n".join(parts)


def used_niches(days):
    cutoff = time.time() - days * 86400
    return [p["niche"] for p in storage.all_products() if p.get("created_at", 0) >= cutoff and p.get("niche")]


def next_id(day: dt.date):
    prefix = day.strftime("%Y%m%d")
    existing = [p["id"] for p in storage.all_products() if p["id"].startswith(prefix)]
    return f"{prefix}-{len(existing) + 1:02d}"


def product_caption(p: dict) -> str:
    t = type_label(p["type"])
    lines = [
        f"🆕 <b>{esc(p['title'])}</b>",
        "",
        f"📦 Tür: {esc(t)}",
        f"🎯 Niş: {esc(p['niche'])}",
        f"💵 Fiyat: ${p['price_usd']:.2f}",
    ]
    if p.get("research", {}).get("etsy_results") is not None:
        r = p["research"]
        lines.append(f"📊 Etsy: {r['etsy_results']:,} rakip ilan, ilk 25'te ortanca {int(r.get('etsy_median_favs', 0))} favori")
    lines.append(f"🏷 {esc(', '.join(p['tags']))}")
    files = "\n".join(f"  • <code>{esc(f['name'])}</code> ({f['size'] / 1048576:.1f} MB)" for f in p["files"])
    lines.append(f"📁 Teslimat dosyaları:\n{files}")
    lines.append(f"\n<code>{p['id']}</code>")
    return "\n".join(lines)


def approval_buttons(pid):
    return [[("✅ Onayla ve yayınla", f"ok:{pid}"), ("❌ Reddet", f"no:{pid}")],
            [("📝 Açıklama", f"desc:{pid}"), ("📦 Dosyaları gönder", f"files:{pid}")]]


def build_one(idea: dict, day: dt.date) -> dict:
    spec = research.product_spec(idea)
    pid = next_id(day)
    slug = research.slugify(spec.get("title"), 40)
    mod = TYPES[idea["type"]]
    t0 = time.time()
    built = mod.build(spec, slug)
    p = {
        "id": pid,
        "created_at": int(time.time()),
        "day": day.isoformat(),
        "status": "pending",
        "type": idea["type"],
        "niche": idea["niche"],
        "research": {k: idea.get(k) for k in ("search_query", "why", "etsy_results", "etsy_median_favs", "score")},
        "title": spec["title"],
        "description": compose_description(spec, built),
        "tags": spec["tags"],
        "price_usd": spec["price_usd"],
        "spec": spec,
        "build": {k: built[k] for k in ("taxonomy", "taxonomy_fallback_id", "is_supply")},
        "files": [{"name": n, "size": len(b)} for n, b in built["delivery"]],
        "photos": [n for n, _ in built["mockups"]],
        "thumb": built["thumb"],
        "build_seconds": int(time.time() - t0),
    }
    storage.add_event(p, "oluşturuldu")
    payload = {f"file__{n}": b for n, b in built["delivery"]}
    payload.update({f"photo__{n}": b for n, b in built["mockups"]})
    assets.upload(pid, payload)
    storage.save_product(p)
    storage.commit_and_push(f"Yeni ürün {pid}")
    # Telegram: photos + approval message
    try:
        telegram.album(built["mockups"])
        telegram.send(product_caption(p), approval_buttons(pid))
    except Exception as e:
        print(f"[generate] Telegram gönderilemedi: {e}")
    return p


def run(count=None, force=False):
    s = config.settings()
    day = today_local()
    target = int(count or s["products_per_day"])
    already = [p for p in storage.all_products() if p.get("day") == day.isoformat()]
    if not force and not count:
        target = max(0, target - len(already))
    if target == 0:
        print("[generate] Bugünün ürünleri zaten hazır.")
        notify("ℹ️ Bugünün ürünleri zaten hazır. Ek ürün için /uret 1 yazın.")
        return []
    notify(f"🔎 Günlük üretim başladı: {target} ürün hazırlanıyor… (genellikle 15-30 dk)")
    try:
        chosen, reserve = research.pick_niches(target, used_niches(s["niche_memory_days"]), day)
    except Exception as e:
        notify(f"⚠️ Araştırma adımı başarısız: <code>{esc(str(e)[:500])}</code>\n{config.GITHUB_RUN_URL}")
        raise
    queue = chosen + reserve
    made, failed = [], []
    while queue and len(made) < target:
        idea = queue.pop(0)
        if any(m["type"] == idea["type"] for m in made) and sum(m["type"] == idea["type"] for m in made) >= s["max_same_type_per_day"]:
            continue
        print(f"[generate] → {idea['type']}: {idea['niche']}")
        try:
            made.append(build_one(idea, day))
        except Exception as e:
            traceback.print_exc()
            failed.append(f"{idea['niche']} ({idea['type']}): {str(e)[:180]}")
            if len(failed) >= target + 3:
                break
            if "Görsel üretilemedi" in str(e) and images.stats["cloudflare"] == 0 and images.stats["pollinations"] == 0 and len(failed) >= 2:
                break  # image providers are down, no point in trying more
    summary = [f"📋 <b>Günlük özet ({day.isoformat()})</b>: {len(made)}/{target} ürün hazırlandı."]
    if made:
        summary.append("Onay bekleyen ürünler yukarıda. ✅ ile onaylarsanız Etsy'de yayınlanır.")
    if failed:
        summary.append("\n⚠️ Başarısız denemeler:\n" + "\n".join(f"• {esc(f)}" for f in failed[:6]))
    summary.append(f"\n🖼 Görsel: Cloudflare {images.stats['cloudflare']}, Pollinations {images.stats['pollinations']}, hata {images.stats['failed']}")
    if config.pages_url():
        summary.append(f"🌐 Panel: {config.pages_url()}")
    notify("\n".join(summary))
    if not made:
        raise RuntimeError("Hiç ürün üretilemedi")
    return made
