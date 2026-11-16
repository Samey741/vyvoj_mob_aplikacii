import asyncio
import inspect
import json
import logging
from pathlib import Path

import httpx
import pytest

from sportnav_data import enrich
from sportnav_data.enrich import (
    AppleAuthError,
    enrich_all,
    enrich_venue,
    enrich_venue_apple,
    enrich_venue_google_fallback,
    get_apple_access_token,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def venue(id_: int = 193, title: str = "Legion Gym") -> dict:
    return {"id": id_, "title": title, "street": "Husova 100", "city": "Jaroměř"}


class Recorder:
    """MockTransport handler: routes by URL, records requests, never touches the network."""

    def __init__(self, apple=None, google=None, token=None):
        self.apple = apple  # callable(request) -> httpx.Response, or a fixture dict
        self.google = google
        self.token = token
        self.requests: list[httpx.Request] = []

    def _respond(self, spec, request):
        if callable(spec):
            return spec(request)
        return httpx.Response(200, json=spec if spec is not None else {})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "maps-api.apple.com" and path == "/v1/token":
            return self._respond(self.token, request)
        if host == "maps-api.apple.com" and path == "/v1/search":
            return self._respond(self.apple, request)
        if host == "maps.googleapis.com":
            return self._respond(self.google, request)
        raise AssertionError(f"unexpected URL {request.url}")

    def calls(self, host: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == host]


def run(coro_factory, handler):
    """Run `coro_factory(client)` with an AsyncClient backed by MockTransport."""

    async def main():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await coro_factory(client)

    return asyncio.run(main())


# --- get_apple_access_token -------------------------------------------------


def test_apple_token_exchange():
    rec = Recorder(token=fixture("apple_token.json"))
    token = run(lambda c: get_apple_access_token("jwt-auth", c), rec)
    assert token == "access-token-xyz"
    (req,) = rec.requests
    assert req.method == "GET"
    assert str(req.url) == "https://maps-api.apple.com/v1/token"
    assert req.headers["Authorization"] == "Bearer jwt-auth"


def test_apple_token_http_error_raises():
    rec = Recorder(token=lambda r: httpx.Response(401, json={"error": "bad"}))
    with pytest.raises(httpx.HTTPStatusError):
        run(lambda c: get_apple_access_token("jwt-auth", c), rec)


def test_apple_token_missing_access_token_raises():
    rec = Recorder(token={"expiresInSeconds": 1})
    with pytest.raises(ValueError):
        run(lambda c: get_apple_access_token("jwt-auth", c), rec)


@pytest.mark.parametrize("body", ["null", "[]", '"text"', "42"])
def test_apple_token_non_object_json_raises_value_error(body):
    rec = Recorder(token=lambda r: httpx.Response(200, text=body))
    with pytest.raises(ValueError):
        run(lambda c: get_apple_access_token("jwt-auth", c), rec)


# --- enrich_venue_apple -----------------------------------------------------


def test_apple_hit_sets_gps_and_normalized_hours():
    rec = Recorder(apple=fixture("apple_search_result.json"))
    v = venue()
    out = run(lambda c: enrich_venue_apple(v, "tok", c), rec)
    assert out["gps_source"] == "apple_maps"
    assert (out["lat"], out["lon"]) == (50.3361, 15.9217)
    assert out["opening_hours"] == [("mon", "06:00", "22:00"), ("tue", "06:00", "22:00")]
    assert "gps_source" not in v  # input not mutated
    (req,) = rec.requests
    assert req.headers["Authorization"] == "Bearer tok"
    assert req.url.params["q"] == "Legion Gym Husova 100 Jaroměř"
    assert req.url.params["resultTypeFilter"] == "Poi"
    assert req.url.params["lang"] == "sk-SK"


def test_apple_hit_center_shape_from_design_sketch():
    rec = Recorder(apple=fixture("apple_search_center_shape.json"))
    out = run(lambda c: enrich_venue_apple(venue(), "tok", c), rec)
    assert (out["lat"], out["lon"]) == (50.3361, 15.9217)
    assert out["gps_source"] == "apple_maps"
    assert out["opening_hours"] == []


def test_apple_empty_results_leaves_venue_without_gps():
    rec = Recorder(apple=fixture("apple_search_empty.json"))
    out = run(lambda c: enrich_venue_apple(venue(), "tok", c), rec)
    assert "gps_source" not in out
    assert "lat" not in out


@pytest.mark.parametrize("status", [401, 403])
def test_apple_auth_status_raises_apple_auth_error(status):
    rec = Recorder(apple=lambda r: httpx.Response(status, json={"error": "denied"}))
    with pytest.raises(AppleAuthError):
        run(lambda c: enrich_venue_apple(venue(), "tok", c), rec)


@pytest.mark.parametrize("status", [400, 404, 429, 500, 503])
def test_apple_other_http_errors_raise_http_error(status):
    rec = Recorder(apple=lambda r: httpx.Response(status, text="x"))
    with pytest.raises(httpx.HTTPStatusError):
        run(lambda c: enrich_venue_apple(venue(), "tok", c), rec)


@pytest.mark.parametrize("body", ["null", "[]", '"text"', "42", "not json", '{"results": "x"}'])
def test_apple_bad_body_raises_value_error(body):
    rec = Recorder(apple=lambda r: httpx.Response(200, text=body))
    with pytest.raises(ValueError):
        run(lambda c: enrich_venue_apple(venue(), "tok", c), rec)


def test_apple_hit_without_usable_coordinates_is_an_error_not_empty():
    rec = Recorder(apple={"results": [{"name": "No coords"}]})
    with pytest.raises(ValueError):
        run(lambda c: enrich_venue_apple(venue(), "tok", c), rec)


def test_apple_200_without_results_key_counts_as_empty():
    rec = Recorder(apple={})
    out = run(lambda c: enrich_venue_apple(venue(), "tok", c), rec)
    assert "lat" not in out


# --- enrich_venue_google_fallback -------------------------------------------


def test_google_fallback_gps_only_with_fields_geometry():
    rec = Recorder(google=fixture("google_find_place.json"))
    out = run(lambda c: enrich_venue_google_fallback(venue(), "gkey", c), rec)
    assert out["gps_source"] == "google_places_fallback"
    assert (out["lat"], out["lon"]) == (48.1486, 17.1077)
    assert "opening_hours" not in out
    (req,) = rec.requests
    assert req.url.params["fields"] == "geometry"
    assert req.url.params["key"] == "gkey"
    assert req.url.params["inputtype"] == "textquery"
    assert req.url.params["input"] == "Legion Gym Husova 100 Jaroměř"


@pytest.mark.parametrize("body", ["null", "[]", "not json"])
def test_google_non_object_or_invalid_json_raises_value_error(body):
    rec = Recorder(google=lambda r: httpx.Response(200, text=body))
    with pytest.raises(ValueError):
        run(lambda c: enrich_venue_google_fallback(venue(), "gkey", c), rec)


def test_google_zero_results_returns_venue_unchanged():
    rec = Recorder(google=fixture("google_zero_results.json"))
    out = run(lambda c: enrich_venue_google_fallback(venue(), "gkey", c), rec)
    assert out == venue()


# --- enrich_venue -----------------------------------------------------------


def test_enrich_venue_apple_result_skips_google():
    rec = Recorder(apple=fixture("apple_search_result.json"), google=fixture("google_find_place.json"))
    out = run(lambda c: enrich_venue(venue(), "tok", "gkey", c), rec)
    assert out["gps_source"] == "apple_maps"
    assert out["gps_pending"] == 0
    assert (out["lat"], out["lon"]) == (50.3361, 15.9217)
    # regression: _finalize must not re-normalize (and thereby erase) Apple's hours
    assert out["opening_hours"] == [("mon", "06:00", "22:00"), ("tue", "06:00", "22:00")]
    assert rec.calls("maps.googleapis.com") == []


def test_enrich_venue_apple_empty_falls_back_to_google():
    rec = Recorder(apple=fixture("apple_search_empty.json"), google=fixture("google_find_place.json"))
    out = run(lambda c: enrich_venue(venue(), "tok", "gkey", c), rec)
    assert out["gps_source"] == "google_places_fallback"
    assert (out["lat"], out["lon"]) == (48.1486, 17.1077)
    assert out["gps_pending"] == 0
    assert out["opening_hours"] == []  # Google fallback supplies GPS only
    assert len(rec.calls("maps.googleapis.com")) == 1


def test_enrich_venue_both_empty_is_gps_pending():
    rec = Recorder(apple=fixture("apple_search_empty.json"), google=fixture("google_zero_results.json"))
    out = run(lambda c: enrich_venue(venue(), "tok", "gkey", c), rec)
    assert out["gps_pending"] == 1
    assert out["lat"] is None and out["lon"] is None
    assert out["gps_source"] is None
    assert out["opening_hours"] == []
    assert out["title"] == "Legion Gym"  # original fields kept


def test_enrich_venue_missing_google_key_does_not_call_google():
    for key in (None, ""):
        rec = Recorder(apple=fixture("apple_search_empty.json"), google=fixture("google_find_place.json"))
        out = run(lambda c: enrich_venue(venue(), "tok", key, c), rec)
        assert rec.calls("maps.googleapis.com") == []
        assert out["gps_pending"] == 1
        assert out["lat"] is None and out["lon"] is None


@pytest.mark.parametrize("status", [400, 404, 429, 500, 503])
def test_enrich_venue_apple_http_error_is_pending_without_google(status):
    rec = Recorder(
        apple=lambda r: httpx.Response(status, text="down"), google=fixture("google_find_place.json")
    )
    out = run(lambda c: enrich_venue(venue(), "tok", "gkey", c), rec)
    assert out["gps_pending"] == 1
    assert out["lat"] is None and out["lon"] is None and out["gps_source"] is None
    assert out["opening_hours"] == []
    assert rec.calls("maps.googleapis.com") == []


@pytest.mark.parametrize("status", [401, 403])
def test_enrich_venue_apple_auth_error_propagates_without_google(status):
    rec = Recorder(apple=lambda r: httpx.Response(status), google=fixture("google_find_place.json"))
    with pytest.raises(AppleAuthError):
        run(lambda c: enrich_venue(venue(), "tok", "gkey", c), rec)
    assert rec.calls("maps.googleapis.com") == []


def test_enrich_venue_google_5xx_after_apple_empty_is_gps_pending():
    rec = Recorder(
        apple=fixture("apple_search_empty.json"), google=lambda r: httpx.Response(502, text="bad gateway")
    )
    out = run(lambda c: enrich_venue(venue(), "tok", "gkey", c), rec)
    assert out["gps_pending"] == 1
    assert out["lat"] is None
    assert len(rec.calls("maps.googleapis.com")) == 1


@pytest.mark.parametrize("body", ["null", "[]", '"x"'])
def test_enrich_venue_google_non_object_json_is_pending(body, caplog):
    rec = Recorder(apple=fixture("apple_search_empty.json"), google=lambda r: httpx.Response(200, text=body))
    with caplog.at_level(logging.WARNING):
        out = run(lambda c: enrich_venue(venue(), "tok", "gkey", c), rec)
    assert out["gps_pending"] == 1
    assert not [r for r in caplog.records if "Unexpected" in r.getMessage()]


@pytest.mark.parametrize("body", ["<html>not json</html>", "null", "[]", '"text"', '{"results": 5}'])
def test_enrich_venue_invalid_or_non_object_json_is_pending_without_google(body):
    rec = Recorder(
        apple=lambda r: httpx.Response(200, text=body), google=fixture("google_find_place.json")
    )
    out = run(lambda c: enrich_venue(venue(), "tok", "gkey", c), rec)
    assert out["gps_pending"] == 1
    assert out["lat"] is None
    assert rec.calls("maps.googleapis.com") == []


def test_enrich_venue_timeout_does_not_raise():
    def boom(request):
        raise httpx.ReadTimeout("timed out", request=request)

    rec = Recorder(apple=boom, google=fixture("google_find_place.json"))
    out = run(lambda c: enrich_venue(venue(), "tok", "gkey", c), rec)
    assert out["gps_pending"] == 1
    assert out["lat"] is None and out["lon"] is None
    assert rec.calls("maps.googleapis.com") == []


# --- enrich_all -------------------------------------------------------------


def test_enrich_all_one_failure_does_not_break_the_run_and_keeps_order():
    apple_ok = fixture("apple_search_result.json")

    def apple(request: httpx.Request) -> httpx.Response:
        if "Broken" in request.url.params["q"]:
            raise httpx.ConnectTimeout("timeout", request=request)
        if "Empty" in request.url.params["q"]:
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json=apple_ok)

    venues = [venue(1, "Good A"), venue(2, "Broken"), venue(3, "Empty"), venue(4, "Good B")]
    rec = Recorder(apple=apple, google=fixture("google_zero_results.json"))
    out = run(lambda c: enrich_all(venues, "tok", "gkey", c), rec)

    assert [v["id"] for v in out] == [1, 2, 3, 4]
    assert [v["gps_pending"] for v in out] == [0, 1, 1, 0]
    assert out[0]["gps_source"] == "apple_maps"
    hours = [("mon", "06:00", "22:00"), ("tue", "06:00", "22:00")]
    assert out[0]["opening_hours"] == hours and out[3]["opening_hours"] == hours
    assert out[1]["opening_hours"] == [] and out[2]["opening_hours"] == []
    assert len(rec.calls("maps.googleapis.com")) == 1  # only the Apple-empty venue, not the broken one
    assert out[1]["lat"] is None and out[2]["lat"] is None
    assert all(set(v) >= {"lat", "lon", "opening_hours", "gps_source", "gps_pending"} for v in out)


