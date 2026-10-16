"""Social media pack for a published product:
- a 2:3 Pinterest pin image (1000x1500) + pin title/description + link
- a 9:16 short video (1080x1920, ~12 s) for TikTok / Instagram Reels / Shorts + caption with hashtags
Everything is drawn locally from the listing mockups (no AI quota used)."""
import io
import os
import re
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import config
from .imgutil import fit_text, font, wrap_text
from .mockups import _mix, palette_colors

SHOP_NAME = "NuviraStudioDigital"
HANDLE = "@nuvirastudiodigital"  # same handle on Pinterest, TikTok and Instagram
FPS = 30

HOOKS = {
    "wall_art": "Instant wall makeover - just print and frame",
    "coloring": "Print, grab your pencils and relax",
    "clipart": "Ready-to-use clipart for your next project",
    "pattern": "Seamless papers for scrapbooking and crafts",
    "tumbler": "Your next tumbler design is ready to press",
}
BASE_TAGS = {
    "wall_art": ["wallart", "printableart", "homedecor"],
    "coloring": ["coloringpages", "printablecoloring", "adultcoloring"],
    "clipart": ["clipart", "pngclipart", "crafting"],
    "pattern": ["digitalpaper", "scrapbooking", "seamlesspattern"],
    "tumbler": ["tumblerwrap", "sublimation", "tumblerdesign"],
}


def _split_title(title):
    main, _, sub = title.partition(" - ")
    return main.strip(), sub.strip()


