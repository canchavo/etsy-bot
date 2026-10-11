"""Central configuration: secrets come from environment variables (GitHub Secrets),
behaviour settings come from settings.json in the repo root."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
FONTS_DIR = ROOT / "assets" / "fonts"
WORK_DIR = Path(os.environ.get("BOT_WORK_DIR", ROOT / ".work"))

DEFAULT_SETTINGS = {
    # How many new products to prepare every day
    "products_per_day": 4,
    # Product types the bot may create, with relative weights
    "product_types": {
        "wall_art": 3,
        "coloring": 2,
        "clipart": 2,
        "pattern": 2,
        "tumbler": 1,
    },
    # Max products of the same type per day
    "max_same_type_per_day": 2,
    # USD price ranges per type (the AI picks inside these)
    "price_ranges_usd": {
        "wall_art": [4.5, 9.0],
        "coloring": [3.5, 6.5],
        "clipart": [3.5, 6.5],
        "pattern": [3.0, 5.5],
        "tumbler": [2.5, 4.5],
    },
    # "active" = listing goes live after approval, "draft" = stays as a draft on Etsy
    "publish_mode": "active",
    # Keep avoiding niches used within this many days
    "niche_memory_days": 60,
    "timezone": "Europe/Istanbul",
    # Optional: shop section id on Etsy (leave null)
    "shop_section_id": None,
    # Telegram/panel language is Turkish; listing language is English
}


def settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    p = ROOT / "settings.json"
    if p.exists():
        try:
            s.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:  # never let a typo stop the bot
            print(f"[config] settings.json okunamadı: {e}")
    return s


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
ETSY_KEYSTRING = env("ETSY_KEYSTRING")
ETSY_SHARED_SECRET = env("ETSY_SHARED_SECRET")
GEMINI_API_KEY = env("GEMINI_API_KEY")
CLOUDFLARE_ACCOUNT_ID = env("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_API_TOKEN = env("CLOUDFLARE_API_TOKEN")
POLLINATIONS_TOKEN = env("POLLINATIONS_TOKEN")
STATE_KEY = env("STATE_KEY")
PANEL_PASSWORD = env("PANEL_PASSWORD")
GITHUB_TOKEN = env("GITHUB_TOKEN")
GITHUB_REPOSITORY = env("GITHUB_REPOSITORY")  # "owner/repo"
GITHUB_RUN_URL = (
    f"{env('GITHUB_SERVER_URL', 'https://github.com')}/{GITHUB_REPOSITORY}/actions/runs/{env('GITHUB_RUN_ID')}"
    if env("GITHUB_RUN_ID") else ""
)


def pages_url() -> str:
    """URL of the GitHub Pages panel (https://owner.github.io/repo/)."""
    custom = env("PANEL_URL")
    if custom:
        return custom.rstrip("/") + "/"
    if "/" in GITHUB_REPOSITORY:
        owner, repo = GITHUB_REPOSITORY.split("/", 1)
        if repo.lower() == f"{owner.lower()}.github.io":
            return f"https://{owner.lower()}.github.io/"
        return f"https://{owner.lower()}.github.io/{repo}/"
    return ""


def etsy_redirect_uri() -> str:
    custom = env("ETSY_REDIRECT_URI")
    if custom:
        return custom
    base = pages_url()
    return base + "callback.html" if base else ""
