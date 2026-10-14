"""Command line entry point used by the GitHub Actions workflows.

python -m bot generate [--count N] [--force]
python -m bot poll
python -m bot etsy-connect [CALLBACK_URL]
python -m bot selftest
python -m bot panel
python -m bot import-abacus
"""
import argparse
import sys
import traceback

from . import config, storage, telegram
from .telegram import esc


def cmd_generate(a):
    from . import generator
    try:
        generator.run(count=a.count, force=a.force)
    finally:
        storage.commit_and_push("Günlük üretim")


def cmd_poll(a):
    from . import poller
    changed = poller.run(loop_seconds=a.loop)
    if changed:
        storage.commit_and_push("Telegram işlemleri")
    print(f"changed={changed}")


def cmd_etsy_connect(a):
    from . import etsy
    if not a.url:
        url = etsy.auth_url()
        telegram.send("🔗 Etsy bağlantı linki (GitHub'dan istendi):", [[("Etsy'de izin ver", url)]])
        print("Bu adresi açın:\n" + url)
        return
    tok = etsy.exchange(a.url)
    storage.commit_and_push("Etsy bağlandı")
    telegram.send(f"🟢 Etsy bağlandı: <b>{esc(tok.get('shop_name') or str(tok['shop_id']))}</b> ({tok.get('currency')})")
    print("Etsy bağlandı:", tok.get("shop_name"), tok.get("shop_id"))


def cmd_selftest(a):
    from . import etsy, images, llm
    import requests
    lines = ["🧪 <b>Kurulum testi</b>"]

    def check(name, fn):
        try:
            res = fn()
            lines.append(f"✅ {name}{': ' + esc(str(res)) if res else ''}")
        except Exception as e:
            lines.append(f"❌ {name}: <code>{esc(str(e)[:300])}</code>")

    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ETSY_KEYSTRING", "ETSY_SHARED_SECRET", "GEMINI_API_KEY",
                           "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "STATE_KEY", "PANEL_PASSWORD") if not getattr(config, k)]
    lines.append("🔑 Eksik gizli anahtar: " + (", ".join(missing) if missing else "yok"))
    check("Telegram", lambda: telegram.call("getMe").get("username"))
    check("Gemini", lambda: llm.gemini_models()[0] if config.GEMINI_API_KEY else (_ for _ in ()).throw(RuntimeError("anahtar yok")))
    check("Metin üretimi", lambda: llm.ask_json('Return JSON {"ok": true, "word": "<a random English word>"}').get("word"))
    check("Görsel üretimi", lambda: "{}x{} ({})".format(*images.generate("a small watercolor lemon on white background", 512, 512).size,
                                                         "cloudflare" if images.stats["cloudflare"] else "pollinations"))

    def etsy_ping():
        r = requests.get("https://openapi.etsy.com/v3/application/openapi-ping", headers={"x-api-key": etsy._api_key()}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
        return "API anahtarı geçerli"
    check("Etsy API", etsy_ping)
    check("Etsy piyasa verisi", lambda: f"'wall art' için {etsy.search_active('botanical wall art', 3).get('count')} ilan")

    def etsy_shop():
        tok = etsy.token()
        return f"{tok.get('shop_name')} ({tok.get('currency')})"
    check("Etsy mağaza bağlantısı", etsy_shop)
    lines.append(f"🌐 Panel: {config.pages_url() or '-'}")
    lines.append(f"↩️ Etsy Callback URL (Etsy uygulamanıza bunu yazın): <code>{esc(config.etsy_redirect_uri())}</code>")
    msg = "\n".join(lines)
    print(msg)
    try:
        telegram.send(msg)
    except Exception as e:
        print(f"Telegram'a gönderilemedi: {e}")
    storage.commit_and_push("Kurulum testi")


def cmd_panel(a):
    from . import panel
    print(panel.build(a.out))


def cmd_import_abacus(a):
    from . import importer
    importer.run()
    storage.commit_and_push("Abacus ürünleri içe aktarıldı")


def cmd_retitle(a):
    from . import retitle
    retitle.run(dry_run=a.dry_run)
    storage.commit_and_push("İlan başlıkları kısaltıldı")


def cmd_pinweek(a):
    from . import pinweek
    if a.notify:
        pinweek.notify()
        return
    try:
        pinweek.run(a.count)
    finally:
        storage.commit_and_push("Haftalık Pinterest pinleri", extra_paths=("panel/pins",))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--count", type=int, default=None)
    g.add_argument("--force", action="store_true")
    pl = sub.add_parser("poll")
    pl.add_argument("--loop", type=int, default=0, help="seconds to keep listening")
    e = sub.add_parser("etsy-connect")
    e.add_argument("url", nargs="?", default="")
    sub.add_parser("selftest")
    p = sub.add_parser("panel")
    p.add_argument("--out", default="_site")
    sub.add_parser("import-abacus")
    pw = sub.add_parser("pinweek")
    pw.add_argument("--count", type=int, default=None)
    pw.add_argument("--notify", action="store_true")
    r = sub.add_parser("retitle")
    r.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    fn = {"generate": cmd_generate, "poll": cmd_poll, "etsy-connect": cmd_etsy_connect, "selftest": cmd_selftest,
          "panel": cmd_panel, "import-abacus": cmd_import_abacus,
          "retitle": cmd_retitle, "pinweek": cmd_pinweek}[a.cmd]
    try:
        fn(a)
    except Exception as e:
        traceback.print_exc()
        if a.cmd in ("generate", "etsy-connect", "import-abacus", "retitle", "pinweek"):
            try:
                telegram.send(f"⚠️ <b>{a.cmd}</b> hata verdi: <code>{esc(str(e)[:600])}</code>\n{config.GITHUB_RUN_URL}")
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
