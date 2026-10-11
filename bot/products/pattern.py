from PIL import Image

from .. import images, mockups
from ..imgutil import jpeg_bytes, make_zips, offset_seamless, thumb_b64, tile_fill

LABEL_TR = "Dijital kağıt / desen paketi (10 adet, 12x12 inç)"
SPEC_FIELDS = """
  "pack_name": "short collection name, 2-4 words",
  "papers": [ exactly 10 objects {"name": "short pattern name", "prompt": "English prompt describing ONE repeating surface pattern: motifs, arrangement, background color"} ]
"""

SUFFIX = ("seamless repeating surface pattern, flat 2D textile print design, evenly distributed motifs covering the whole tile edge to edge, "
          "top-down view, no text, no letters, no border, no frame, no mockup")

SIZE = 3600  # 12x12 in @300dpi


def build(spec, slug):
    style = spec.get("style", "")
    palette = spec.get("palette", [])
    papers = []
    for p in spec["papers"][:10]:
        raw = images.generate(f"{p['prompt']}, {style}, color palette {', '.join(palette)}, {SUFFIX}", 1024, 1024)
        tile = offset_seamless(raw, blend=0.14).resize((1800, 1800), Image.LANCZOS)
        papers.append((p["name"], tile_fill(tile, SIZE)))
    files = []
    for i, (name, im) in enumerate(papers, 1):
        safe = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")[:30] or "paper"
        files.append((f"{i:02d}-{safe}.jpg", jpeg_bytes(im, 90)))
    readme = (f"{spec['title']}\n\nThank you for your purchase!\n\n{len(files)} seamless digital papers, 12x12 inch, 300 DPI JPG.\n"
              "License: personal and small business commercial use (up to 500 physical products).\n"
              "You may NOT resell, share or redistribute the digital files themselves.\n")
    delivery = make_zips(slug, files, readme)

    name = spec.get("pack_name", "Digital Paper Pack")
    prevs = [im.resize((900, 900), Image.LANCZOS) for _, im in papers]
    mock = [
        ("01-cover.jpg", mockups.cover(prevs[:5], name, f"{len(papers)} Seamless Digital Papers  •  12x12 in  •  300 DPI", palette)),
        ("02-all.jpg", mockups.grid(prevs, f"{len(papers)} Digital Papers Included", palette, cols=5)),
        ("03-info.jpg", mockups.info_card("WHAT YOU GET", [
            f"{len(papers)} seamless patterns",
            "12x12 inch JPG files, 300 DPI",
            "Perfect for scrapbooking, card making, gift wrap, backgrounds and crafts",
            "Commercial use for small businesses (up to 500 items)",
        ], palette, prevs[0])),
        ("04-how.jpg", mockups.how_it_works(palette)),
    ]
    return {
        "delivery": delivery,
        "mockups": [(n, jpeg_bytes(im, 88, dpi=72)) for n, im in mock],
        "thumb": thumb_b64(mock[0][1]),
        "preview": mock[0][1],
        "included": [f"{len(papers)} seamless digital papers", "12x12 inch, 3600x3600 px JPG", "Delivered as ZIP"],
        "details": ["300 DPI", "Seamless edges – tile them for larger projects"],
        "usage": ["Scrapbooking, card making, journals, party decor, gift wrap and digital backgrounds",
                  "Unzip the file on a computer before use"],
        "license": "Personal and small business commercial use for physical products (up to 500 items). Reselling or sharing the digital files is not allowed.",
        "taxonomy": ["Digital Paper", "Clip Art & Image Files"],
        "taxonomy_fallback_id": 6844,
        "is_supply": True,
    }
