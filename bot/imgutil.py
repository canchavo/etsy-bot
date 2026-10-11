"""Image helpers shared by product builders and mockups."""
import io
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config

FONT_FILES = {
    "sans": "Poppins-Regular.ttf",
    "sans_light": "Poppins-Light.ttf",
    "sans_medium": "Poppins-Medium.ttf",
    "sans_bold": "Poppins-Bold.ttf",
    "serif": "Lora-Variable.ttf",
    "serif_italic": "Lora-Italic-Variable.ttf",
}


def font(kind: str, size: int):
    try:
        return ImageFont.truetype(str(config.FONTS_DIR / FONT_FILES[kind]), int(size))
    except Exception:
        return ImageFont.load_default()


def hex2rgb(h: str):
    h = (h or "#888888").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (136, 136, 136)


def upscale(img: Image.Image, w: int, h: int, sharpen=True) -> Image.Image:
    out = img.resize((w, h), Image.LANCZOS)
    if sharpen:
        out = out.filter(ImageFilter.UnsharpMask(radius=2, percent=55, threshold=2))
    return out


def crop_ratio(img: Image.Image, ratio: float) -> Image.Image:
    """Center-crop to width/height ratio."""
    w, h = img.size
    if w / h > ratio:
        nw = int(h * ratio)
        x = (w - nw) // 2
        return img.crop((x, 0, x + nw, h))
    nh = int(w / ratio)
    y = (h - nh) // 2
    return img.crop((0, y, w, y + nh))


def jpeg_bytes(img: Image.Image, quality=90, dpi=300) -> bytes:
    b = io.BytesIO()
    img.convert("RGB").save(b, "JPEG", quality=quality, dpi=(dpi, dpi), optimize=True, progressive=True, subsampling=0 if quality >= 90 else 2)
    return b.getvalue()


def png_bytes(img: Image.Image, dpi=300) -> bytes:
    b = io.BytesIO()
    img.save(b, "PNG", dpi=(dpi, dpi), optimize=True)
    return b.getvalue()


def thumb_b64(img: Image.Image, size=420) -> str:
    import base64
    t = img.convert("RGB").copy()
    t.thumbnail((size, size), Image.LANCZOS)
    b = io.BytesIO()
    t.save(b, "JPEG", quality=72)
    return base64.b64encode(b.getvalue()).decode()


def color_to_alpha_background(img: Image.Image, thresh=232) -> Image.Image:
    """Remove a (near-)white background that touches the image border.
    Interior whites stay opaque; edges keep soft watercolor transparency."""
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    h, w, _ = rgb.shape
    near_white = rgb.min(axis=2) >= thresh
    # flood fill from the borders over near-white pixels
    mask_img = Image.fromarray((near_white * 255).astype(np.uint8))
    filled = mask_img.copy()
    seeds = [(x, 0) for x in range(0, w, 7)] + [(x, h - 1) for x in range(0, w, 7)] + \
            [(0, y) for y in range(0, h, 7)] + [(w - 1, y) for y in range(0, h, 7)]
    for sx, sy in seeds:
        if filled.getpixel((sx, sy)) == 255:
            ImageDraw.floodfill(filled, (sx, sy), 128)
    bg = np.asarray(filled) == 128
    # widen the background region a little so anti-aliased edges are softened too
    region = np.asarray(Image.fromarray((bg * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))) > 0
    # GIMP-style color-to-alpha against white
    a = (255.0 - rgb.min(axis=2)) / 255.0
    a = np.clip(a * 1.15, 0, 1)
    alpha = np.where(region, a, 1.0)
    alpha[bg & (rgb.min(axis=2) >= 245)] = 0.0
    safe = np.maximum(alpha, 1e-3)[..., None]
    col = (rgb - 255.0 * (1 - safe)) / safe
    col = np.where(region[..., None], col, rgb)
    out = np.dstack([np.clip(col, 0, 255), alpha * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def trim_alpha(img: Image.Image, pad_ratio=0.04) -> Image.Image:
    bbox = img.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox()
    if not bbox:
        return img
    x0, y0, x1, y1 = bbox
    pad = int(max(img.size) * pad_ratio)
    return img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)))


def mirror_tile(img: Image.Image) -> Image.Image:
    """Make a guaranteed-seamless tile by mirroring (2x2)."""
    w, h = img.size
    tile = Image.new("RGB", (w * 2, h * 2))
    tile.paste(img, (0, 0))
    tile.paste(img.transpose(Image.FLIP_LEFT_RIGHT), (w, 0))
    tile.paste(img.transpose(Image.FLIP_TOP_BOTTOM), (0, h))
    tile.paste(img.transpose(Image.ROTATE_180), (w, h))
    return tile