def test_enrich_all_unexpected_exception_is_contained(monkeypatch):
    original = enrich._enrich_venue

    async def flaky(v, token, key, client, gate=None):
        if v["id"] == 2:
            raise RuntimeError("boom")
        return await original(v, token, key, client, gate)

    monkeypatch.setattr(enrich, "_enrich_venue", flaky)
    rec = Recorder(apple=fixture("apple_search_result.json"))
    out = run(lambda c: enrich_all([venue(1), venue(2), venue(3)], "tok", None, c), rec)
    assert [v["gps_pending"] for v in out] == [0, 1, 0]


def test_enrich_all_empty_list():
    assert run(lambda c: enrich_all([], "tok", None, c), Recorder()) == []


@pytest.mark.parametrize("limit", [1, 3, 5])
def test_enrich_all_respects_concurrency_limit(limit):
    state = {"in_flight": 0, "max": 0}
    apple_ok = fixture("apple_search_result.json")

    async def handler(request: httpx.Request) -> httpx.Response:
        state["in_flight"] += 1
        state["max"] = max(state["max"], state["in_flight"])
        await asyncio.sleep(0.01)
        state["in_flight"] -= 1
        return httpx.Response(200, json=apple_ok)

    venues = [venue(i) for i in range(20)]
    out = run(lambda c: enrich_all(venues, "tok", None, c, concurrency=limit), handler)
    assert len(out) == 20
    assert all(v["gps_pending"] == 0 for v in out)
    assert state["max"] == limit  # saturated, but never exceeded


