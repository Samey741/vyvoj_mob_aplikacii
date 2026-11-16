"""Static mapping of Multisport category names (as returned by the scraper) to filter slugs.

See DESIGN.md section 3.1 (slug table) and section 8.2 (unknown category is logged and skipped).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

logger = logging.getLogger(__name__)

# (slug, name) in the order they are written to the `categories` table.
CATEGORIES: list[tuple[str, str]] = [
    ("bazeny-a-vodni-sporty-1", "Bazény a vodní sporty"),
    ("joga-a-zdravotni-cviceni-3", "Jóga a zdravotní cvičení"),
    ("lezecke-steny-4", "Lezecké stěny"),
    ("posilovny-a-silove-treninky-5", "Posilovny a silové tréninky"),
    ("raketove-a-micove-sporty-7", "Raketové a míčové sporty"),
    ("skupinove-a-tanecni-lekce-9", "Skupinové a taneční lekce"),
    ("wellness-a-relax-10", "Wellness a relax"),
]

# category name -> slug
CATEGORY_SLUGS: dict[str, str] = {name: slug for slug, name in CATEGORIES}


def map_category_names(names: Iterable[str] | str | None) -> list[str]:
    """Map scraper category names to slugs.

    Unknown names are logged (WARNING) and skipped; this never raises, so the venue
    itself is always kept. Duplicates are removed, order of first occurrence is kept.

    Input handling: a single `str` is treated as ONE category name (not iterated per
    character). `None` or any non-iterable value (e.g. 5) yields [] and is logged (WARNING).
    """
    if isinstance(names, str):
        names = [names]
    try:
        items = list(names)
    except TypeError:
        logger.warning("Categories ignored, not an iterable of names: %r", names)
        return []
    slugs: list[str] = []
    for name in items:
        slug = CATEGORY_SLUGS.get(name.strip()) if isinstance(name, str) else None
        if slug is None:
            logger.warning("Unknown category skipped: %r", name)
            continue
        if slug not in slugs:
            slugs.append(slug)
    return slugs
