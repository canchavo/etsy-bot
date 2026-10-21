"""Niche research: the AI proposes ideas, Etsy's public search data scores them."""
import datetime as dt
import math
import random
import re
import statistics

from . import config, etsy, llm
from .products import TYPES

BANNED = [
    # Etsy prohibits AI prompt products; trademarks/IP get listings removed
    "prompt", "chatgpt", "midjourney", "dall-e", "dalle", "openai", "canva", "cricut", "disney", "marvel", "pixar",
    "pokemon", "harry potter", "hogwarts", "star wars", "barbie", "bluey", "taylor swift", "swiftie", "nfl", "nba",
    "stanley", "hello kitty", "sanrio", "minecraft", "fortnite", "mickey", "minnie", "frozen", "grinch", "snoopy",
    "peanuts", "sesame", "paw patrol", "spongebob", "lego", "nike", "louis vuitton", "chanel", "gucci", "coca",
    "starbucks", "barbie", "labubu", "stitch", "wednesday addams", "beetlejuice", "jack skellington", "nightmare before",
    "studio ghibli", "ghibli", "anime character", "goodnotes", "notability", "svg", "cut file",
]

SEASONS = [
    (1, 15, "Valentine's Day (Feb 14)"), (2, 20, "St. Patrick's Day (Mar 17)"), (3, 1, "Easter and spring"),
    (4, 1, "Mother's Day (May)"), (5, 1, "Father's Day (June) and graduation"), (5, 20, "summer, 4th of July"),
    (7, 1, "back to school"), (8, 1, "fall / autumn decor"), (8, 20, "Halloween"), (9, 25, "Thanksgiving"),
    (10, 1, "Christmas, winter and holiday season"), (11, 15, "New Year, winter"), (12, 15, "Valentine's Day, winter"),
]


def is_banned(text: str) -> bool:
    t = (text or "").lower()
    return any(b in t for b in BANNED)


def season_hint(today: dt.date) -> str:
    upcoming = []
    for m, d, name in SEASONS:
        start = dt.date(today.year, m, d)
        delta = (start - today).days
        if -45 <= delta <= 50:
            upcoming.append(name)
    if not upcoming:
        upcoming = ["evergreen home decor and gifts"]
    return ", ".join(dict.fromkeys(upcoming))


def winners(max_n=5) -> list:
    """Best-selling listings of our own shop (refreshed once a day, cached in meta)."""
    import time
    from . import storage
    meta = storage.load_meta()
    cache = meta.get("winners", {})
    if time.time() - cache.get("at", 0) > 20 * 3600:
        try:
            sold = etsy.sold_listings()
            cache = {"at": int(time.time()), "items": sorted(sold.values(), key=lambda x: -x["sales"])[:max_n]}
            meta["winners"] = cache
            storage.save_meta(meta)
        except Exception as e:
            print(f"[research] satış verisi alınamadı: {e}")
    return cache.get("items", [])


