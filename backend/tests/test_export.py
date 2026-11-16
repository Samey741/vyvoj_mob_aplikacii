import asyncio
import json
import logging
import os
import sqlite3
from pathlib import Path

import httpx
import pytest

from scripts import build_db
from scripts.make_test_fixture import DEFAULT_OUTPUT, FIXTURE_VENUES, build_fixture
from sportnav_data.categories import CATEGORIES
from sportnav_data.export import create_schema, export_venues

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def enriched(id_: int, title: str = "Venue", **extra) -> dict:
    record = {
        "id": id_,
        "title": title,
        "street": "Husova 100",
        "city": "Jaroměř",
        "phone": "+420 606 182 647",
        "website": "http://example.cz/",
        "categories": [],
        "lat": 50.0,
        "lon": 15.0,
        "opening_hours": [],
        "gps_source": "nominatim_poi",
        "gps_pending": 0,
    }
    record.update(extra)
    return record


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "out" / "venues.sqlite")


def rows(path: str, sql: str, params=()) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# --- schema exactly per DESIGN.md 3.3 ---------------------------------------------------------------

# (name, declared type, notnull, pk) in column order
EXPECTED_COLUMNS = {
    "venues": [
        ("id", "INTEGER", 0, 1),
        ("name", "TEXT", 1, 0),
        ("street", "TEXT", 0, 0),
        ("city", "TEXT", 0, 0),
        ("lat", "REAL", 0, 0),
        ("lon", "REAL", 0, 0),
        ("phone", "TEXT", 0, 0),
        ("website", "TEXT", 0, 0),
        ("gps_source", "TEXT", 0, 0),
        ("gps_pending", "INTEGER", 0, 0),
    ],
    "categories": [("id", "INTEGER", 0, 1), ("slug", "TEXT", 1, 0), ("name", "TEXT", 1, 0)],
    "venue_categories": [("venue_id", "INTEGER", 0, 0), ("category_id", "INTEGER", 0, 0)],
    "opening_hours": [
        ("venue_id", "INTEGER", 0, 0),
        ("day", "TEXT", 0, 0),
        ("opens", "TEXT", 0, 0),
        ("closes", "TEXT", 0, 0),
    ],
}


def test_create_schema_tables_columns_and_index_exactly_as_designed():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == set(EXPECTED_COLUMNS)

    for table, expected in EXPECTED_COLUMNS.items():
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        assert [(c[1], c[2], c[3], c[5]) for c in info] == expected, table

    # gps_pending DEFAULT 0
    default = {c[1]: c[4] for c in conn.execute("PRAGMA table_info(venues)")}["gps_pending"]
    assert default == "0"

    # foreign keys: venue_categories -> venues/categories, opening_hours -> venues
    def fks(table):
        return {(r[3], r[2], r[4]) for r in conn.execute(f"PRAGMA foreign_key_list({table})")}

    assert fks("venue_categories") == {("venue_id", "venues", "id"), ("category_id", "categories", "id")}
    assert fks("opening_hours") == {("venue_id", "venues", "id")}

    # exactly one explicit index: idx_venues_location ON venues(lat, lon)
    indexes = conn.execute("SELECT name, tbl_name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL").fetchall()
    assert indexes == [("idx_venues_location", "venues")]
    assert [r[2] for r in conn.execute("PRAGMA index_info(idx_venues_location)")] == ["lat", "lon"]
    conn.close()


