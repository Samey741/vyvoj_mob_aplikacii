import asyncio
import copy
import json
import logging
import time
from pathlib import Path

import httpx
import pytest

from sportnav_data.enrich import (
    NominatimBlockedError,
    enrich_all,
    enrich_venue,
    nominatim_search,
)

FIXTURES = Path(__file__).parent / "fixtures"
EMAIL = "secret.person@example.com"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_response(name: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=fixture_text(name), headers={"content-type": "application/json"})


POI = fixture_response  # readability alias for call sites below

VENUE = {
    "id": 193,
    "title": "Legion Gym",
    "categories": ["Posilovny a silové tréninky"],
    "street": "Husova 100",
    "city": "Jaroměř",
}

POI_Q = "Legion Gym, Husova 100, Jaroměř"
ADDRESS_Q = "Husova 100, Jaroměř"


def run(coro):
    return asyncio.run(coro)


class Recorder:
    """MockTransport handler that records requests and answers by query via `answers`."""

    def __init__(self, answers):
        self.answers = answers  # callable(request) -> httpx.Response | exception to raise
        self.requests: list[httpx.Request] = []
        self.starts: list[float] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.starts.append(time.perf_counter())
        answer = self.answers(request)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    @property
    def queries(self) -> list[str]:
        return [r.url.params["q"] for r in self.requests]


def by_query(mapping: dict[str, httpx.Response | Exception], default=None):
    def answers(request: httpx.Request):
        q = request.url.params["q"]
        if q in mapping:
            return mapping[q]
        return default if default is not None else fixture_response("nominatim_empty.json")

    return answers


def enrich_one(recorder: Recorder, venue=None, email=None, min_interval=0.0) -> dict:
    async def go():
        async with recorder.client() as client:
            return await enrich_venue(venue or VENUE, client, email, min_interval)

    return run(go())


def enrich_many(recorder: Recorder, venues, email=None, min_interval=0.0) -> list[dict]:
    async def go():
        async with recorder.client() as client:
            return await enrich_all(venues, client, email, min_interval)

    return run(go())


# --- phase 1: POI ------------------------------------------------------------------------------------------


def test_poi_result_gives_gps_hours_and_source():
    rec = Recorder(by_query({POI_Q: POI("nominatim_poi.json")}))
    result = enrich_one(rec)

    assert rec.queries == [POI_Q]  # no address query needed
    assert result["gps_source"] == "nominatim_poi"
    assert result["gps_pending"] == 0
    assert result["lat"] == 50.3561 and isinstance(result["lat"], float)
    assert result["lon"] == 15.9187 and isinstance(result["lon"], float)
    assert result["opening_hours"] == [
        ("mon", "06:00", "22:00"),
        ("tue", "06:00", "22:00"),
        ("wed", "06:00", "22:00"),
        ("thu", "06:00", "22:00"),
        ("fri", "06:00", "22:00"),
        ("sat", "08:00", "20:00"),
        ("sun", "08:00", "20:00"),
    ]
    assert result["title"] == "Legion Gym"  # original keys survive


def test_poi_without_opening_hours_tag_gives_empty_hours():
    body = json.dumps([{"lat": "50.0", "lon": "15.0", "extratags": {"website": "x"}}])
    rec = Recorder(lambda r: httpx.Response(200, content=body))
    result = enrich_one(rec)
    assert (result["gps_source"], result["opening_hours"]) == ("nominatim_poi", [])

    body = json.dumps([{"lat": "50.0", "lon": "15.0"}])  # no extratags at all
    result = enrich_one(Recorder(lambda r: httpx.Response(200, content=body)))
    assert (result["gps_source"], result["opening_hours"]) == ("nominatim_poi", [])


def test_poi_with_unsupported_hours_syntax_keeps_gps_and_empty_hours():
    body = json.dumps([{"lat": "50.0", "lon": "15.0", "extratags": {"opening_hours": "Mo-Fr 08:00-17:00; PH off"}}])
    result = enrich_one(Recorder(lambda r: httpx.Response(200, content=body)))
    assert result["gps_source"] == "nominatim_poi" and result["opening_hours"] == []


# --- phase 2: address ----------------------------------------------------------------------------------------


