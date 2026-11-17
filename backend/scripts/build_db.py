"""CLI that builds venues.sqlite from scraped venues (DESIGN.md sections 3.2, 3.3, 8.3, 8.4, 8.9, 9.1, 12).

    python scripts/build_db.py --input data/venues_raw.json --output ../frontend/app/src/main/assets/venues.sqlite

No environment variable is required. Optional (environment or `backend/.env`, see `.env.example`):
    NOMINATIM_EMAIL   contact e-mail sent to Nominatim as the `email` parameter (usage policy, section 8.3)

The e-mail is never printed or logged by this script. Exit code 1 on any fatal error, including
HTTP 403 from Nominatim (section 8.9); the database is then not written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# Allow `python scripts/build_db.py` from the backend directory (sys.path[0] is scripts/ then).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from sportnav_data.enrich import NominatimBlockedError, enrich_all  # noqa: E402
from sportnav_data.export import export_venues  # noqa: E402

logger = logging.getLogger("build_db")

BACKEND_DIR = Path(__file__).resolve().parent.parent
PENDING_WARN_SHARE = 0.10  # section 12: warn when more than 10 % of venues have no GPS
MIN_REQUEST_INTERVAL = 1.0  # Nominatim usage policy: at most 1 request per second (section 3.2)
GPS_SOURCES = ("nominatim_poi", "nominatim_address")


class BuildError(Exception):
    """A fatal, user-presentable error (the message never contains secrets)."""


def load_dotenv(path: Path) -> None:
    """Minimal `.env` reader: KEY=VALUE lines; variables already in the environment win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


def read_venues(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BuildError(f"Cannot read input file {path}: {type(exc).__name__}") from None
    except ValueError as exc:
        raise BuildError(f"Input file {path} is not valid JSON: {exc}") from None
    if not isinstance(data, list) or not all(isinstance(v, dict) for v in data):
        raise BuildError(f"Input file {path} must contain a JSON array of venue objects")
    return data


def database_statistics(path: Path) -> dict:
    """Record count, gps_pending share and per-category counts of a built database."""
    conn = sqlite3.connect(str(path))
    try:
        total = conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM venues WHERE gps_pending = 1").fetchone()[0]
        per_source = dict(
            conn.execute(
                "SELECT gps_source, COUNT(*) FROM venues WHERE gps_source IS NOT NULL GROUP BY gps_source"
            ).fetchall()
        )
        uncategorized = conn.execute(
            "SELECT COUNT(*) FROM venues WHERE id NOT IN (SELECT venue_id FROM venue_categories)"
        ).fetchone()[0]
        per_category = conn.execute(
            "SELECT c.slug, COUNT(vc.venue_id) FROM categories c "
            "LEFT JOIN venue_categories vc ON vc.category_id = c.id GROUP BY c.id ORDER BY c.id"
        ).fetchall()
    finally:
        conn.close()
    return {
        "total": total,
        "gps_pending": pending,
        "gps_pending_share": (pending / total) if total else 0.0,
        "per_source": per_source,
        "uncategorized": uncategorized,
        "per_category": per_category,
    }


def format_statistics(stats: dict) -> str:
    lines = [
        f"Records written: {stats['total']}",
        f"gps_pending: {stats['gps_pending']} ({stats['gps_pending_share'] * 100:.1f} %)",
        "gps_source:",
        *[f"  {source}: {stats['per_source'].get(source, 0)}" for source in GPS_SOURCES],
        f"Venues without any known category: {stats['uncategorized']}",
        "Venues per category:",
    ]
    lines += [f"  {slug}: {count}" for slug, count in stats["per_category"]]
    if stats["gps_pending_share"] > PENDING_WARN_SHARE:
        lines.append(
            f"WARNING: gps_pending share is above {PENDING_WARN_SHARE * 100:.0f} % (DESIGN.md section 12)"
        )
    return "\n".join(lines)


def check_output_writable(path: Path) -> None:
    """Fail fast, before any network call, when the output file cannot be written.

    Creates the parent directory (as `export_venues` would) and probes it with a temporary file. An
    existing output file is opened for update without truncating (a locked or read-only file fails here);
    it is neither modified nor deleted.
    """
    try:
        if path.is_dir():
            raise IsADirectoryError(str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path.parent):
            pass
        if path.exists():
            with open(path, "r+b"):
                pass
    except OSError as exc:
        raise BuildError(f"Output file {path} is not writable ({type(exc).__name__}); nothing was fetched") from None


async def build(
    input_path: Path,
    output_path: Path,
    email: str | None = None,
    client: httpx.AsyncClient | None = None,
    min_interval: float | None = None,
) -> dict:
    """Read, enrich and export; returns the statistics of the written database.

    `client` can be injected (tests use `httpx.MockTransport`); otherwise a real client is created.
    Raises BuildError on fatal errors, including NominatimBlockedError (HTTP 403, section 8.9).
    """
    if min_interval is None:
        min_interval = MIN_REQUEST_INTERVAL
    venues = read_venues(input_path)
    check_output_writable(output_path)  # before the first request to Nominatim

    async def run(http: httpx.AsyncClient) -> list[dict]:
        try:
            return await enrich_all(venues, http, email, min_interval)
        except NominatimBlockedError as exc:
            raise BuildError(f"Nominatim blocked the import, run aborted: {exc}") from None

    if client is not None:
        enriched = await run(client)
    else:
        async with httpx.AsyncClient(timeout=30.0) as http:
            enriched = await run(http)

    try:
        export_venues(enriched, str(output_path))
        return database_statistics(output_path)
    except (OSError, sqlite3.Error) as exc:
        raise BuildError(f"Cannot write output file {output_path} ({type(exc).__name__})") from None


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build venues.sqlite from scraped venues (DESIGN.md).")
    parser.add_argument("--input", required=True, type=Path, help="scraper export, e.g. data/venues_raw.json")
    parser.add_argument("--output", required=True, type=Path, help="output SQLite file, e.g. venues.sqlite")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # httpx logs every request URL at INFO; keep it quiet (the URL carries the optional e-mail).
    logging.getLogger("httpx").setLevel(logging.WARNING)

    load_dotenv(BACKEND_DIR / ".env")
    email = os.environ.get("NOMINATIM_EMAIL", "").strip() or None

    try:
        stats = asyncio.run(build(args.input, args.output, email))
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_statistics(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