def test_enrich_all_default_concurrency_is_five():
    state = {"in_flight": 0, "max": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["in_flight"] += 1
        state["max"] = max(state["max"], state["in_flight"])
        await asyncio.sleep(0.01)
        state["in_flight"] -= 1
        return httpx.Response(200, json=fixture("apple_search_empty.json"))

    run(lambda c: enrich_all([venue(i) for i in range(20)], "tok", None, c), handler)
    assert state["max"] == 5


# --- enrich_all: Apple hours, errors, auth, Google cap (DESIGN.md 8.9) -------

HOURS = [("mon", "06:00", "22:00"), ("tue", "06:00", "22:00")]


def token_requests(rec: Recorder) -> list[httpx.Request]:
    return [r for r in rec.requests if r.url.path == "/v1/token"]


def test_enrich_all_apple_hours_survive():
    rec = Recorder(apple=fixture("apple_search_result.json"))
    out = run(lambda c: enrich_all([venue(1), venue(2)], "tok", None, c), rec)
    for v in out:
        assert v["gps_source"] == "apple_maps"
        assert v["opening_hours"] == HOURS


@pytest.mark.parametrize("status", [429, 500, 503])
def test_enrich_all_apple_http_error_for_one_venue_is_pending_without_google(status):
    def apple(request):
        if "Bad" in request.url.params["q"]:
            return httpx.Response(status)
        return httpx.Response(200, json=fixture("apple_search_result.json"))

    rec = Recorder(apple=apple, google=fixture("google_find_place.json"))
    venues = [venue(1, "Good"), venue(2, "Bad"), venue(3, "Good")]
    out = run(lambda c: enrich_all(venues, "tok", "gkey", c), rec)
    assert [v["gps_pending"] for v in out] == [0, 1, 0]
    assert rec.calls("maps.googleapis.com") == []


def test_enrich_all_auth_error_refreshes_token_once_and_retries():
    def apple(request):
        if request.headers["Authorization"] == "Bearer access-token-xyz":
            return httpx.Response(200, json=fixture("apple_search_result.json"))
        return httpx.Response(401)

    rec = Recorder(apple=apple, token=fixture("apple_token.json"), google=fixture("google_find_place.json"))
    venues = [venue(i) for i in range(8)]
    out = run(lambda c: enrich_all(venues, "stale", "gkey", c, apple_auth_token="jwt-auth"), rec)

    assert [v["id"] for v in out] == list(range(8))
    assert all(v["gps_source"] == "apple_maps" and v["gps_pending"] == 0 for v in out)
    assert all(v["opening_hours"] == HOURS for v in out)
    assert len(token_requests(rec)) == 1  # refreshed exactly once, even with concurrent 401s
    assert token_requests(rec)[0].headers["Authorization"] == "Bearer jwt-auth"
    assert rec.calls("maps.googleapis.com") == []


@pytest.mark.parametrize("status", [401, 403])
def test_enrich_all_auth_error_without_auth_token_aborts_without_google(status):
    rec = Recorder(apple=lambda r: httpx.Response(status), google=fixture("google_find_place.json"))
    venues = [venue(i) for i in range(10)]
    with pytest.raises(AppleAuthError):
        run(lambda c: enrich_all(venues, "tok", "gkey", c), rec)
    assert rec.calls("maps.googleapis.com") == []
    assert token_requests(rec) == []


def test_enrich_all_auth_error_persisting_after_refresh_aborts_without_google():
    rec = Recorder(
        apple=lambda r: httpx.Response(401),
        token=fixture("apple_token.json"),
        google=fixture("google_find_place.json"),
    )
    venues = [venue(i) for i in range(10)]
    with pytest.raises(AppleAuthError):
        run(lambda c: enrich_all(venues, "tok", "gkey", c, apple_auth_token="jwt-auth"), rec)
    assert len(token_requests(rec)) == 1
    assert rec.calls("maps.googleapis.com") == []


@pytest.mark.parametrize(
    "token_response",
    [lambda r: httpx.Response(500), lambda r: httpx.Response(200, text="null"), {"nope": 1}],
)
def test_enrich_all_failed_token_refresh_aborts_with_apple_auth_error(token_response):
    rec = Recorder(
        apple=lambda r: httpx.Response(401), token=token_response, google=fixture("google_find_place.json")
    )
    with pytest.raises(AppleAuthError):
        run(lambda c: enrich_all([venue(1), venue(2)], "tok", "gkey", c, apple_auth_token="jwt"), rec)
    assert rec.calls("maps.googleapis.com") == []


def test_enrich_all_auth_error_late_in_run_stops_google_for_remaining_venues():
    # the first venue is Apple-empty (Google legitimately used), then Apple starts answering 401
    def apple(request):
        if "Late" in request.url.params["q"]:
            return httpx.Response(401)
        return httpx.Response(200, json={"results": []})

    rec = Recorder(apple=apple, google=fixture("google_find_place.json"))
    venues = [venue(1, "Early"), venue(2, "Late")] + [venue(i, "Empty") for i in range(3, 20)]
    with pytest.raises(AppleAuthError):
        run(lambda c: enrich_all(venues, "tok", "gkey", c, concurrency=1), rec)
    assert len(rec.calls("maps.googleapis.com")) == 1  # only the venue before the failure


def test_enrich_all_google_cap_is_enforced_and_warned_once(caplog):
    rec = Recorder(apple=fixture("apple_search_empty.json"), google=fixture("google_find_place.json"))
    venues = [venue(i) for i in range(6)]
    with caplog.at_level(logging.WARNING, logger="sportnav_data.enrich"):
        out = run(lambda c: enrich_all(venues, "tok", "gkey", c, max_google_calls=2), rec)

    assert len(rec.calls("maps.googleapis.com")) == 2
    assert sorted(v["gps_pending"] for v in out) == [0, 0, 1, 1, 1, 1]
    assert [v["id"] for v in out] == list(range(6))
    for v in out:
        if v["gps_pending"]:
            assert v["lat"] is None and v["lon"] is None and v["gps_source"] is None
    cap_warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and "max_google_calls" in r.getMessage()
    ]
    assert len(cap_warnings) == 1


