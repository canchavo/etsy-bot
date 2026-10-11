from .. import images, mockups
from ..imgutil import jpeg_bytes, make_zips, png_bytes, thumb_b64, upscale

LABEL_TR = "Tumbler sublimasyon baskısı (20 oz, 2 tasarım PNG)"
SPEC_FIELDS = """
  "collection_name": "short collection name, 2-4 words",
  "designs": [ exactly 2 objects {"name": "short design name", "prompt": "English prompt describing ONE full-wrap tumbler design: motifs, background, arrangement across a wide rectangle"} ]
"""

SUFFIX = ("full bleed wide rectangular artwork for a tumbler wrap, design covering the whole canvas edge to edge, "
          "flat 2D illustration, no text, no letters, no tumbler, no cup, no mockup, no border")

SIZE = (2790, 2460)  # 20oz skinny straight tumbler, 9.3 x 8.2 in @300dpi


def build(spec, slug):
    style = spec.get("style", "")
    palette = spec.get("palette", [])
    designs = []
    for d in spec["designs"][:2]:
        raw = images.generate(f"{d['prompt']}, {style}, color palette {', '.join(palette)}, {SUFFIX}", 1920, 1696)
        designs.append((d["name"], upscale(raw, *SIZE)))
    files = []
    for i, (name, im) in enumerate(designs, 1):
        safe = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")[:30] or "design"
        files.append((f"{i:02d}-{safe}-20oz-skinny.png", png_bytes(im)))
    readme = (f"{spec['title']}\n\nThank you for your purchase!\n\n{len(files)} tumbler wrap designs, 2790x2460 px PNG (9.3 x 8.2 in) at 300 DPI.\n"
              "Sized for 20 oz skinny STRAIGHT tumblers. Check your blank's template before printing and mirror the image if your process requires it.\n"
              "License: personal and small business commercial use (up to 500 physical products). Reselling or sharing the digital files is not allowed.\n")
    delivery = make_zips(slug, files, readme)
    name = spec.get("collection_name", "Tumbler Wrap")
    mock = [(f"0{i}-tumbler.jpg", mockups.tumbler_mockup(im, palette)) for i, (_, im) in enumerate(designs, 1)]
    mock += [
        ("03-cover.jpg", mockups.cover([im for _, im in designs], name, "20 oz Skinny Tumbler Sublimation PNG  •  300 DPI", palette, layout="row")),
        ("04-info.jpg", mockups.info_card("WHAT YOU GET", [
            f"{len(designs)} full-wrap designs",
            "2790 x 2460 px PNG, 300 DPI",
            "For 20 oz skinny straight tumblers",
            "Sublimation and printable vinyl ready",
        ], palette, designs[0][1])),
        ("05-how.jpg", mockups.how_it_works(palette)),
    ]
    return {
        "delivery": delivery,
        "mockups": [(n, jpeg_bytes(im, 88, dpi=72)) for n, im in mock],
        "thumb": thumb_b64(mock[0][1]),
        "preview": mock[0][1],
        "included": [f"{len(designs)} tumbler wrap designs as PNG", "Delivered as ZIP"],
        "details": ["2790 x 2460 px (9.3 x 8.2 in), 300 DPI", "For 20 oz skinny straight tumblers"],
        "usage": ["Sublimation, printable vinyl or waterslide", "Tumbler, blank and mockup props are not included"],
        "license": "Personal and small business commercial use for physical products (up to 500 items). Reselling or sharing the digital files is not allowed.",
        "taxonomy": ["Clip Art & Image Files", "Digital Prints"],
        "taxonomy_fallback_id": 6844,
        "is_supply": True,
    }
