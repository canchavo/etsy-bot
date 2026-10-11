"""Product types. Each module exposes:
    LABEL_TR   – Turkish label for Telegram/panel
    SPEC_FIELDS – extra JSON fields the AI must return (text, embedded in the prompt)
    build(spec, slug) -> dict(delivery=[(name, bytes)], mockups=[(name, bytes)],
                              thumb=PIL.Image, included=[str], details=[str], usage=[str],
                              license=str, taxonomy=[names], is_supply=bool)
"""
from . import clipart, coloring, pattern, tumbler, wall_art

TYPES = {
    "wall_art": wall_art,
    "coloring": coloring,
    "clipart": clipart,
    "pattern": pattern,
    "tumbler": tumbler,
}


def type_label(ptype: str) -> str:
    if ptype in TYPES:
        return TYPES[ptype].LABEL_TR
    return {"imported": "Abacus'tan aktarılan ürün"}.get(ptype, ptype)