def test_enrich_all_google_cap_zero_makes_no_google_calls():
    rec = Recorder(apple=fixture("apple_search_empty.json"), google=fixture("google_find_place.json"))
    out = run(lambda c: enrich_all([venue(1), venue(2)], "tok", "gkey", c, max_google_calls=0), rec)
    assert rec.calls("maps.googleapis.com") == []
    assert [v["gps_pending"] for v in out] == [1, 1]


def test_enrich_all_google_cap_not_consumed_by_apple_hits():
    def apple(request):
        if "Empty" in request.url.params["q"]:
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json=fixture("apple_search_result.json"))

    rec = Recorder(apple=apple, google=fixture("google_find_place.json"))
    venues = [venue(i, "Hit") for i in range(5)] + [venue(10, "Empty")]
    out = run(lambda c: enrich_all(venues, "tok", "gkey", c, max_google_calls=1), rec)
    assert len(rec.calls("maps.googleapis.com")) == 1
    assert all(v["gps_pending"] == 0 for v in out)


def test_enrich_all_signature_defaults():
    params = inspect.signature(enrich_all).parameters
    assert params["max_google_calls"].default == 500
    assert params["apple_auth_token"].default is None
    assert params["concurrency"].default == 5


# --- secrets never leak into logs or exception messages ---------------------

