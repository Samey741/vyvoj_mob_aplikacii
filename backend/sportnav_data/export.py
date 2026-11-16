"""Export of enriched venues to the SQLite database bundled in the app (DESIGN.md sections 3.3, 8.1, 8.2, 9.1).

Input records are the enriched venues produced by `enrich.py` (scraper keys `id`, `title`, `street`,
`city`, `phone`, `website`, `categories` plus `lat`, `lon`, `opening_hours`, `gps_source`, `gps_pending`).

Rules applied here:
    * `categories` holds exactly the 7 categories of `CATEGORIES` (section 8.2), ids 1..7 in that order.
    * Scraper category names are mapped to slugs with `map_category_names`; an unknown name is logged
      and skipped, the venue itself is still saved (without that category).
    * Section 8.1: `gps_pending = 1  <=>  lat IS NULL  <=>  lon IS NULL`. The invariant is enforced here
      from the actual coordinates, whatever `gps_pending` the record claims; a venue without usable
      coordinates is stored with NULL lat / lon / gps_source and `gps_pending = 1`.
    * A record without an integer `id` or without a `title` cannot be stored (`id` is the primary key,
      `name` is NOT NULL); it is logged and skipped. For a duplicate `id` the first record wins.
    * Opening hours are written as given (already normalized by `enrich.py`); malformed entries are
      logged and skipped.
"""

from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
from pathlib import Path

from .categories import CATEGORIES, map_category_names

logger = logging.getLogger(__name__)

_DAYS = frozenset(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))
# Valid HH:MM, 00:00-23:59 (what normalize_opening_hours produces; closes < opens means overnight).
_TIME_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")

# Section 3.3, verbatim apart from formatting of comments.
_SCHEMA = """
CREATE TABLE venues (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    street      TEXT,
    city        TEXT,
    lat         REAL,     -- NULL iff gps_pending = 1
    lon         REAL,     -- NULL iff gps_pending = 1
    phone       TEXT,
    website     TEXT,
    gps_source  TEXT,
    gps_pending INTEGER DEFAULT 0  -- 1 ak GPS nebola nájdená
);

CREATE TABLE categories (
    id    INTEGER PRIMARY KEY,
    slug  TEXT NOT NULL,
    name  TEXT NOT NULL
);

CREATE TABLE venue_categories (
    venue_id    INTEGER REFERENCES venues(id),
    category_id INTEGER REFERENCES categories(id)
);

CREATE TABLE opening_hours (
    venue_id  INTEGER REFERENCES venues(id),
    day       TEXT,   -- 'mon', 'tue', ...
    opens     TEXT,   -- '06:00'
    closes    TEXT    -- '22:00'
);

-- Geospatial index pre rýchle vyhľadávanie v okolí
CREATE INDEX idx_venues_location ON venues(lat, lon);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the tables and the index of DESIGN.md section 3.3 (the database must be empty)."""
    conn.executescript(_SCHEMA)


def _text(value: object) -> str | None:
    """Stripped non-empty string, else None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coordinates(venue: dict) -> tuple[float, float] | None:
    lat, lon = venue.get("lat"), venue.get("lon")
    for value in (lat, lon):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            logger.warning("Venue %s has unusable coordinates, marking gps_pending", venue.get("id"))
            return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        logger.warning("Venue %s has out-of-range coordinates, marking gps_pending", venue.get("id"))
        return None
    return float(lat), float(lon)


def _hours(venue_id: int, hours: object) -> list[tuple[str, str, str]]:
    if not hours:
        return []
    if not isinstance(hours, (list, tuple)):
        logger.warning("Venue %s: opening_hours is not a list, ignored", venue_id)
        return []
    rows: list[tuple[str, str, str]] = []
    for item in hours:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 3
            and isinstance(item[0], str)  # an unhashable day must not raise in the `in` test below
            and item[0] in _DAYS
            and isinstance(item[1], str)
            and isinstance(item[2], str)
            and _TIME_RE.fullmatch(item[1])  # fullmatch: no trailing newline, unlike `$`
            and _TIME_RE.fullmatch(item[2])
        ):
            rows.append((item[0], item[1], item[2]))
        else:
            logger.warning("Venue %s: malformed opening hours entry skipped: %r", venue_id, item)
    return rows


def _write(conn: sqlite3.Connection, venues: list[dict]) -> None:
    category_ids = {slug: idx for idx, (slug, _name) in enumerate(CATEGORIES, start=1)}
    conn.executemany(
        "INSERT INTO categories (id, slug, name) VALUES (?, ?, ?)",
        [(category_ids[slug], slug, name) for slug, name in CATEGORIES],
    )

    seen: set[int] = set()
    for venue in venues:
        if not isinstance(venue, dict):
            logger.warning("Record skipped, not an object: %r", type(venue).__name__)
            continue
        venue_id = venue.get("id")
        name = _text(venue.get("title"))
        if isinstance(venue_id, bool) or not isinstance(venue_id, int) or name is None:
            logger.warning("Record skipped, missing integer id or title: id=%r", venue_id)
            continue
        if venue_id in seen:
            logger.warning("Duplicate venue id %s skipped", venue_id)
            continue
        seen.add(venue_id)

        coords = _coordinates(venue)
        if coords is None:
            lat = lon = gps_source = None
            gps_pending = 1
        else:
            lat, lon = coords
            gps_source = _text(venue.get("gps_source"))
            gps_pending = 0

        conn.execute(
            "INSERT INTO venues (id, name, street, city, lat, lon, phone, website, gps_source, gps_pending) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                venue_id,
                name,
                _text(venue.get("street")),
                _text(venue.get("city")),
                lat,
                lon,
                _text(venue.get("phone")),
                _text(venue.get("website")),
                gps_source,
                gps_pending,
            ),
        )

        # Unknown names are logged and skipped by map_category_names; the venue stays (section 8.2).
        slugs = map_category_names(venue.get("categories"))
        conn.executemany(
            "INSERT INTO venue_categories (venue_id, category_id) VALUES (?, ?)",
            [(venue_id, category_ids[slug]) for slug in slugs],
        )
        conn.executemany(
            "INSERT INTO opening_hours (venue_id, day, opens, closes) VALUES (?, ?, ?, ?)",
            [(venue_id, day, opens, closes) for day, opens, closes in _hours(venue_id, venue.get("opening_hours"))],
        )


def export_venues(venues: list[dict], path: str) -> None:
    """Create a fresh SQLite database at `path` (an existing file is replaced) and write the venues.

    The database is written in a single transaction; on failure no partial file is left behind.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    conn = sqlite3.connect(str(target))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        create_schema(conn)
        with conn:  # one transaction: commit on success, rollback on error
            _write(conn, venues)
    except BaseException:
        conn.close()
        try:
            os.remove(target)
        except OSError:
            pass
        raise
    else:
        conn.close()
