import io

from PIL import Image

from .. import images, mockups
from ..imgutil import jpeg_bytes, thumb_b64

LABEL_TR = "Boyama sayfaları (8 sayfa, PDF)"
SPEC_FIELDS = """
  "audience": "adults or kids",
  "book_name": "short collection name, 2-5 words",
  "pages": [ exactly 8 objects {"name": "...", "prompt": "detailed English prompt describing ONE coloring page scene/subject and its composition. Line art only."} ]
"""

LETTER = (2550, 3300)  # 8.5x11 in @300dpi
A4 = (2480, 3508)


def _suffix(audience):
    if str(audience).lower().startswith("kid"):
        detail = "simple bold thick outlines, large open areas, cute friendly style suitable for children"
    else:
        detail = "intricate detailed outlines for adults, many small areas to color"
    return (f"Black and white coloring book page, {detail}, clean crisp black line art on pure white background, "
            "no shading, no gray tones, no color, no fill, no text, no letters, no border, no frame, full page composition.")


def _page(lineart: Image.Image, size):
    pw, ph = size
    margin = int(pw * 0.06)
    box_w, box_h = pw - 2 * margin, ph - 2 * margin
    g = lineart.convert("L")
    s = min(box_w / g.width, box_h / g.height)
    g = g.resize((int(g.width * s), int(g.height * s)), Image.LANCZOS)
    bw = g.point(lambda v: 255 if v > 165 else 0, mode="L")
    page = Image.new("L", (pw, ph), 255)
    page.paste(bw, ((pw - bw.width) // 2, (ph - bw.height) // 2))
    return page.convert("1")


def _pdf(pages):
    b = io.BytesIO()
    pages[0].save(b, "PDF", save_all=True, append_images=pages[1:], resolution=300)
    return b.getvalue()


def build(spec, slug):
    audience = spec.get("audience", "adults")
    raws = []
    for p in spec["pages"][:8]:
        raws.append(images.generate(f"{p['prompt']}. {_suffix(audience)}", 1488, 1920))
    letter = [_page(r, LETTER) for r in raws]
    a4 = [_page(r, A4) for r in raws]
    delivery = [
        (f"{slug}-US-Letter.pdf", _pdf(letter)),
        (f"{slug}-A4.pdf", _pdf(a4)),
    ]
    palette = spec.get("palette", [])
    previews = [p.convert("L").convert("RGB") for p in letter]
    name = spec.get("book_name", "Coloring Pages")
    colored = mockups.colored_preview(letter[0], palette, seed=len(slug))
    mock = [
        ("01-cover.jpg", mockups.cover(previews[:4], name, f"{len(letter)} Printable Coloring Pages  •  Letter & A4 PDF", palette)),
        ("02-all.jpg", mockups.grid(previews, f"{len(letter)} Coloring Pages Included", palette, cols=4)),
        ("03-example.jpg", mockups.info_card("COLOR YOUR WAY", [
            "Use colored pencils, markers or crayons",
            "Print as many times as you like",
            "US Letter and A4 PDFs included",
            "Single-sided pages, 300 DPI",
        ], palette, colored)),
    ]
    for i, pv in enumerate(previews[1:3], 4):
        mock.append((f"0{i}-page.jpg", mockups.info_card(name.upper(), [p["name"] for p in spec["pages"][:8]][:6], palette, pv)))
    mock.append(("06-how.jpg", mockups.how_it_works(palette)))
    return {
        "delivery": delivery,
        "mockups": [(n, jpeg_bytes(im, 88, dpi=72)) for n, im in mock],
        "thumb": thumb_b64(mock[0][1]),
        "preview": mock[0][1],
        "included": [
            f"{len(letter)} printable coloring pages",
            "1 PDF in US Letter size (8.5x11 in)",
            "1 PDF in A4 size",
        ],
        "details": ["300 DPI, crisp black line art", "Single-sided pages with margins for easy printing"],
        "usage": ["Print at home on regular or thicker paper", "Print as many copies as you need for your own use"],
        "license": "For personal and classroom use only. Please do not share, resell or redistribute the files.",
        "taxonomy": ["Coloring Books", "Coloring Pages", "Digital Prints"],
        "taxonomy_fallback_id": 2078,
        "is_supply": False,
    }
