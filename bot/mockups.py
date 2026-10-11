"""Listing images (mockups) drawn with Pillow. All outputs are 2400x1800 (4:3),
which Etsy shows without cropping in search results."""
import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .imgutil import fit_text, font, hex2rgb, paste_with_shadow, wrap_text

W, H = 2400, 1800


def _mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def palette_colors(palette):
    cols = [hex2rgb(c) for c in (palette or [])][:5]
    if not cols:
        cols = [(74, 93, 79), (216, 164, 127), (46, 58, 48)]
    # darkest color for text, lightest tint for background
    lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    dark = min(cols, key=lum)
    if lum(dark) > 110:
        dark = _mix(dark, (25, 25, 30), 0.6)
    accent = sorted(cols, key=lambda c: -(max(c) - min(c)))[0]
    bg = _mix(max(cols, key=lum), (250, 247, 242), 0.82)
    return {"bg": bg, "text": dark, "accent": accent, "all": cols}


def _bg(pal, texture=True):
    img = Image.new("RGB", (W, H), pal["bg"])
    if texture:
        rng = np.random.default_rng(7)
        noise = rng.normal(0, 4, (H // 4, W // 4)).astype(np.float32)
        n = Image.fromarray(np.clip(128 + noise, 0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
        img = Image.blend(img, Image.merge("RGB", (n, n, n)), 0.06)
    return img.convert("RGBA")


def _badge(d, x, y, text, pal, size=44):
    f = font("sans_medium", size)
    tw = d.textlength(text, font=f)
    pad_x, pad_y = size * 0.9, size * 0.45
    box = (x, y, x + tw + 2 * pad_x, y + size + 2 * pad_y)
    d.rounded_rectangle(box, radius=int(size), fill=pal["text"])
    d.text((x + pad_x, y + pad_y - size * 0.12), text, font=f, fill=pal["bg"])
    return box


def frame(art: Image.Image, frame_rgb=(30, 30, 30), mat=True, thickness=None) -> Image.Image:
    art = art.convert("RGB")
    w, h = art.size
    t = thickness or max(8, int(min(w, h) * 0.045))
    m = int(min(w, h) * 0.09) if mat else 0
    out = Image.new("RGB", (w + 2 * (t + m), h + 2 * (t + m)), frame_rgb)
    d = ImageDraw.Draw(out)
    if mat:
        d.rectangle((t, t, out.width - t - 1, out.height - t - 1), fill=(250, 249, 246))
        # inner bevel of the mat
        d.rectangle((t + m - 3, t + m - 3, t + m + w + 2, t + m + h + 2), fill=(225, 222, 216))
    out.paste(art, (t + m, t + m))
    # subtle frame highlight
    d.line((0, 0, out.width, 0), fill=_mix(frame_rgb, (255, 255, 255), 0.25), width=max(2, t // 5))
    return out


def room_mockup(room: Image.Image, arts: list, frame_rgb=(32, 30, 28)) -> Image.Image:
    """Hang 1-3 framed prints on the upper wall area of an AI generated room photo."""
    canvas = ImageOps.fit(room.convert("RGB"), (W, H), Image.LANCZOS).convert("RGBA")
    n = len(arts)
    total_w = W * (0.68 if n >= 3 else 0.50 if n == 2 else 0.30)
    gap = W * 0.035
    fw = (total_w - gap * (n - 1)) / n
    framed = []
    for a in arts:
        ratio = a.height / a.width
        art_w = int(fw * 0.80)
        art = a.resize((art_w, int(art_w * ratio)), Image.LANCZOS)
        framed.append(frame(art, frame_rgb, mat=True))
    fh = max(f.height for f in framed)
    scale = min(1.0, (H * 0.56) / fh)
    framed = [f.resize((int(f.width * scale), int(f.height * scale)), Image.LANCZOS) for f in framed]
    total = sum(f.width for f in framed) + gap * (n - 1)
    x = (W - total) / 2
    top = H * 0.10
    for f in framed:
        y = top + (max(g.height for g in framed) - f.height) / 2
        paste_with_shadow(canvas, f, (x, y), radius=22, offset=(10, 22), opacity=120)
        x += f.width + gap
    return canvas.convert("RGB")


def wall_mockup(art: Image.Image, wall_rgb, frame_rgb=(32, 30, 28)) -> Image.Image:
    """Single framed print on a plain painted wall with a soft light falloff."""
    canvas = Image.new("RGB", (W, H), wall_rgb)
    grad = Image.radial_gradient("L").resize((W * 2, H * 2)).crop((W // 2, H // 3, W // 2 + W, H // 3 + H))
    dark = Image.new("RGB", (W, H), _mix(wall_rgb, (0, 0, 0), 0.22))
    canvas = Image.composite(dark, canvas, grad.point(lambda v: int(v * 0.8)))
    # floor/shelf line
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, int(H * 0.88), W, H), fill=_mix(wall_rgb, (90, 70, 55), 0.55))
    canvas = canvas.convert("RGBA")
    ratio = art.height / art.width
    fh = H * 0.70
    art_w = int(fh / ratio * 0.80)
    f = frame(art.resize((art_w, int(art_w * ratio)), Image.LANCZOS), frame_rgb, mat=True)
    s = fh / f.height
    f = f.resize((int(f.width * s), int(f.height * s)), Image.LANCZOS)
    paste_with_shadow(canvas, f, ((W - f.width) / 2, H * 0.08), radius=26, offset=(12, 26), opacity=130)
    return canvas.convert("RGB")


def cover(images: list, title: str, subtitle: str, palette, badge="INSTANT DOWNLOAD", layout="fan") -> Image.Image:
    pal = palette_colors(palette)
    canvas = _bg(pal)
    d = ImageDraw.Draw(canvas)
    area_top, area_bottom = 130, H - 470
    n = min(len(images), 5)
    imgs = images[:n]
    if layout == "fan" and n >= 2:
        max_h = area_bottom - area_top
        angles = np.linspace(-9, 9, n) if n > 1 else [0]
        span = W * 0.80
        for i, (im, ang) in enumerate(zip(imgs, angles)):
            im = im.convert("RGB")
            s = (max_h * 0.92) / im.height
            if im.width * s > span / max(1, n - 0.6):
                s = (span / max(1, n - 0.6)) / im.width
            t = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
            t = ImageOps.expand(t, border=max(6, t.width // 60), fill=(255, 255, 255))
            cx = W / 2 + (i - (n - 1) / 2) * (span / n)
            r = t.convert("RGBA").rotate(-ang, expand=True, resample=Image.BICUBIC)
            paste_with_shadow(canvas, r, (cx - r.width / 2, area_top + (max_h - r.height) / 2 + abs(ang) * 4), radius=24, offset=(8, 18), opacity=90)
    else:
        # simple row
        max_h = area_bottom - area_top
        gap = 50
        widths = [im.width * max_h / im.height for im in imgs]
        total = sum(widths) + gap * (n - 1)
        s = min(1, (W * 0.88) / total)
        x = (W - total * s) / 2
        for im, wd in zip(imgs, widths):
            t = im.convert("RGBA").resize((int(wd * s), int(max_h * s)), Image.LANCZOS)
            paste_with_shadow(canvas, t, (x, area_top + (max_h - t.height) / 2), radius=22, offset=(6, 14), opacity=80)
            x += t.width + gap * s
    # title panel
    panel_top = H - 420
    d.rectangle((0, panel_top, W, H), fill=pal["bg"] + (255,))
    d.line((W * 0.3, panel_top + 6, W * 0.7, panel_top + 6), fill=pal["accent"] + (255,), width=4)
    tf = fit_text(d, title.upper(), "sans_bold", W * 0.9, 120, 48)
    tw = d.textlength(title.upper(), font=tf)
    d.text(((W - tw) / 2, panel_top + 50), title.upper(), font=tf, fill=pal["text"] + (255,))
    sf = fit_text(d, subtitle, "serif_italic", W * 0.85, 64, 30)
    sw = d.textlength(subtitle, font=sf)
    d.text(((W - sw) / 2, panel_top + 205), subtitle, font=sf, fill=_mix(pal["text"], pal["bg"], 0.25) + (255,))
    if badge:
        f = font("sans_medium", 42)
        bw = d.textlength(badge, font=f) + 2 * 38
        _badge(d, (W - bw) / 2, panel_top + 300, badge, pal, 42)
    return canvas.convert("RGB")


def grid(images: list, title: str, palette, cols=None, checker=False, cell_bg=(255, 255, 255)) -> Image.Image:
    pal = palette_colors(palette)
    canvas = _bg(pal)
    d = ImageDraw.Draw(canvas)
    n = len(images)
    cols = cols or (3 if n <= 6 else 4 if n <= 12 else 5)
    rows = math.ceil(n / cols)
    top = 210
    margin = 70
    gap = 28
    cw = (W - 2 * margin - gap * (cols - 1)) / cols
    ch = (H - top - margin - gap * (rows - 1)) / rows
    tf = fit_text(d, title, "sans_bold", W - 2 * margin, 92, 40)
    tw = d.textlength(title, font=tf)
    d.text(((W - tw) / 2, 60), title, font=tf, fill=pal["text"] + (255,))
    for i, im in enumerate(images):
        r, c = divmod(i, cols)
        x0 = margin + c * (cw + gap)
        y0 = top + r * (ch + gap)
        cell = Image.new("RGBA", (int(cw), int(ch)), cell_bg + (255,))
        if checker:
            cd = ImageDraw.Draw(cell)
            sq = 22
            for yy in range(0, int(ch), sq):
                for xx in range(0, int(cw), sq):
                    if (xx // sq + yy // sq) % 2:
                        cd.rectangle((xx, yy, xx + sq, yy + sq), fill=(236, 236, 236, 255))
        t = im.copy()
        t.thumbnail((int(cw * 0.88), int(ch * 0.88)), Image.LANCZOS)
        t = t.convert("RGBA")
        cell.alpha_composite(t, (int((cw - t.width) / 2), int((ch - t.height) / 2)))
        mask = Image.new("L", cell.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, cell.width - 1, cell.height - 1), radius=22, fill=255)
        cell.putalpha(mask)
        paste_with_shadow(canvas, cell, (x0, y0), radius=14, offset=(0, 8), opacity=45)
    return canvas.convert("RGB")


def info_card(heading: str, lines: list, palette, image: Image.Image = None) -> Image.Image:
    pal = palette_colors(palette)
    canvas = _bg(pal)
    d = ImageDraw.Draw(canvas)
    left = 140
    text_w = W * (0.48 if image is not None else 0.8)
    hf = fit_text(d, heading, "sans_bold", text_w, 110, 44)
    d.text((left, 170), heading, font=hf, fill=pal["text"] + (255,))
    d.line((left, 310, left + 220, 310), fill=pal["accent"] + (255,), width=8)
    y = 390
    bf = font("sans", 60)
    for line in lines:
        wrapped = wrap_text(d, line, bf, text_w - 80)
        d.ellipse((left, y + 28, left + 24, y + 52), fill=pal["accent"] + (255,))
        for wl in wrapped:
            d.text((left + 60, y), wl, font=bf, fill=pal["text"] + (255,))
            y += 84
        y += 38
        if y > H - 120:
            break
    if image is not None:
        im = image.convert("RGBA")
        im.thumbnail((int(W * 0.36), int(H * 0.74)), Image.LANCZOS)
        paste_with_shadow(canvas, im, (W - im.width - 150, (H - im.height) / 2), radius=26, offset=(10, 20), opacity=100)
    return canvas.convert("RGB")


def how_it_works(palette) -> Image.Image:
    pal = palette_colors(palette)
    canvas = _bg(pal)
    d = ImageDraw.Draw(canvas)
    title = "HOW IT WORKS"
    tf = font("sans_bold", 104)
    d.text(((W - d.textlength(title, font=tf)) / 2, 170), title, font=tf, fill=pal["text"] + (255,))
    steps = [
        ("1", "Purchase", "Complete your order on Etsy"),
        ("2", "Download", "Get your files instantly from Purchases & Reviews"),
        ("3", "Enjoy", "Print at home, at a print shop or use them digitally"),
    ]
    cw = (W - 300) / 3
    for i, (num, head, sub) in enumerate(steps):
        cx = 150 + cw * i + cw / 2
        d.ellipse((cx - 120, 520, cx + 120, 760), fill=pal["accent"] + (255,))
        nf = font("sans_bold", 120)
        d.text((cx - d.textlength(num, font=nf) / 2, 545), num, font=nf, fill=(255, 255, 255, 255))
        hf = font("sans_medium", 66)
        d.text((cx - d.textlength(head, font=hf) / 2, 830), head, font=hf, fill=pal["text"] + (255,))
        sf = font("sans", 42)
        yy = 940
        for line in wrap_text(d, sub, sf, cw - 80):
            d.text((cx - d.textlength(line, font=sf) / 2, yy), line, font=sf, fill=_mix(pal["text"], pal["bg"], 0.3) + (255,))
            yy += 58
    note = "This is a digital product. No physical item will be shipped."
    nf = font("serif_italic", 46)
    d.text(((W - d.textlength(note, font=nf)) / 2, H - 260), note, font=nf, fill=_mix(pal["text"], pal["bg"], 0.2) + (255,))
    return canvas.convert("RGB")


def tumbler_mockup(design: Image.Image, palette, label="20 OZ SKINNY TUMBLER") -> Image.Image:
    """Draw a straight skinny tumbler with the wrap mapped around a cylinder."""
    pal = palette_colors(palette)
    canvas = _bg(pal)
    tw_, th_ = 900, 1350
    # visible half of the cylinder = middle 50% of the wrap, compressed with a sine mapping
    src = design.convert("RGB").resize((1800, th_), Image.LANCZOS)
    a = np.asarray(src)
    xs = np.arange(tw_)
    theta = np.arcsin(np.clip((xs - tw_ / 2) / (tw_ / 2), -0.999, 0.999))  # -pi/2..pi/2
    sx = ((theta / math.pi) + 0.5) * (src.width * 0.5) + src.width * 0.25
    body = a[:, sx.astype(int).clip(0, src.width - 1), :].astype(np.float32)
    shade = 0.72 + 0.28 * np.cos(theta)  # darker towards the edges
    hl = np.exp(-((xs - tw_ * 0.32) / (tw_ * 0.05)) ** 2) * 60  # highlight stripe
    body = np.clip(body * shade[None, :, None] + hl[None, :, None], 0, 255).astype(np.uint8)
    body_img = Image.fromarray(body).convert("RGBA")
    mask = Image.new("L", (tw_, th_), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw_ - 1, th_ - 1), radius=60, fill=255)
    body_img.putalpha(mask)
    # lid
    lid = Image.new("RGBA", (tw_ + 40, 170), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lid)
    ld.rounded_rectangle((0, 40, tw_ + 39, 169), radius=40, fill=(245, 245, 245, 255))
    ld.rounded_rectangle((tw_ * 0.30, 0, tw_ * 0.70, 70), radius=30, fill=(232, 232, 232, 255))
    x = (W - tw_) / 2 - W * 0.17
    y = 300
    paste_with_shadow(canvas, body_img, (x, y + 150), radius=30, offset=(30, 30), opacity=90)
    paste_with_shadow(canvas, lid, (x - 20, y), radius=10, offset=(0, 6), opacity=40)
    # flat design preview on the right
    flat = design.convert("RGB").copy()
    flat.thumbnail((int(W * 0.38), int(H * 0.5)), Image.LANCZOS)
    flat = ImageOps.expand(flat, border=10, fill=(255, 255, 255))
    paste_with_shadow(canvas, flat.convert("RGBA"), (W * 0.56, H * 0.28), radius=20, offset=(6, 14), opacity=70)
    d = ImageDraw.Draw(canvas)
    f = font("sans_medium", 50)
    d.text((W * 0.56, H * 0.28 + flat.height + 50), label, font=f, fill=pal["text"] + (255,))
    f2 = font("sans", 40)
    d.text((W * 0.56, H * 0.28 + flat.height + 120), "PNG  •  300 DPI  •  Sublimation ready", font=f2, fill=_mix(pal["text"], pal["bg"], 0.3) + (255,))
    return canvas.convert("RGB")


def colored_preview(page: Image.Image, palette, seed=1) -> Image.Image:
    """Flood-fill some regions of a line-art page to show a colored example."""
    rnd = random.Random(seed)
    small = page.convert("L").copy()
    small.thumbnail((900, 900))
    bw = small.point(lambda v: 255 if v > 150 else 0).convert("RGB")
    cols = palette_colors(palette)["all"] + [(244, 184, 167), (167, 199, 231), (193, 225, 193), (253, 222, 150)]
    w, h = bw.size
    # mark the outer background so it stays white
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if bw.getpixel(corner) == (255, 255, 255):
            ImageDraw.floodfill(bw, corner, (255, 255, 254), thresh=0)
    for _ in range(140):
        x, y = rnd.randrange(w), rnd.randrange(h)
        if bw.getpixel((x, y)) == (255, 255, 255):
            c = rnd.choice(cols)
            c = _mix(c, (255, 255, 255), 0.25)
            ImageDraw.floodfill(bw, (x, y), c, thresh=0)
    return bw
