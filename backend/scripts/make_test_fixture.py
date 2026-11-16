"""Regenerates the iOS test database `frontend/SportNavTests/Fixtures/test_venues.sqlite` (DESIGN.md 9.2, 11.2).

    cd backend && python scripts/make_test_fixture.py [--output <path>.sqlite]

The records below are hand-written *enriched* venues (no network, no API keys); they are written by the
same `export_venues` that `build_db.py` uses, so the schema is exactly section 3.3. The result is
deterministic; `tests/test_export.py` checks that the committed fixture matches this script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sportnav_data.export import export_venues  # noqa: E402

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "SportNavTests" / "Fixtures" / "test_venues.sqlite"
)

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri")


def _hours(days: tuple[str, ...], opens: str, closes: str) -> list[tuple[str, str, str]]:
    return [(day, opens, closes) for day in days]


FIXTURE_VENUES: list[dict] = [
    {  # 1: single category, Apple Maps, weekday hours
        "id": 1,
        "title": "Legion Gym",
        "categories": ["Posilovny a silové tréninky"],
        "activities": ["Funkční trénink", "Posilovna"],
        "street": "Husova 100",
        "city": "Jaroměř",
        "phone": "+420 606 182 647",
        "website": "http://legiongym.cz/",
        "lat": 50.3563,
        "lon": 15.9223,
        "opening_hours": _hours(_WEEKDAYS, "06:00", "22:00") + [("sat", "08:00", "20:00")],
        "gps_source": "apple_maps",
        "gps_pending": 0,
    },
    {  # 2: two categories, closing after midnight on Friday
        "id": 2,
        "title": "Aquapark Bratislava",
        "categories": ["Bazény a vodní sporty", "Wellness a relax"],
        "street": "Mliekarenská 10",
        "city": "Bratislava",
        "phone": "+421 2 5555 0102",
        "website": "https://aquapark.example/",
        "lat": 48.1486,
        "lon": 17.1077,
        "opening_hours": _hours(("mon", "tue", "wed", "thu"), "06:00", "22:00") + [("fri", "06:00", "02:00")],
        "gps_source": "apple_maps",
        "gps_pending": 0,
    },
    {  # 3: Google fallback -> GPS only, no opening hours, no phone / website
        "id": 3,
        "title": "Joga Studio Lotos",
        "categories": ["Jóga a zdravotní cvičení"],
        "street": "Kvetná 5",
        "city": "Košice",
        "phone": None,
        "website": None,
        "lat": 48.7164,
        "lon": 21.2611,
        "opening_hours": [],
        "gps_source": "google_places_fallback",
        "gps_pending": 0,
    },
    {  # 4: climbing wall, every day
        "id": 4,
        "title": "Lezecká stěna Smíchov",
        "categories": ["Lezecké stěny"],
        "street": "Nádražní 20",
        "city": "Praha",
        "phone": "+420 777 000 004",
        "website": "https://lezeni.example/",
        "lat": 50.0714,
        "lon": 14.4036,
        "opening_hours": _hours(_WEEKDAYS + ("sat", "sun"), "09:00", "23:00"),
        "gps_source": "apple_maps",
        "gps_pending": 0,
    },
    {  # 5: racket and ball sports + group lessons, two blocks on one day
        "id": 5,
        "title": "Squash Centrum Brno",
        "categories": ["Raketové a míčové sporty", "Skupinové a taneční lekce"],
        "street": "Cejl 15",
        "city": "Brno",
        "phone": "+420 777 000 005",
        "website": None,
        "lat": 49.1951,
        "lon": 16.6068,
        "opening_hours": [("mon", "07:00", "12:00"), ("mon", "14:00", "21:00"), ("tue", "07:00", "21:00")],
        "gps_source": "apple_maps",
        "gps_pending": 0,
    },
    {  # 6: group / dance lessons
        "id": 6,
        "title": "Tanečná škola Rytmus",
        "categories": ["Skupinové a taneční lekce"],
        "street": "Hlavná 8",
        "city": "Nitra",
        "phone": None,
        "website": "https://rytmus.example/",
        "lat": 48.3069,
        "lon": 18.0864,
        "opening_hours": _hours(("tue", "thu"), "17:00", "21:00"),
        "gps_source": "apple_maps",
        "gps_pending": 0,
    },
    {  # 7: gps_pending = 1 -> NULL lat / lon, kept in the DB but not loaded by the app (section 8.1)
        "id": 7,
        "title": "Wellness Neznáma 1",
        "categories": ["Wellness a relax"],
        "street": "Neznáma 1",
        "city": "Žilina",
        "phone": "+421 41 555 0107",
        "website": None,
        "lat": None,
        "lon": None,
        "opening_hours": [],
        "gps_source": None,
        "gps_pending": 1,
    },
    {  # 8: unknown category only -> venue saved, no venue_categories row (section 8.2)
        "id": 8,
        "title": "Bowling Klub Neznámy",
        "categories": ["Bowling a biliár"],
        "street": "Dlhá 3",
        "city": "Trnava",
        "phone": None,
        "website": None,
        "lat": 48.3774,
        "lon": 17.5883,
        "opening_hours": _hours(("sat", "sun"), "12:00", "23:00"),
        "gps_source": "apple_maps",
        "gps_pending": 0,
    },
    {  # 9: known + unknown category -> only the known one is linked
        "id": 9,
        "title": "Fitness Plus",
        "categories": ["Posilovny a silové tréninky", "Bowling a biliár"],
        "street": "Hlavná 99",
        "city": "Poprad",
        "phone": "+421 52 555 0109",
        "website": "https://fitnessplus.example/",
        "lat": 49.0614,
        "lon": 20.2979,
        "opening_hours": [("mon", "00:00", "23:59")],
        "gps_source": "apple_maps",
        "gps_pending": 0,
    },
]


def build_fixture(output: Path = DEFAULT_OUTPUT) -> Path:
    export_venues([dict(v) for v in FIXTURE_VENUES], str(output))
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate the iOS test fixture database.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(f"Wrote {build_fixture(args.output)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