def _winner_block(win, n_ideas):
    if not win:
        return ""
    lines = "\n".join(f'- "{w["title"]}" ({w["sales"]} sale{"s" if w["sales"] > 1 else ""})' for w in win)
    k = max(1, n_ideas // 3)
    return f"""
PROVEN BEST SELLERS in our own shop (real buyers paid for these):
{lines}
Make about {k} of the ideas CLOSE VARIATIONS of these best sellers: same buyer, same room/use and product type,
but a clearly different theme, region, season, colorway or art style (e.g. a best-selling "vintage Italian kitchen
wall art" -> "vintage French bistro kitchen prints", "Greek island kitchen wall art", "lemon & olive Mediterranean
kitchen prints"). Never copy the original. For these ideas add "variation_of": "<best seller title>".
"""


def _candidates(n_ideas, used, today):
    types_desc = "\n".join(f'- "{k}": {m.LABEL_TR}' for k, m in TYPES.items() if k in config.settings()["product_types"])
    prompt = f"""You are an expert Etsy digital-products researcher.
Today is {today.isoformat()}. Buyers shop 3-8 weeks ahead, so focus on: {season_hint(today)}, plus some evergreen ideas.

Propose {n_ideas} DIFFERENT digital product ideas that sell well on Etsy right now and that our system can produce.
Our system can only make these product types (AI generated artwork):
{types_desc}

Rules:
- Each idea must be a specific, buyer-oriented niche (style + theme), not generic. e.g. "vintage botanical mushroom prints", "cute kawaii Christmas animals coloring pages for kids".
- No trademarks, brands, celebrities, characters, sports teams, franchises, logos, or copyrighted styles.
- No AI prompt products, no SVG/cut files, no templates that need Canva.
- The artwork is AI generated and CANNOT contain readable text: never propose quotes, sayings, typography, lettering, names, monograms, calendars or anything that depends on words. Focus on illustration, painting, pattern and character based designs.
- Avoid these niches we already used recently: {', '.join(used) or 'none'}.
- Mix product types.
{_winner_block(winners(), n_ideas)}
Return JSON: {{"ideas": [{{"niche": "...", "type": "one of {list(TYPES)}", "search_query": "2-4 words a buyer types into Etsy search", "why": "short reason", "variation_of": "optional"}}]}}"""
    data = llm.ask_json(prompt, temperature=1.0)
    ideas = data.get("ideas", data if isinstance(data, list) else [])
    out = []
    for i in ideas:
        if not isinstance(i, dict) or i.get("type") not in TYPES:
            continue
        if is_banned(i.get("niche", "") + " " + i.get("search_query", "")):
            continue
        out.append(i)
    return out


def _score(idea):
    """Demand (favorites of top results) vs. competition (number of results)."""
    try:
        res = etsy.search_active(idea["search_query"])
        count = int(res.get("count", 0))
        favs = [int(r.get("num_favorers", 0)) for r in res.get("results", [])]
        med = statistics.median(favs) if favs else 0
        idea["etsy_results"] = count
        idea["etsy_median_favs"] = med
        return math.log1p(med) - 0.35 * math.log10(count + 10)
    except Exception as e:
        print(f"[research] Etsy verisi alınamadı ({idea.get('search_query')}): {e}")
        return None


def pick_niches(n: int, used: list, today=None) -> list:
    today = today or dt.date.today()
    s = config.settings()
    ideas = _candidates(max(10, n * 3), used, today)
    if not ideas:
        raise RuntimeError("Yapay zekâ ürün fikri üretemedi")
    used_l = [u.lower() for u in used]
    ideas = [i for i in ideas if i["niche"].lower() not in used_l]
    scored = []
    for rank, i in enumerate(ideas):
        sc = _score(i)
        i["score"] = (sc if sc is not None else 0) + (len(ideas) - rank) * 0.02 + random.random() * 0.1
        scored.append(i)
    scored.sort(key=lambda i: -i["score"])
    weights = s["product_types"]
    max_same = s["max_same_type_per_day"]
    chosen, per_type = [], {}
    for i in scored:
        t = i["type"]
        if t not in weights or per_type.get(t, 0) >= max_same:
            continue
        chosen.append(i)
        per_type[t] = per_type.get(t, 0) + 1
        if len(chosen) >= n:
            break
    # make sure one product a day builds on a proven best seller (when we have one)
    variations = [i for i in scored if i.get("variation_of") and i.get("type") in weights]
    if variations and chosen and not any(i.get("variation_of") for i in chosen):
        chosen[-1] = variations[0]
    reserve = [i for i in scored if i not in chosen]
    return chosen, reserve


# Etsy's 2025 guidance: short, clear titles a buyer understands at a glance; keywords belong in the tags
TITLE_RULE = ("short clear Etsy title a buyer understands at a glance: 5-12 words and max 90 characters, "
              "says exactly what the item is with the main search phrase first, at most one ' - ' or ', ' separator, "
              "no keyword lists, no repeated words, no words already covered only by tags, no ALL CAPS, English")


def title_problems(title: str) -> list:
    t = (title or "").strip()
    probs = []
    words = t.split()
    if len(words) > 13 or len(t) > 100:
        probs.append(f"title too long ({len(words)} words, {len(t)} chars) - use 5-12 words, max 90 characters")
    if t.count(",") + t.count("|") + t.count(" - ") > 1:
        probs.append("title has a keyword list - use at most one separator")
    low = [w.strip(",|-").lower() for w in words if len(w) > 3]
    if len(low) != len(set(low)):
        probs.append("title repeats words")
    return probs


SPEC_COMMON = """
  "title": "TITLE_RULE",
  "intro": "2 short persuasive paragraphs (English) describing the product, style and who it is for; no file details, no emojis, no trademarks",
  "tags": [13 Etsy tags, each max 20 characters, multi-word phrases buyers search, no repeats of the same word only, English],
  "price_usd": number,
  "style": "visual style description used for every image of this product (medium, technique, mood), e.g. 'soft watercolor with loose ink outlines'",
  "palette": [3-5 hex colors],
"""


def product_spec(idea: dict) -> dict:
    ptype = idea["type"]
    mod = TYPES[ptype]
    lo, hi = config.settings()["price_ranges_usd"].get(ptype, [3, 8])
    prompt = f"""Create a complete Etsy digital product listing plan.
Product type: {ptype} ({mod.LABEL_TR})
Niche: {idea['niche']}
Main search phrase: {idea.get('search_query', '')}
Price must be between {lo} and {hi} USD (end with .99 or .49 is fine).
Never use trademarks, brand names, characters, celebrities or copyrighted styles in any field.
The artwork can NOT contain any readable text, so do not plan quotes, words or lettering in the images.
All text in English. Image prompts must describe ORIGINAL artwork only.

Return JSON with these fields:
{{
{SPEC_COMMON.replace("TITLE_RULE", TITLE_RULE)}{mod.SPEC_FIELDS}
}}"""
    for attempt in range(3):
        spec = llm.ask_json(prompt, temperature=0.9)
        problems = _validate(spec, ptype)
        if not problems:
            spec["price_usd"] = round(min(hi, max(lo, float(spec["price_usd"]))), 2)
            spec["tags"] = [t[:20] for t in spec["tags"] if not is_banned(t)][:13]
            return spec
        print(f"[research] spec sorunlu ({problems}), tekrar deneniyor")
        prompt += f"\n\nYour previous answer had problems: {problems}. Fix them."
    raise RuntimeError(f"Ürün planı oluşturulamadı: {problems}")


_LIST_FIELD = {"wall_art": ("prints", 3), "coloring": ("pages", 8), "clipart": ("elements", 12), "pattern": ("papers", 10), "tumbler": ("designs", 2)}


def _validate(spec, ptype):
    probs = []
    for f in ("title", "intro", "tags", "price_usd", "style"):
        if not spec.get(f):
            probs.append(f"missing {f}")
    probs += title_problems(spec.get("title", "")) if spec.get("title") else []
    if is_banned(spec.get("title", "")) or any(is_banned(t) for t in spec.get("tags", [])):
        probs.append("contains a banned/trademark word (remove words like prompt, svg, brand names)")
    f, n = _LIST_FIELD[ptype]
    items = spec.get(f) or []
    items = [i for i in items if isinstance(i, dict) and i.get("prompt")]
    if len(items) < n:
        probs.append(f"'{f}' must have exactly {n} items with 'name' and 'prompt'")
    else:
        for i in items:
            i.setdefault("name", "design")
        spec[f] = items[:n]
    if len(spec.get("tags", [])) < 10:
        probs.append("need 13 tags")
    try:
        float(spec.get("price_usd"))
    except Exception:
        probs.append("price_usd must be a number")
    return probs


def slugify(text, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:n].strip("-") or "digital-product"


def short_titles(items: list) -> dict:
    """items: [{"id", "title", "tags"}] -> {id: new short title} (only valid ones)."""
    out = {}
    for start in range(0, len(items), 8):
        batch = items[start:start + 8]
        lines = "\n".join(f'- id {i["id"]}: "{i["title"]}" (tags: {", ".join(i.get("tags", [])[:13])})' for i in batch)
        prompt = f"""Rewrite these Etsy listing titles for digital download products.
Each new title must be a {TITLE_RULE}.
Keep the meaning and the main product type (e.g. 'wall art set', 'clipart', 'digital paper', 'coloring pages', 'tumbler wrap', 'printable').
Do not invent features, do not add brand names or trademarks.

{lines}

Return JSON: {{"titles": [{{"id": <id>, "title": "<new title>"}}]}}"""
        for attempt in range(3):
            res = llm.ask_json(prompt, temperature=0.4)
            bad = []
            for r in res.get("titles", []):
                rid, t = str(r.get("id")), (r.get("title") or "").strip().strip('"')
                if rid in {str(i["id"]) for i in batch} and t and not title_problems(t) and not is_banned(t):
                    out[rid] = t
                elif rid in {str(i["id"]) for i in batch}:
                    bad.append(rid)
            missing = [str(i["id"]) for i in batch if str(i["id"]) not in out]
            if not missing:
                break
            prompt += f"\n\nThese ids were missing or invalid, try again shorter: {missing}"
    return out
