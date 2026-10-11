from PIL import Image

from .. import images, mockups
from ..imgutil import crop_ratio, jpeg_bytes, make_zips, thumb_b64, upscale, hex2rgb

LABEL_TR = "Duvar sanatı (3'lü set)"
DESCRIPTION_TR = "Baskıya hazır 3'lü duvar sanatı seti (5 farklı oran, 300 DPI)"
SPEC_FIELDS = """
  "set_name": "short collection name, 2-4 words, e.g. 'Sage Botanical Trio'",
  "room": "one of: living room, bedroom, nursery, kitchen, home office, bathroom, entryway",
  "frame_color": "hex color of the picture frames that suits the art (e.g. #2b2b2b black, #c8a165 oak, #f2f2f2 white)",
  "prints": [ exactly 3 objects {"name": "...", "prompt": "detailed English image prompt for ONE artwork of the cohesive set: subject, composition, medium/technique, mood. Do not mention text, frames or walls."} ]
"""

RATIOS = [
    ("2x3", 2 / 3, (4800, 7200), "2:3 ratio – 4x6, 8x12, 12x18, 16x24, 20x30, 24x36 in"),
    ("3x4", 3 / 4, (5400, 7200), "3:4 ratio – 6x8, 9x12, 12x16, 18x24 in"),
    ("4x5", 4 / 5, (4800, 6000), "4:5 ratio – 4x5, 8x10, 16x20 in"),
    ("ISO", 1 / 2 ** 0.5, (4961, 7016), "ISO ratio – A5, A4, A3, A2, A1"),
    ("11x14", 11 / 14, (3300, 4200), "11x14 in"),
]

SUFFIX = ("Fine art print artwork filling the whole canvas, flat 2D artwork, centered composition with breathing room, "
          "high detail, gallery quality. No frame, no border, no wall, no mockup, no text, no letters, no signature, no watermark.")


def build(spec, slug):
    style = spec.get("style", "")
    palette = spec.get("palette", [])
    arts = []
    for p in spec["prints"][:3]:
        prompt = f"{p['prompt']}. Style: {style}. Color palette: {', '.join(palette)}. {SUFFIX}"
        arts.append(images.generate(prompt, 1280, 1920))

    readme = (
        f"{spec['title']}\n\nThank you for your purchase!\n\n"
        "This download contains 3 high resolution (300 DPI) JPG prints in 5 aspect ratios, one ZIP per ratio:\n"
        + "\n".join(f"  - {r[3]}" for r in RATIOS)
        + "\n\nTip: print at home on matte or photo paper, or upload the files to a local/online print shop.\n"
          "Larger sizes (24x36 in, A1) print at around 200 DPI, which looks great at normal viewing distance.\n\n"
          "For personal use only. Please do not share, resell or redistribute the files.\n"
    )
    delivery = []
    for tag, ratio, (pw, ph), _ in RATIOS:
        for quality in (90, 86, 80, 74):
            files = []
            for i, art in enumerate(arts, 1):
                img = upscale(crop_ratio(art, ratio), pw, ph)
                files.append((f"{slug}-print{i}-{tag}.jpg", jpeg_bytes(img, quality)))
            if sum(len(b) for _, b in files) < 18.5 * 1024 * 1024:
                break
        delivery += make_zips(f"{slug}-{tag}", files, readme)

    frame_rgb = hex2rgb(spec.get("frame_color") or "#2b2b2b")
    room_prompt = (
        f"Interior design photograph of a {spec.get('room', 'living room')} with {style} decor, "
        "a large empty plain painted wall filling the upper half of the image, furniture only along the bottom edge, "
        "soft natural daylight, realistic, high detail, eye level. Absolutely nothing hanging on the wall: no pictures, no frames, no art, no shelves, no text."
    )
    mock = []
    try:
        room = images.generate(room_prompt, 1920, 1440)
        mock.append(("01-room.jpg", mockups.room_mockup(room, arts, frame_rgb)))
    except Exception as e:
        print(f"[wall_art] oda görseli üretilemedi, sade duvar kullanılıyor: {e}")
    pal = mockups.palette_colors(palette)
    wall = mockups._mix(pal["bg"], (200, 196, 188), 0.35)
    mock.append(("02-cover.jpg", mockups.cover(arts, spec.get("set_name", "Wall Art Set"), "Set of 3 Printable Wall Art  •  5 Ratios  •  300 DPI", palette)))
    for i, art in enumerate(arts, 1):
        mock.append((f"0{2 + i}-print{i}.jpg", mockups.wall_mockup(art, wall, frame_rgb)))
    mock.append(("06-sizes.jpg", mockups.info_card("5 RATIOS • 15 FILES", [r[3] for r in RATIOS] + ["High resolution 300 DPI JPG"], palette, arts[0])))
    mock.append(("07-how.jpg", mockups.how_it_works(palette)))

    return {
        "delivery": delivery,
        "mockups": [(n, jpeg_bytes(im, 88, dpi=72)) for n, im in mock],
        "thumb": thumb_b64(mock[0][1]),
        "preview": mock[0][1],
        "included": [
            "3 printable wall art designs",
            "5 ZIP files (one per aspect ratio), 15 high resolution JPG files in total",
            "300 DPI, print-ready",
        ],
        "details": [r[3] for r in RATIOS],
        "usage": [
            "Print at home on matte or photo paper",
            "Or upload the files to a local or online print shop",
            "Frames, mats and props in the photos are not included",
        ],
        "license": "For personal use only. Please do not share, resell or redistribute the files.",
        "taxonomy": ["Digital Prints"],
        "taxonomy_fallback_id": 2078,
        "is_supply": False,
    }