def offset_seamless(img: Image.Image, blend=0.18) -> Image.Image:
    """Make a tile seamless while keeping orientation: wrap-offset by half and blend
    the seams with the original."""
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    h, w, _ = a.shape
    shifted = np.roll(np.roll(a, h // 2, axis=0), w // 2, axis=1)
    # weight: 1 near the center seams of the shifted image (where original edges meet)
    yy = np.abs(np.arange(h) - h / 2) / (h * blend)
    xx = np.abs(np.arange(w) - w / 2) / (w * blend)
    wy = np.clip(1 - yy, 0, 1)
    wx = np.clip(1 - xx, 0, 1)
    wgt = np.maximum(wy[:, None], wx[None, :])
    wgt = wgt * wgt * (3 - 2 * wgt)  # smoothstep
    # Across the central seam cross use the original (continuous there). The borders
    # of the result come from `shifted`, whose opposite edges are neighbours in the
    # original image, so the tile repeats without visible seams.
    out = shifted * (1 - wgt[..., None]) + a * wgt[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def tile_fill(tile: Image.Image, size: int) -> Image.Image:
    out = Image.new("RGB", (size, size))
    for y in range(0, size, tile.height):
        for x in range(0, size, tile.width):
            out.paste(tile, (x, y))
    return out


def shadow(size, radius=30, offset=(0, 18), opacity=110, spread=0):
    """Returns RGBA shadow layer bigger than size by margins (m) and the margin."""
    w, h = size
    m = radius * 3
    layer = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle((m + offset[0] - spread, m + offset[1] - spread, m + offset[0] + w + spread, m + offset[1] + h + spread), fill=(0, 0, 0, opacity))
    return layer.filter(ImageFilter.GaussianBlur(radius)), m


def paste_with_shadow(canvas: Image.Image, img: Image.Image, xy, radius=28, offset=(0, 16), opacity=95, angle=0):
    img = img.convert("RGBA")
    if angle:
        img = img.rotate(angle, expand=True, resample=Image.BICUBIC)
    m = radius * 3
    # shadow follows the alpha channel, so cut-out (transparent) images get a natural shadow
    a = img.getchannel("A").point(lambda v: v * opacity // 255)
    sh = Image.new("RGBA", (img.width + 2 * m, img.height + 2 * m), (0, 0, 0, 0))
    dark = Image.new("RGBA", img.size, (0, 0, 0, 255))
    dark.putalpha(a)
    sh.paste(dark, (m + offset[0], m + offset[1]), dark)
    sh = sh.filter(ImageFilter.GaussianBlur(radius))
    if canvas.mode == "RGBA":
        canvas.alpha_composite(sh, (int(xy[0] - m), int(xy[1] - m)))
        canvas.alpha_composite(img, (int(xy[0]), int(xy[1])))
    else:
        canvas.paste(sh, (int(xy[0] - m), int(xy[1] - m)), sh)
        canvas.paste(img, (int(xy[0]), int(xy[1])), img)


def fit_text(draw, text, kind, max_w, start_size, min_size=18):
    size = start_size
    while size > min_size:
        f = font(kind, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return font(kind, min_size)


def wrap_text(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=f) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def make_zips(base_name: str, files: list, readme: str, limit_mb=19.0, max_zips=5):
    """Pack [(name, bytes)] into one or more ZIPs each below limit_mb (Etsy limit 20MB).
    Returns [(zip_name, bytes)]."""
    limit = int(limit_mb * 1024 * 1024)
    groups, cur, cur_size = [], [], 0
    for name, data in files:
        if cur and cur_size + len(data) > limit - 200_000:
            groups.append(cur)
            cur, cur_size = [], 0
        cur.append((name, data))
        cur_size += len(data)
    if cur:
        groups.append(cur)
    if len(groups) > max_zips:
        raise ValueError(f"Dosyalar {max_zips} ZIP'e sığmıyor ({len(groups)})")
    out = []
    for i, g in enumerate(groups, 1):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("README.txt", readme)
            for name, data in g:
                z.writestr(name, data, compress_type=zipfile.ZIP_STORED if name.lower().endswith((".jpg", ".png", ".pdf")) else zipfile.ZIP_DEFLATED)
        suffix = f"-part{i}" if len(groups) > 1 else ""
        out.append((f"{base_name}{suffix}.zip", b.getvalue()))
    return out