def test_export_creates_schema_in_file(db_path):
    export_venues([], db_path)
    conn = sqlite3.connect(db_path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    conn.close()
    assert names == {"venues", "categories", "venue_categories", "opening_hours", "idx_venues_location"}
    assert rows(db_path, "SELECT COUNT(*) FROM venues") == [(0,)]


def test_export_replaces_existing_file_and_creates_parent_dir(db_path):
    export_venues([enriched(1), enriched(2)], db_path)
    export_venues([enriched(3)], db_path)
    assert rows(db_path, "SELECT id FROM venues") == [(3,)]


# --- row counts ---------------------------------------------------------------------------------------


def test_categories_table_holds_exactly_the_seven_categories(db_path):
    export_venues([], db_path)
    assert len(CATEGORIES) == 7
    assert rows(db_path, "SELECT slug, name FROM categories ORDER BY id") == list(CATEGORIES)


def test_row_counts_match_input(db_path):
    venues = [
        enriched(1, categories=["Wellness a relax", "Lezecké stěny"], opening_hours=[("mon", "06:00", "22:00")]),
        enriched(2, categories=["Bazény a vodní sporty"], opening_hours=[("mon", "07:00", "12:00"), ("mon", "14:00", "20:00")]),
        enriched(3, lat=None, lon=None, gps_source=None, gps_pending=1),
    ]
    export_venues(venues, db_path)
    assert rows(db_path, "SELECT COUNT(*) FROM venues") == [(3,)]
    assert rows(db_path, "SELECT COUNT(*) FROM venue_categories") == [(3,)]
    assert rows(db_path, "SELECT COUNT(*) FROM opening_hours") == [(3,)]
    assert rows(db_path, "SELECT COUNT(*) FROM categories") == [(7,)]


def test_venue_columns_are_stored(db_path):
    export_venues([enriched(193, "Legion Gym", street="Husova 100", city="Jaroměř")], db_path)
    assert rows(db_path, "SELECT id, name, street, city, lat, lon, phone, website, gps_source, gps_pending FROM venues") == [
        (193, "Legion Gym", "Husova 100", "Jaroměř", 50.0, 15.0, "+420 606 182 647", "http://example.cz/", "nominatim_poi", 0)
    ]


# --- links by venue_id ----------------------------------------------------------------------------------


def test_venue_categories_and_opening_hours_are_linked_to_the_right_venue(db_path):
    venues = [
        enriched(10, categories=["Lezecké stěny"], opening_hours=[("tue", "08:00", "20:00")]),
        enriched(
            20,
            categories=["Bazény a vodní sporty", "Wellness a relax"],
            opening_hours=[("mon", "06:00", "22:00"), ("fri", "22:00", "02:00")],
        ),
        enriched(30, categories=["Joga"], opening_hours=[]),  # nothing to link
    ]
    export_venues(venues, db_path)

    linked = rows(
        db_path,
        "SELECT vc.venue_id, c.slug FROM venue_categories vc JOIN categories c ON c.id = vc.category_id "
        "ORDER BY vc.venue_id, c.slug",
    )
    assert linked == [
        (10, "lezecke-steny-4"),
        (20, "bazeny-a-vodni-sporty-1"),
        (20, "wellness-a-relax-10"),
    ]
    assert rows(db_path, "SELECT venue_id, day, opens, closes FROM opening_hours ORDER BY venue_id, rowid") == [
        (10, "tue", "08:00", "20:00"),
        (20, "mon", "06:00", "22:00"),
        (20, "fri", "22:00", "02:00"),
    ]
    # no orphans: every link points to an existing venue / category
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_duplicate_categories_are_linked_once(db_path):
    export_venues([enriched(1, categories=["Lezecké stěny", "Lezecké stěny"])], db_path)
    assert rows(db_path, "SELECT COUNT(*) FROM venue_categories") == [(1,)]


# --- gps_pending <=> lat IS NULL ------------------------------------------------------------------------


def test_gps_pending_iff_lat_null(db_path):
    venues = [
        enriched(1),
        enriched(2, lat=None, lon=None, gps_source=None, gps_pending=1),
        # inconsistent input is normalized by the exporter, the invariant always holds
        enriched(3, lat=None, lon=None, gps_pending=0, gps_source="nominatim_poi"),
        enriched(4, lat=50.0, lon=None, gps_pending=0),
        enriched(5, gps_pending=1),  # claims pending but has coordinates
        {"id": 6, "title": "Raw record without enrichment keys"},
    ]
    export_venues(venues, db_path)

    assert rows(db_path, "SELECT id, gps_pending, lat IS NULL, lon IS NULL FROM venues ORDER BY id") == [
        (1, 0, 0, 0),
        (2, 1, 1, 1),
        (3, 1, 1, 1),
        (4, 1, 1, 1),
        (5, 0, 0, 0),
        (6, 1, 1, 1),
    ]
    # whole-table invariant
    assert rows(db_path, "SELECT COUNT(*) FROM venues WHERE (gps_pending = 1) <> (lat IS NULL)") == [(0,)]
    assert rows(db_path, "SELECT COUNT(*) FROM venues WHERE (gps_pending = 1) <> (lon IS NULL)") == [(0,)]
    # pending venues carry no gps_source
    assert rows(db_path, "SELECT COUNT(*) FROM venues WHERE gps_pending = 1 AND gps_source IS NOT NULL") == [(0,)]


@pytest.mark.parametrize("lat, lon", [(float("nan"), 15.0), (91.0, 15.0), (50.0, 181.0), ("50", "15"), (True, False)])
def test_unusable_coordinates_become_gps_pending(db_path, lat, lon):
    export_venues([enriched(1, lat=lat, lon=lon)], db_path)
    assert rows(db_path, "SELECT lat, lon, gps_pending FROM venues") == [(None, None, 1)]


# --- unknown category (8.2) -------------------------------------------------------------------------------


def test_unknown_category_is_logged_and_skipped_but_venue_is_saved(db_path, caplog):
    venues = [
        enriched(1, categories=["Bowling a biliár"]),
        enriched(2, categories=["Lezecké stěny", "Bowling a biliár"]),
    ]
    with caplog.at_level(logging.WARNING):
        export_venues(venues, db_path)

    assert "Bowling a biliár" in caplog.text
    assert rows(db_path, "SELECT id FROM venues ORDER BY id") == [(1,), (2,)]
    assert rows(db_path, "SELECT venue_id, category_id FROM venue_categories") == [(2, 3)]
    assert rows(db_path, "SELECT COUNT(*) FROM categories") == [(7,)]  # never extended


# --- robustness ---------------------------------------------------------------------------------------------


def test_invalid_records_are_skipped_and_logged(db_path, caplog):
    venues = [
        enriched(1),
        enriched(1, title="Duplicate"),
        {"title": "No id"},
        {"id": "7", "title": "String id"},
        {"id": 8, "title": "  "},
        "not a dict",
        enriched(2),
    ]
    with caplog.at_level(logging.WARNING):
        export_venues(venues, db_path)  # type: ignore[arg-type]
    assert rows(db_path, "SELECT id, name FROM venues ORDER BY id") == [(1, "Venue"), (2, "Venue")]
    assert "Duplicate venue id 1" in caplog.text


def test_malformed_opening_hours_are_skipped(db_path):
    hours = [("mon", "06:00", "22:00"), ("xyz", "06:00", "22:00"), ("tue", "6:00", "22:00"), ("wed",), "bad"]
    export_venues([enriched(1, opening_hours=hours), enriched(2, opening_hours="nonsense")], db_path)
    assert rows(db_path, "SELECT venue_id, day FROM opening_hours") == [(1, "mon")]


def test_unhashable_or_non_string_day_is_skipped_not_fatal(db_path, caplog):
    hours = [(["mon"], "06:00", "22:00"), ({"d": 1}, "06:00", "22:00"), (None, "06:00", "22:00"), ("sun", "06:00", "22:00")]
    with caplog.at_level(logging.WARNING):
        export_venues([enriched(1, opening_hours=hours)], db_path)
    assert rows(db_path, "SELECT day FROM opening_hours") == [("sun",)]
    assert "malformed opening hours" in caplog.text


@pytest.mark.parametrize(
    "opens, closes",
    [
        ("06:00\n", "22:00"),
        ("06:00", "22:00\n"),
        ("99:99", "22:00"),
        ("24:00", "22:00"),
        ("06:60", "22:00"),
        ("6:00", "22:00"),
        ("06:00", "22:00 "),
        ("０６:00", "22:00"),  # full-width digits
        ("", "22:00"),
    ],
)
def test_invalid_times_are_skipped_with_warning(db_path, caplog, opens, closes):
    with caplog.at_level(logging.WARNING):
        export_venues([enriched(1, opening_hours=[("mon", opens, closes), ("tue", "06:00", "22:00")])], db_path)
    assert rows(db_path, "SELECT day, opens, closes FROM opening_hours") == [("tue", "06:00", "22:00")]
    assert "malformed opening hours" in caplog.text


@pytest.mark.parametrize("opens, closes", [("00:00", "23:59"), ("18:00", "02:00"), ("09:05", "09:05")])
def test_valid_times_are_stored_including_24h_and_overnight(db_path, opens, closes):
    export_venues([enriched(1, opening_hours=[("mon", opens, closes)])], db_path)
    assert rows(db_path, "SELECT opens, closes FROM opening_hours") == [(opens, closes)]


def test_failed_export_leaves_no_partial_file(db_path, monkeypatch):
    from sportnav_data import export

    def boom(conn, venues):
        raise RuntimeError("boom")

    monkeypatch.setattr(export, "_write", boom)
    with pytest.raises(RuntimeError):
        export_venues([enriched(1)], db_path)
    assert not Path(db_path).exists()


def test_empty_strings_become_null(db_path):
    export_venues([enriched(1, street="", city=None, phone="  ", website="")], db_path)
    assert rows(db_path, "SELECT street, city, phone, website FROM venues") == [(None, None, None, None)]


# --- test fixture DB for the iOS tests --------------------------------------------------------------------------


def dump(path) -> list[str]:
    conn = sqlite3.connect(str(path))
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def test_committed_fixture_db_is_reproducible_from_the_script(tmp_path):
    assert DEFAULT_OUTPUT.is_file(), "run: cd backend && python scripts/make_test_fixture.py"
    regenerated = build_fixture(tmp_path / "test_venues.sqlite")
    assert dump(regenerated) == dump(DEFAULT_OUTPUT)


def test_fixture_db_contents():
    path = str(DEFAULT_OUTPUT)
    assert 5 <= len(FIXTURE_VENUES) <= 10
    assert rows(path, "SELECT COUNT(*) FROM venues") == [(len(FIXTURE_VENUES),)]
    assert rows(path, "SELECT COUNT(*) FROM categories") == [(7,)]
    # at least one gps_pending venue (NULL lat / lon) and several with GPS
    assert rows(path, "SELECT COUNT(*) FROM venues WHERE gps_pending = 1 AND lat IS NULL AND lon IS NULL") == [(1,)]
    assert rows(path, "SELECT COUNT(*) FROM venues WHERE gps_pending = 0 AND lat IS NOT NULL") [0][0] >= 5
    # venues with opening hours, one closing after midnight
    assert rows(path, "SELECT COUNT(DISTINCT venue_id) FROM opening_hours")[0][0] >= 3
    assert rows(path, "SELECT COUNT(*) FROM opening_hours WHERE closes < opens")[0][0] >= 1
    # every one of the 7 categories is used by at least one venue
    assert rows(path, "SELECT COUNT(DISTINCT category_id) FROM venue_categories") == [(7,)]
    # a venue with several categories and a venue saved without any category (unknown category scenario)
    assert rows(path, "SELECT COUNT(*) FROM (SELECT venue_id FROM venue_categories GROUP BY venue_id HAVING COUNT(*) > 1)")[0][0] >= 1
    assert rows(path, "SELECT COUNT(*) FROM venues WHERE id NOT IN (SELECT venue_id FROM venue_categories)")[0][0] >= 1
    # a gps_pending venue that has a category and a venue without hours
    assert rows(
        path, "SELECT COUNT(*) FROM venues v JOIN venue_categories vc ON vc.venue_id = v.id WHERE v.gps_pending = 1"
    )[0][0] >= 1
    assert rows(path, "SELECT COUNT(*) FROM venues WHERE id NOT IN (SELECT venue_id FROM opening_hours)")[0][0] >= 1
    # gps_pending <=> lat IS NULL
    assert rows(path, "SELECT COUNT(*) FROM venues WHERE (gps_pending = 1) <> (lat IS NULL)") == [(0,)]


# --- build_db CLI ----------------------------------------------------------------------------------------------------

EMAIL = "secret.person@example.com"


@pytest.fixture(autouse=True)
def fast_requests(monkeypatch):
    """The real default is 1 request per second (Nominatim usage policy); tests do not wait."""
    monkeypatch.setattr(build_db, "MIN_REQUEST_INTERVAL", 0.0)


def nominatim_response(name: str) -> httpx.Response:
    return httpx.Response(200, content=(FIXTURES / name).read_text(encoding="utf-8"))


def venues_handler(calls: list[httpx.Request]):
    """Nominatim knows 'Legion Gym' as POI, 'Address Gym' only by address; 'Nowhere' nowhere."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        q = request.url.params["q"]
        if q.startswith("Legion Gym"):
            return nominatim_response("nominatim_poi.json")
        if q == "A 1, B":  # address query of 'Address Gym'
            return nominatim_response("nominatim_address.json")
        return nominatim_response("nominatim_empty.json")

    return handler


def make_client(calls: list[httpx.Request]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(venues_handler(calls)))


RAW_VENUES = [
    {"id": 1, "title": "Legion Gym", "categories": ["Posilovny a silové tréninky"], "street": "Husova 100", "city": "Jaroměř"},
    {"id": 2, "title": "Address Gym", "categories": ["Lezecké stěny", "Bowling"], "street": "A 1", "city": "B"},
    {"id": 3, "title": "Nowhere", "categories": ["Wellness a relax"], "street": "C 2", "city": "D"},
    {"id": 4, "title": "Nowhere 2", "categories": ["Bowling"], "street": "E 3", "city": "F"},
]


def write_input(tmp_path) -> Path:
    path = tmp_path / "venues_raw.json"
    path.write_text(json.dumps(RAW_VENUES), encoding="utf-8")
    return path


def run_build(tmp_path, out, email=None) -> tuple[dict, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    async def go() -> dict:
        async with make_client(calls) as client:
            return await build_db.build(write_input(tmp_path), out, email, client=client, min_interval=0.0)

    return asyncio.run(go()), calls


def test_build_enriches_exports_and_reports_statistics(tmp_path):
    out = tmp_path / "venues.sqlite"
    stats, calls = run_build(tmp_path, out)

    assert stats["total"] == 4
    assert stats["gps_pending"] == 2
    assert stats["gps_pending_share"] == 0.5
    assert stats["per_source"] == {"nominatim_poi": 1, "nominatim_address": 1}
    assert stats["uncategorized"] == 1  # "Nowhere 2" has only an unknown category
    assert dict(stats["per_category"])["lezecke-steny-4"] == 1

    assert rows(str(out), "SELECT id, gps_source, gps_pending, lat IS NULL FROM venues ORDER BY id") == [
        (1, "nominatim_poi", 0, 0),
        (2, "nominatim_address", 0, 0),
        (3, None, 1, 1),
        (4, None, 1, 1),
    ]
    # OSM opening hours of the POI result survive into the database; the address result has none
    assert rows(str(out), "SELECT COUNT(*) FROM opening_hours WHERE venue_id = 1") == [(7,)]
    assert rows(str(out), "SELECT day, opens, closes FROM opening_hours WHERE venue_id = 1 ORDER BY rowid LIMIT 1") == [
        ("mon", "06:00", "22:00")
    ]
    assert rows(str(out), "SELECT COUNT(*) FROM opening_hours WHERE venue_id <> 1") == [(0,)]
    # 1 POI request for venue 1, POI + address for each of the others
    assert len(calls) == 1 + 2 + 2 + 2


def test_build_sends_email_only_when_given(tmp_path):
    _, calls = run_build(tmp_path, tmp_path / "a.sqlite")
    assert calls and all("email" not in r.url.params for r in calls)
    _, calls = run_build(tmp_path, tmp_path / "b.sqlite", email=EMAIL)
    assert calls and all(r.url.params["email"] == EMAIL for r in calls)


def run_main(tmp_path, monkeypatch, handler, out, *, input_path=None, env_email=None):
    """Run `build_db.main` against a MockTransport handler; returns (exit code, requests made)."""
    calls: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(recording))
    monkeypatch.setattr(build_db.httpx, "AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(build_db, "BACKEND_DIR", tmp_path)  # no real .env is read
    monkeypatch.delenv("NOMINATIM_EMAIL", raising=False)
    if env_email:
        monkeypatch.setenv("NOMINATIM_EMAIL", env_email)
    code = build_db.main(["--input", str(input_path or write_input(tmp_path)), "--output", str(out)])
    return code, calls


def test_main_runs_without_any_environment_variable(tmp_path, monkeypatch, capsys, caplog):
    monkeypatch.delenv("NOMINATIM_EMAIL", raising=False)
    out = tmp_path / "venues.sqlite"
    with caplog.at_level(logging.DEBUG):
        code, calls = run_main(tmp_path, monkeypatch, venues_handler([]), out)
    captured = capsys.readouterr()

    assert code == 0
    assert out.exists()
    assert calls and all("email" not in r.url.params for r in calls)
    assert "Records written: 4" in captured.out
    assert "gps_pending: 2 (50.0 %)" in captured.out
    assert "nominatim_poi: 1" in captured.out
    assert "nominatim_address: 1" in captured.out
    assert "above 10 %" in captured.out  # share warning of section 12
    assert "lezecke-steny-4: 1" in captured.out
    assert "Venues without any known category: 1" in captured.out
    assert "Bowling" in caplog.text  # unknown categories are logged


def test_main_uses_email_from_dotenv_and_never_prints_it(tmp_path, monkeypatch, capsys, caplog):
    (tmp_path / ".env").write_text(f"# contact\nNOMINATIM_EMAIL={EMAIL}\n", encoding="utf-8")
    # setenv then delenv registers an undo, so monkeypatch removes whatever load_dotenv writes into
    # os.environ even when `main` raises (delenv alone on an unset variable would register nothing).
    monkeypatch.setenv("NOMINATIM_EMAIL", "placeholder")
    monkeypatch.delenv("NOMINATIM_EMAIL")
    calls: list[httpx.Request] = []
    client = make_client(calls)
    monkeypatch.setattr(build_db.httpx, "AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(build_db, "BACKEND_DIR", tmp_path)
    out = tmp_path / "venues.sqlite"
    with caplog.at_level(logging.DEBUG):
        code = build_db.main(["--input", str(write_input(tmp_path)), "--output", str(out)])
    captured = capsys.readouterr()

    assert code == 0
    assert calls and all(r.url.params["email"] == EMAIL for r in calls)
    assert EMAIL not in captured.out + captured.err + caplog.text


def test_dotenv_email_does_not_leak_into_the_next_test():
    # Runs right after the .env test above: its load_dotenv must have been undone by monkeypatch.
    assert os.environ.get("NOMINATIM_EMAIL") != EMAIL


def test_main_uses_email_from_environment_and_never_prints_it(tmp_path, monkeypatch, capsys, caplog):
    out = tmp_path / "venues.sqlite"
    with caplog.at_level(logging.DEBUG):
        code, calls = run_main(tmp_path, monkeypatch, venues_handler([]), out, env_email=EMAIL)
    captured = capsys.readouterr()
    assert code == 0
    assert calls and all(r.url.params["email"] == EMAIL for r in calls)
    assert EMAIL not in captured.out + captured.err + caplog.text


def test_main_blocked_by_nominatim_exits_1_without_database(tmp_path, monkeypatch, capsys, caplog):
    out = tmp_path / "venues.sqlite"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["q"].startswith("Address Gym"):
            return httpx.Response(403)
        return nominatim_response("nominatim_empty.json")

    with caplog.at_level(logging.DEBUG):
        code, calls = run_main(tmp_path, monkeypatch, handler, out, env_email=EMAIL)
    captured = capsys.readouterr()

    assert code == 1
    assert "ERROR" in captured.err and "blocked" in captured.err and "Traceback" not in captured.err
    assert not out.exists()
    # venue 1 (POI + address), then the POI query of venue 2 got 403 -> nothing more is sent
    assert [r.url.params["q"] for r in calls] == [
        "Legion Gym, Husova 100, Jaroměř",
        "Husova 100, Jaroměř",
        "Address Gym, A 1, B",
    ]
    assert EMAIL not in captured.out + captured.err + caplog.text


def test_main_blocked_keeps_an_existing_output_untouched(tmp_path, monkeypatch, capsys):
    out = tmp_path / "venues.sqlite"
    out.write_bytes(b"previous database")
    code, _ = run_main(tmp_path, monkeypatch, lambda request: httpx.Response(403), out)
    capsys.readouterr()
    assert code == 1
    assert out.read_bytes() == b"previous database"


def test_main_reports_bad_input_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_db, "BACKEND_DIR", tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text('{"not": "an array"}', encoding="utf-8")
    code = build_db.main(["--input", str(bad), "--output", str(tmp_path / "o.sqlite")])
    assert code == 1
    assert "JSON array" in capsys.readouterr().err
    missing = build_db.main(["--input", str(tmp_path / "missing.json"), "--output", str(tmp_path / "o.sqlite")])
    assert missing == 1


# --- output location is checked before any network call -------------------------------------------------------


def never_called(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"network call made: {request.url.path}")


def test_main_unwritable_output_fails_fast_before_any_network_call(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    for out in (blocker / "venues.sqlite", tmp_path):  # parent is a file / the output is a directory
        code, calls = run_main(tmp_path, monkeypatch, never_called, out)
        captured = capsys.readouterr()
        assert code == 1
        assert calls == []
        assert "ERROR" in captured.err and "not writable" in captured.err
        assert "Traceback" not in captured.err
    assert blocker.read_text(encoding="utf-8") == "a file, not a directory"


def test_main_read_only_existing_output_fails_fast_and_is_left_untouched(tmp_path, monkeypatch, capsys):
    out = tmp_path / "venues.sqlite"
    out.write_bytes(b"previous database")
    out.chmod(0o444)
    try:
        if os.access(out, os.W_OK):
            pytest.skip("cannot make a file read-only for this user")
        code, calls = run_main(tmp_path, monkeypatch, never_called, out)
        captured = capsys.readouterr()
        assert code == 1
        assert calls == []
        assert "not writable" in captured.err and "Traceback" not in captured.err
    finally:
        out.chmod(0o666)
    assert out.read_bytes() == b"previous database"


def test_check_output_writable_keeps_existing_file_and_creates_parent_dir(tmp_path):
    out = tmp_path / "new" / "dir" / "venues.sqlite"
    build_db.check_output_writable(out)
    assert out.parent.is_dir() and not out.exists() and list(out.parent.iterdir()) == []  # no probe file left
    out.write_bytes(b"previous database")
    build_db.check_output_writable(out)
    assert out.read_bytes() == b"previous database"


def test_main_oserror_during_final_export_is_a_clean_error_exit(tmp_path, monkeypatch, capsys, caplog):
    def locked(venues, path):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(build_db, "export_venues", locked)
    out = tmp_path / "venues.sqlite"
    with caplog.at_level(logging.DEBUG):
        code, made = run_main(tmp_path, monkeypatch, venues_handler([]), out, env_email=EMAIL)
    captured = capsys.readouterr()
    assert code == 1
    assert made  # enrichment did run; only the write failed
    assert "ERROR: Cannot write output file" in captured.err and "PermissionError" in captured.err
    assert "Traceback" not in captured.err
    assert EMAIL not in captured.out + captured.err + caplog.text


def test_load_dotenv_does_not_override_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nNOMINATIM_EMAIL=from-file\nOTHER=\nEXTRA_X=1\n", encoding="utf-8")
    monkeypatch.setenv("NOMINATIM_EMAIL", "from-env")
    monkeypatch.delenv("OTHER", raising=False)
    monkeypatch.delenv("EXTRA_X", raising=False)
    build_db.load_dotenv(env_file)
    assert os.environ["NOMINATIM_EMAIL"] == "from-env"
    assert "OTHER" not in os.environ
    monkeypatch.delenv("EXTRA_X", raising=False)