GOOGLE_SECRET = "SECRET-GOOGLE-KEY-9f3a"
APPLE_AUTH_SECRET = "SECRET-APPLE-AUTH-7b1c"
APPLE_ACCESS_SECRET = "SECRET-APPLE-ACCESS-4d2e"
SECRETS = (GOOGLE_SECRET, APPLE_AUTH_SECRET, APPLE_ACCESS_SECRET)


def _leaky_transport_error(exc_type):
    """Handler raising a transport error whose message embeds the URL and headers (worst case)."""

    def handler(request):
        raise exc_type(f"boom {request.url} {dict(request.headers)}", request=request)

    return handler


def _exception_texts(exc):
    """str and repr of an exception and of its whole __cause__ / __context__ chain."""
    texts, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        texts += [str(exc), repr(exc)]
        exc = exc.__cause__ or exc.__context__
    return texts


def _log_texts(caplog):
    texts = [caplog.text]
    for r in caplog.records:
        texts += [r.getMessage(), str(r.msg), repr(r.args), r.exc_text or ""]
        if r.exc_info:
            texts += _exception_texts(r.exc_info[1])
    return texts


def assert_no_secrets(caplog, *exceptions):
    texts = _log_texts(caplog)
    for exc in exceptions:
        texts += _exception_texts(exc)
    for text in texts:
        for secret in SECRETS:
            assert secret not in text