def test_address_fallback_gives_gps_but_never_opening_hours():
    # the address result carries extratags.opening_hours, which must be ignored
    assert "opening_hours" in fixture_text("nominatim_address.json")
    rec = Recorder(by_query({ADDRESS_Q: POI("nominatim_address.json")}))
    result = enrich_one(rec)

    assert rec.queries == [POI_Q, ADDRESS_Q]
    assert result["gps_source"] == "nominatim_address"
    assert result["gps_pending"] == 0
    assert (result["lat"], result["lon"]) == (50.3570, 15.9190)
    assert result["opening_hours"] == []


def test_both_phases_empty_gives_gps_pending():
    rec = Recorder(by_query({}))
    result = enrich_one(rec)

    assert rec.queries == [POI_Q, ADDRESS_Q]
    assert result["gps_pending"] == 1
    assert result["lat"] is None and result["lon"] is None
    assert result["gps_source"] is None
    assert result["opening_hours"] == []


def test_venue_without_street_and_city_skips_the_address_query():
    rec = Recorder(by_query({}))
    result = enrich_one(rec, {"id": 1, "title": "Lonely Gym", "street": None, "city": ""})
    assert rec.queries == ["Lonely Gym"]
    assert result["gps_pending"] == 1


@pytest.mark.parametrize(
    "venue, poi_q, address_q",
    [
        ({"title": "T", "street": None, "city": "Praha"}, "T, Praha", "Praha"),
        ({"title": "T", "street": "Ulica 1", "city": None}, "T, Ulica 1", "Ulica 1"),
        ({"title": "T", "street": "  ", "city": "Praha"}, "T, Praha", "Praha"),
    ],
)
def test_empty_query_parts_are_omitted(venue, poi_q, address_q):
    rec = Recorder(by_query({}))
    enrich_one(rec, venue)
    assert rec.queries == [poi_q, address_q]


# --- request shape ----------------------------------------------------------------------------------------------


def test_request_parameters_and_user_agent():
    rec = Recorder(by_query({}))
    enrich_one(rec)

    for request in rec.requests:
        assert request.method == "GET"
        assert (request.url.scheme, request.url.host, request.url.path) == ("https", "nominatim.openstreetmap.org", "/search")
        params = request.url.params
        assert params["format"] == "jsonv2"
        assert params["limit"] == "1"
        assert params["extratags"] == "1"
        assert params["countrycodes"] == "cz,sk"
        assert params["accept-language"] == "cs"
        assert request.headers["User-Agent"] == "SportNav-data-import/1.0"
        assert "email" not in params
    assert rec.queries == [POI_Q, ADDRESS_Q]


def test_email_is_sent_only_when_given():
    rec = Recorder(by_query({}))
    enrich_one(rec, email=EMAIL)
    assert all(r.url.params["email"] == EMAIL for r in rec.requests)

    rec = Recorder(by_query({}))
    enrich_one(rec, email="")
    assert all("email" not in r.url.params for r in rec.requests)


def test_nominatim_search_returns_first_result_or_none():
    async def go(name):
        rec = Recorder(lambda r: fixture_response(name))
        async with rec.client() as client:
            return await nominatim_search("anything", client)

    hit = run(go("nominatim_poi.json"))
    assert hit["lat"] == "50.3561" and hit["extratags"]["opening_hours"].startswith("Mo-Fr")
    assert run(go("nominatim_empty.json")) is None


# --- errors for one venue (8.9) -------------------------------------------------------------------------------------


def failing_answers():
    return {
        "429": httpx.Response(429, text="slow down"),
        "500": httpx.Response(500),
        "503": httpx.Response(503),
        "404": httpx.Response(404),
        "timeout": httpx.ReadTimeout("timed out"),
        "connect": httpx.ConnectError("boom"),
        "invalid url": httpx.InvalidURL("bad url"),  # not derived from httpx.HTTPError
        "stream error": httpx.StreamError("stream"),  # not derived from httpx.HTTPError
        "invalid json": httpx.Response(200, content="<html>not json</html>"),
        "not an array": fixture_response("nominatim_not_array.json"),
        "json null": httpx.Response(200, content="null"),
    }