def _rounded(img, radius):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def _shadowed(canvas, img, xy, radius=28, blur=26, opacity=90):
    sh = Image.new("RGBA", (img.width + blur * 4, img.height + blur * 4), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((blur * 2, blur * 2, blur * 2 + img.width, blur * 2 + img.height),
                                         radius=radius, fill=(0, 0, 0, opacity))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(sh, (xy[0] - blur * 2, xy[1] - blur * 2 + 14))
    canvas.alpha_composite(_rounded(img, radius), xy)


def _center_text(d, y, text, f, fill, W):
    w = d.textlength(text, font=f)
    d.text(((W - w) / 2, y), text, font=f, fill=fill)


def _pill(d, cx, y, text, f, bg, fg):
    w = d.textlength(text, font=f)
    h = f.size
    box = (cx - w / 2 - h * 0.9, y, cx + w / 2 + h * 0.9, y + h * 1.9)
    d.rounded_rectangle(box, radius=int(h), fill=bg)
    d.text((cx - w / 2, y + h * 0.38), text, font=f, fill=fg)
    return box


# ---------------------------------------------------------------- Pinterest pin

def pin_image(p, photos):
    """photos: [PIL images] (listing mockups, first = hero)."""
    W, H = 1000, 1500
    pal = palette_colors(p.get("spec", {}).get("palette"))
    canvas = Image.new("RGBA", (W, H), pal["bg"] + (255,))
    d = ImageDraw.Draw(canvas)
    main, sub = _split_title(p["title"])
    # header
    f_pill = font("sans_medium", 26)
    _pill(d, W / 2, 56, "INSTANT DOWNLOAD", f_pill, pal["text"], pal["bg"])
    f_title = fit_text(d, main, "serif", W - 120, 78, 46)
    lines = wrap_text(d, main, f_title, W - 120)[:3]
    y = 150
    for ln in lines:
        _center_text(d, y, ln, f_title, pal["text"], W)
        y += int(f_title.size * 1.18)
    if sub:
        f_sub = fit_text(d, sub, "sans", W - 140, 34, 24)
        _center_text(d, y + 6, sub, f_sub, _mix(pal["text"], pal["bg"], 0.25), W)
        y += int(f_sub.size * 1.5) + 6
    # hero mockup
    hero = ImageOps.fit(photos[0].convert("RGB"), (880, 700), Image.LANCZOS)
    hy = y + 45
    _shadowed(canvas, hero, ((W - 880) // 2, hy))
    # strip of up to 2 more images
    extra = photos[1:3]
    sy = hy + 700 + 40
    if extra and sy + 220 < H - 110:
        sw = (880 - 30 * (len(extra) - 1)) // len(extra)
        sh = H - 125 - sy
        for i, im in enumerate(extra):
            th = ImageOps.fit(im.convert("RGB"), (sw, sh), Image.LANCZOS)
            _shadowed(canvas, th, ((W - 880) // 2 + i * (sw + 30), sy), radius=20, blur=16, opacity=70)
    # footer
    f_foot = font("sans_medium", 30)
    _center_text(d, H - 78, f"{SHOP_NAME}  •  on Etsy", f_foot, pal["text"], W)
    out = io.BytesIO()
    canvas.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()


def _hashtags(p, n=10):
    tags = list(BASE_TAGS.get(p["type"], []))
    for t in p.get("tags", []):
        h = re.sub(r"[^a-z0-9]", "", t.lower())
        if 3 <= len(h) <= 24 and h not in tags:
            tags.append(h)
    tags += ["etsyfinds", "digitaldownload"]
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append("#" + t)
    return out[:n]


def texts(p, link):
    main, sub = _split_title(p["title"])
    intro = re.split(r"(?<=[.!?])\s", (p.get("spec", {}).get("intro") or "").strip())[0][:240]
    kw = ", ".join(t for t in p.get("tags", [])[:8])
    tail = f" More designs on TikTok & Instagram {HANDLE}"
    pin_desc = (f"{intro} Instant digital download from {SHOP_NAME} on Etsy. {kw}"[:480 - len(tail)].rstrip(", ") + "." + tail).strip()
    caption = "\n".join([
        f"{HOOKS.get(p['type'], 'New in the shop')} ✨",
        "",
        p["title"],
        "Instant digital download 📥  Link in bio → " + SHOP_NAME + " on Etsy",
        f"📌 Also on Pinterest & Instagram: {HANDLE}",
        "",
        " ".join(_hashtags(p)),
    ])
    return {"pin_title": p["title"][:100], "pin_desc": pin_desc, "caption": caption, "link": link}


# ---------------------------------------------------------------- vertical video

VW, VH = 1080, 1920


def _bg_frame(img, pal):
    bg = ImageOps.fit(img.convert("RGB"), (VW // 4, VH // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(10))
    bg = bg.resize((VW, VH), Image.BILINEAR)
    return Image.blend(bg, Image.new("RGB", (VW, VH), pal["bg"]), 0.45)


def _overlay(p, pal):
    """Static text layer (title at top, CTA at bottom) as RGBA."""
    ov = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    main, sub = _split_title(p["title"])
    f_t = fit_text(d, main, "serif", VW - 140, 84, 52)
    lines = wrap_text(d, main, f_t, VW - 140)[:3]
    box_h = 120 + len(lines) * int(f_t.size * 1.2) + (60 if sub else 0)
    d.rounded_rectangle((50, 170, VW - 50, 170 + box_h), radius=40, fill=pal["bg"] + (235,))
    y = 215
    for ln in lines:
        _center_text(d, y, ln, f_t, pal["text"], VW)
        y += int(f_t.size * 1.2)
    if sub:
        f_s = fit_text(d, sub, "sans", VW - 180, 38, 26)
        _center_text(d, y + 8, sub, f_s, _mix(pal["text"], pal["bg"], 0.25), VW)
    f_b = font("sans_medium", 40)
    _pill(d, VW / 2, VH - 330, "INSTANT DOWNLOAD  •  LINK IN BIO", f_b, pal["text"] + (255,), pal["bg"] + (255,))
    return ov


def _end_card(p, pal):
    img = Image.new("RGB", (VW, VH), pal["bg"])
    d = ImageDraw.Draw(img)
    main, _ = _split_title(p["title"])
    f_t = fit_text(d, main, "serif", VW - 160, 92, 56)
    lines = wrap_text(d, main, f_t, VW - 160)[:4]
    y = VH / 2 - (len(lines) * f_t.size * 1.2) / 2 - 140
    for ln in lines:
        _center_text(d, y, ln, f_t, pal["text"], VW)
        y += f_t.size * 1.2
    _center_text(d, y + 60, "Shop the full set on Etsy", font("sans", 46), _mix(pal["text"], pal["bg"], 0.2), VW)
    _pill(d, VW / 2, y + 170, SHOP_NAME, font("sans_bold", 48), pal["text"], pal["bg"])
    _center_text(d, y + 330, "link in bio", font("sans_light", 40), _mix(pal["text"], pal["bg"], 0.3), VW)
    return img


def _ffmpeg():
    """Bundled static ffmpeg (pip package imageio-ffmpeg); the system one may be missing."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def video(p, photos, seconds_per=2.6, end=2.2, fade=0.45):
    pal = palette_colors(p.get("spec", {}).get("palette"))
    photos = [im.convert("RGB") for im in photos[:4]]
    ov = _overlay(p, pal)
    scenes = []
    for im in photos:
        # crop the 4:3 mockup towards 1:1 so the product fills more of the vertical screen
        sq = ImageOps.fit(im, (min(im.width, int(im.height * 1.08)), im.height), Image.LANCZOS)
        fg_w = VW - 70
        fg_h = int(fg_w * sq.height / sq.width)
        scenes.append((_bg_frame(im, pal), sq, fg_w, fg_h))
    endc = _end_card(p, pal)
    n_scene = int(seconds_per * FPS)
    n_fade = int(fade * FPS)

    def scene_frame(i, t):
        bg, im, fw, fh = scenes[i]
        z = 1.0 + 0.06 * t  # slow zoom-in
        w, h = int(fw * z), int(fh * z)
        fr = bg.copy().convert("RGBA")
        fg = im.resize((w, h), Image.BILINEAR)
        x, y = (VW - w) // 2, (VH - h) // 2 + 90
        fr.alpha_composite(_rounded(fg, 30), (x, y))
        fr.alpha_composite(ov)
        return fr.convert("RGB")

    frames = []  # generator of PIL frames
    def gen():
        for i in range(len(scenes)):
            for k in range(n_scene):
                f = scene_frame(i, k / n_scene)
                if k >= n_scene - n_fade:  # crossfade into the next scene / end card
                    a = (k - (n_scene - n_fade)) / n_fade
                    nxt = scene_frame(i + 1, 0) if i + 1 < len(scenes) else endc
                    f = Image.blend(f, nxt, a)
                yield f
        for _ in range(int(end * FPS)):
            yield endc

    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "v.mp4")
        cmd = [_ffmpeg(), "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{VW}x{VH}", "-r", str(FPS), "-i", "-",
               "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
               "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for f in gen():
            proc.stdin.write(f.tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg video oluşturamadı")
        return open(out, "rb").read()


# ---------------------------------------------------------------- pack + Telegram

def _pick_photos(p, photos):
    """Prefer real-looking mockups (room/cover/tumbler/all) over info and how-to cards."""
    order = ("room", "cover", "tumbler", "print", "all", "transparent", "page", "example")
    named = [(n, Image.open(io.BytesIO(b))) for n, b in photos]
    good = [im for key in order for n, im in named if key in n]
    seen, out = set(), []
    for im in good:
        if id(im) not in seen:
            seen.add(id(im))
            out.append(im)
    return out or [im for _, im in named]


def build_pack(p, photos):
    """photos: [(name, jpeg bytes)] -> dict with pin, video, texts."""
    ims = _pick_photos(p, photos)
    link = p.get("etsy", {}).get("url") or f"https://www.etsy.com/shop/{SHOP_NAME}"
    pack = texts(p, link)
    pack["pin"] = pin_image(p, ims)
    pack["video"] = video(p, ims)
    return pack


def send_pack(p, photos):
    from . import telegram
    from .telegram import esc
    pack = build_pack(p, photos)
    telegram.call("sendPhoto", {"chat_id": config.TELEGRAM_CHAT_ID, "parse_mode": "HTML",
                                "caption": (f"📌 <b>Pinterest pini</b>\n\n<b>Başlık:</b> <code>{esc(pack['pin_title'])}</code>\n"
                                            f"<b>Link:</b> {esc(pack['link'])}")[:1024]},
                  files={"photo": ("pin.jpg", pack["pin"], "image/jpeg")}, timeout=120)
    telegram.send(f"📝 <b>Pin açıklaması</b> (kopyala):\n<code>{esc(pack['pin_desc'])}</code>")
    telegram.call("sendVideo", {"chat_id": config.TELEGRAM_CHAT_ID, "supports_streaming": "true", "parse_mode": "HTML",
                                "caption": "🎬 <b>TikTok / Reels / Shorts videosu</b> – kaydet, trend bir ses ekle, paylaş."},
                  files={"video": ("video.mp4", pack["video"], "video/mp4")}, timeout=300)
    telegram.send(f"✍️ <b>Video açıklaması</b> (kopyala):\n<code>{esc(pack['caption'])}</code>")
    return pack