def _apple_empty(request):
    return httpx.Response(200, json={"results": []})


@pytest.mark.parametrize("status", [400, 403, 404, 429, 500, 503])
def test_google_http_error_does_not_log_api_key(status, caplog):
    rec = Recorder(apple=_apple_empty, google=lambda r: httpx.Response(status))
    with caplog.at_level(logging.DEBUG):
        out = run(lambda c: enrich_venue(venue(7), "tok", GOOGLE_SECRET, c), rec)
    assert out["gps_pending"] == 1
    # the key really was sent (so the test would have caught the leak) ...
    assert rec.calls("maps.googleapis.com")[0].url.params["key"] == GOOGLE_SECRET
    # ... but logs stay useful: venue id, status code and exception type, without the URL
    (record,) = [r for r in caplog.records if "Google fallback failed" in r.getMessage()]
    assert "venue 7" in record.getMessage()
    assert f"HTTP {status}" in record.getMessage()
    assert "HTTPStatusError" in record.getMessage()
    assert_no_secrets(caplog)


def test_httpx_request_log_redacts_google_key_on_success_too(caplog):
    # httpx itself logs the full URL at INFO; enrich.py installs a filter that scrubs `key=`.
    rec = Recorder(apple=_apple_empty, google=fixture("google_find_place.json"))
    with caplog.at_level(logging.INFO):
        out = run(lambda c: enrich_venue(venue(7), "tok", GOOGLE_SECRET, c), rec)
    assert out["gps_source"] == "google_places_fallback"
    google_logs = [r.getMessage() for r in caplog.records if "googleapis.com" in r.getMessage()]
    assert google_logs and all("key=***" in m for m in google_logs)
    assert_no_secrets(caplog)