@pytest.mark.parametrize("case", list(failing_answers()))
def test_poi_failure_marks_pending_without_address_query(case):
    rec = Recorder(lambda r: failing_answers()[case])
    result = enrich_one(rec)
    assert len(rec.requests) == 1  # no second phase
    assert result["gps_pending"] == 1 and result["lat"] is None and result["gps_source"] is None


@pytest.mark.parametrize("case", list(failing_answers()))
def test_address_phase_failure_marks_pending(case):
    rec = Recorder(by_query({ADDRESS_Q: failing_answers()[case]}))
    result = enrich_one(rec)
    assert rec.queries == [POI_Q, ADDRESS_Q]
    assert result["gps_pending"] == 1


def test_run_continues_after_a_failing_venue():
    venues = [
        {"id": 1, "title": "A", "street": "S1", "city": "C1"},
        {"id": 2, "title": "B", "street": "S2", "city": "C2"},
        {"id": 3, "title": "C", "street": "S3", "city": "C3"},
    ]
    rec = Recorder(
        by_query({"A, S1, C1": httpx.Response(429), "C, S3, C3": POI("nominatim_poi.json")}, default=POI("nominatim_empty.json"))
    )
    results = enrich_many(rec, venues)
    assert [r["id"] for r in results] == [1, 2, 3]
    assert [r["gps_pending"] for r in results] == [1, 1, 0]
    # venue 1: one request (failed); venue 2: both phases; venue 3: POI hit
    assert rec.queries == ["A, S1, C1", "B, S2, C2", "S2, C2", "C, S3, C3"]


def test_invalid_coordinates_count_as_an_empty_phase_result():
    # POI result with broken coordinates -> address query is tried
    rec = Recorder(by_query({POI_Q: POI("nominatim_invalid_coords.json"), ADDRESS_Q: POI("nominatim_address.json")}))
    result = enrich_one(rec)
    assert rec.queries == [POI_Q, ADDRESS_Q]
    assert result["gps_source"] == "nominatim_address"

    # both phases broken -> pending
    rec = Recorder(lambda r: POI("nominatim_invalid_coords.json"))
    assert enrich_one(rec)["gps_pending"] == 1


@pytest.mark.parametrize(
    "item",
    [
        {"lon": "15.0"},
        {"lat": "50.0"},
        {"lat": None, "lon": "15"},
        {"lat": "north", "lon": "15"},
        {"lat": "91", "lon": "15"},
        {"lat": "-91", "lon": "15"},
        {"lat": "50", "lon": "181"},
        {"lat": "50", "lon": "-180.5"},
        {"lat": "nan", "lon": "15"},
        {"lat": "50", "lon": "inf"},
        {"lat": True, "lon": 15},
        {"lat": [50], "lon": "15"},
        "not an object",
    ],
)
def test_unusable_coordinates_are_an_empty_result(item):
    body = json.dumps([item])
    rec = Recorder(lambda r: httpx.Response(200, content=body))
    result = enrich_one(rec)
    assert len(rec.requests) == 2  # POI, then address
    assert result["gps_pending"] == 1


def test_boundary_and_numeric_coordinates_are_accepted():
    body = json.dumps([{"lat": 90, "lon": "-180"}])
    result = enrich_one(Recorder(lambda r: httpx.Response(200, content=body)))
    assert (result["lat"], result["lon"], result["gps_pending"]) == (90.0, -180.0, 0)


# --- 403 aborts the run ----------------------------------------------------------------------------------------------------


def test_403_raises_blocked_error_and_sends_no_further_requests():
    venues = [{"id": i, "title": f"V{i}", "street": "S", "city": "C"} for i in range(1, 5)]

    def answers(request):
        return httpx.Response(403) if request.url.params["q"].startswith("V2") else fixture_response("nominatim_poi.json")

    rec = Recorder(answers)
    with pytest.raises(NominatimBlockedError):
        enrich_many(rec, venues)
    assert rec.queries == ["V1, S, C", "V2, S, C"]


def test_403_in_the_address_phase_also_aborts():
    rec = Recorder(by_query({ADDRESS_Q: httpx.Response(403)}))
    with pytest.raises(NominatimBlockedError):
        enrich_one(rec)
    assert rec.queries == [POI_Q, ADDRESS_Q]