@pytest.mark.parametrize("exc_type", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError])
def test_google_transport_error_does_not_log_api_key(exc_type, caplog):
    rec = Recorder(apple=_apple_empty, google=_leaky_transport_error(exc_type))
    with caplog.at_level(logging.DEBUG):
        out = run(lambda c: enrich_venue(venue(7), "tok", GOOGLE_SECRET, c), rec)
    assert out["gps_pending"] == 1
    (record,) = [r for r in caplog.records if "Google fallback failed" in r.getMessage()]
    assert "venue 7" in record.getMessage()
    assert exc_type.__name__ in record.getMessage()
    assert_no_secrets(caplog)


def test_google_error_via_enrich_all_does_not_log_api_key(caplog):
    rec = Recorder(apple=_apple_empty, google=lambda r: httpx.Response(500))
    with caplog.at_level(logging.DEBUG):
        out = run(lambda c: enrich_all([venue(1), venue(2)], "tok", GOOGLE_SECRET, c), rec)
    assert [v["gps_pending"] for v in out] == [1, 1]
    assert len([r for r in caplog.records if "Google fallback failed" in r.getMessage()]) == 2
    assert_no_secrets(caplog)


@pytest.mark.parametrize("status", [429, 500, 502])
def test_apple_http_error_does_not_log_tokens(status, caplog):
    rec = Recorder(apple=lambda r: httpx.Response(status), google=fixture("google_find_place.json"))
    with caplog.at_level(logging.DEBUG):
        out = run(lambda c: enrich_venue(venue(5), APPLE_ACCESS_SECRET, GOOGLE_SECRET, c), rec)
    assert out["gps_pending"] == 1
    (record,) = [r for r in caplog.records if "Apple Maps failed" in r.getMessage()]
    assert "venue 5" in record.getMessage()
    assert f"HTTP {status}" in record.getMessage()
    assert_no_secrets(caplog)


@pytest.mark.parametrize("exc_type", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError])
def test_apple_transport_error_does_not_log_tokens(exc_type, caplog):
    rec = Recorder(apple=_leaky_transport_error(exc_type))
    with caplog.at_level(logging.DEBUG):
        out = run(lambda c: enrich_venue(venue(5), APPLE_ACCESS_SECRET, GOOGLE_SECRET, c), rec)
    assert out["gps_pending"] == 1
    (record,) = [r for r in caplog.records if "Apple Maps failed" in r.getMessage()]
    assert exc_type.__name__ in record.getMessage()
    assert_no_secrets(caplog)


def test_apple_invalid_json_does_not_log_tokens(caplog):
    rec = Recorder(apple=lambda r: httpx.Response(200, text=f"not json {APPLE_ACCESS_SECRET}"))
    with caplog.at_level(logging.DEBUG):
        out = run(lambda c: enrich_venue(venue(5), APPLE_ACCESS_SECRET, GOOGLE_SECRET, c), rec)
    assert out["gps_pending"] == 1
    assert_no_secrets(caplog)


@pytest.mark.parametrize("status", [401, 403])
def test_apple_auth_error_does_not_leak_tokens(status, caplog):
    rec = Recorder(apple=lambda r: httpx.Response(status), google=fixture("google_find_place.json"))
    with caplog.at_level(logging.DEBUG), pytest.raises(AppleAuthError) as info:
        run(lambda c: enrich_all([venue(1), venue(2)], APPLE_ACCESS_SECRET, GOOGLE_SECRET, c), rec)
    assert_no_secrets(caplog, info.value)


def test_apple_auth_error_persisting_after_refresh_does_not_leak_tokens(caplog):
    rec = Recorder(apple=lambda r: httpx.Response(401), token=fixture("apple_token.json"))
    with caplog.at_level(logging.DEBUG), pytest.raises(AppleAuthError) as info:
        run(
            lambda c: enrich_all(
                [venue(1), venue(2)], APPLE_ACCESS_SECRET, GOOGLE_SECRET, c, apple_auth_token=APPLE_AUTH_SECRET
            ),
            rec,
        )
    assert_no_secrets(caplog, info.value)


@pytest.mark.parametrize(
    "token_response",
    [
        lambda r: httpx.Response(401),
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(200, text=f"null {APPLE_AUTH_SECRET}"),
        {"nope": APPLE_AUTH_SECRET},
        _leaky_transport_error(httpx.ConnectTimeout),
        _leaky_transport_error(httpx.ConnectError),
    ],
)
def test_apple_token_exchange_error_does_not_leak_tokens(token_response, caplog):
    rec = Recorder(apple=lambda r: httpx.Response(401), token=token_response)
    with caplog.at_level(logging.DEBUG), pytest.raises(AppleAuthError) as info:
        run(
            lambda c: enrich_all(
                [venue(1), venue(2)], APPLE_ACCESS_SECRET, GOOGLE_SECRET, c, apple_auth_token=APPLE_AUTH_SECRET
            ),
            rec,
        )
    assert "token refresh failed" in str(info.value)
    assert_no_secrets(caplog, info.value)


@pytest.mark.parametrize("status", [401, 500])
def test_get_apple_access_token_errors_do_not_leak_tokens(status, caplog):
    rec = Recorder(token=lambda r: httpx.Response(status))
    with caplog.at_level(logging.DEBUG), pytest.raises(httpx.HTTPStatusError) as info:
        run(lambda c: get_apple_access_token(APPLE_AUTH_SECRET, c), rec)
    assert_no_secrets(caplog, info.value)


def test_unexpected_error_log_does_not_leak_secrets(monkeypatch, caplog):
    async def boom(v, token, key, client, gate=None):
        raise RuntimeError(f"url=...?key={key} Authorization: Bearer {token}")

    monkeypatch.setattr(enrich, "_enrich_venue", boom)
    with caplog.at_level(logging.DEBUG):
        out = run(lambda c: enrich_all([venue(3)], APPLE_ACCESS_SECRET, GOOGLE_SECRET, c), Recorder())
    assert out[0]["gps_pending"] == 1
    (record,) = [r for r in caplog.records if "Unexpected error" in r.getMessage()]
    assert "venue 3" in record.getMessage() and "RuntimeError" in record.getMessage()
    assert_no_secrets(caplog)