def test_403_from_nominatim_search_directly():
    async def go():
        async with Recorder(lambda r: httpx.Response(403)).client() as client:
            await nominatim_search("x", client)

    with pytest.raises(NominatimBlockedError):
        run(go())


# --- enrich_all: order, sequence, spacing -----------------------------------------------------------------------------------


def test_enrich_all_preserves_input_order_and_returns_enriched_copies():
    venues = [{"id": i, "title": f"V{i}", "street": "S", "city": "C"} for i in range(1, 8)]
    # even ids found, odd ids not found
    rec = Recorder(
        lambda r: fixture_response("nominatim_poi.json")
        if int(r.url.params["q"][1]) % 2 == 0 and r.url.params["q"].startswith("V")
        else fixture_response("nominatim_empty.json")
    )
    results = enrich_many(rec, venues)
    assert [r["id"] for r in results] == [1, 2, 3, 4, 5, 6, 7]
    assert [r["gps_pending"] for r in results] == [1, 0, 1, 0, 1, 0, 1]
    assert enrich_many(Recorder(by_query({})), []) == []


def test_requests_are_never_concurrent():
    venues = [{"id": i, "title": f"V{i}", "street": "S", "city": "C"} for i in range(6)]
    in_flight = 0
    max_in_flight = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return fixture_response("nominatim_empty.json")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await enrich_all(venues, client, None, 0.0)

    results = run(go())
    assert max_in_flight == 1
    assert len(results) == 6


def test_min_interval_between_request_starts_including_phases_of_one_venue():
    venues = [{"id": i, "title": f"V{i}", "street": "S", "city": "C"} for i in range(3)]
    rec = Recorder(lambda r: fixture_response("nominatim_empty.json"))  # 2 requests per venue
    min_interval = 0.05
    enrich_many(rec, venues, min_interval=min_interval)

    assert len(rec.starts) == 6
    gaps = [b - a for a, b in zip(rec.starts, rec.starts[1:])]
    # small tolerance for clock granularity between the throttle and this measurement
    assert all(gap >= min_interval - 0.005 for gap in gaps), gaps


def test_default_min_interval_is_one_second():
    import inspect

    assert inspect.signature(enrich_all).parameters["min_interval"].default == 1.0
    assert inspect.signature(enrich_venue).parameters["min_interval"].default == 1.0


def test_enrich_venue_spaces_its_own_two_requests():
    rec = Recorder(lambda r: fixture_response("nominatim_empty.json"))
    enrich_one(rec, min_interval=0.05)
    assert rec.starts[1] - rec.starts[0] >= 0.045


# --- input untouched ---------------------------------------------------------------------------------------------------------------


def test_input_record_is_not_modified():
    venue = copy.deepcopy(VENUE)
    venue["categories"] = ["Posilovny a silové tréninky"]
    snapshot = copy.deepcopy(venue)

    for answers in (by_query({POI_Q: POI("nominatim_poi.json")}), by_query({})):
        result = enrich_one(Recorder(answers), venue)
        assert venue == snapshot and "lat" not in venue and "gps_pending" not in venue
        assert result is not venue

    venues = [venue]
    enrich_many(Recorder(by_query({})), venues)
    assert venues == [snapshot]


# --- no e-mail in logs -----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["429", "timeout", "invalid json", "not an array"])
def test_failures_are_logged_without_url_or_email(caplog, case):
    def answers(request):
        answer = failing_answers()[case]
        if isinstance(answer, Exception):
            return type(answer)("failed", request=request)  # httpx errors embed the request
        return answer

    rec = Recorder(answers)
    with caplog.at_level(logging.DEBUG):
        enrich_one(rec, email=EMAIL)
    ours = [r.getMessage() for r in caplog.records if r.name == "sportnav_data.enrich"]
    assert ours  # the failure was logged
    assert EMAIL not in caplog.text
    assert all("nominatim.openstreetmap.org" not in message and "://" not in message for message in ours)


def test_httpx_request_log_is_redacted(caplog):
    rec = Recorder(by_query({}))
    with caplog.at_level(logging.INFO, logger="httpx"):
        enrich_one(rec, email=EMAIL)
    assert any("HTTP Request" in r.getMessage() for r in caplog.records)
    assert EMAIL not in caplog.text
