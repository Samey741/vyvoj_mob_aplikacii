"""Enrichment of scraped venues with GPS and opening hours (DESIGN.md sections 3.2, 8.3-8.5, 8.9, 9.1).

Pipeline per venue: Apple Maps Server API -> Google Places fallback (GPS only) -> gps_pending.
The `httpx.AsyncClient` is always passed in, so tests can use `httpx.MockTransport`.

Error policy (section 8.9):
    * Google is called only when Apple answered HTTP 200 with an empty `results`.
    * Apple 401 / 403            -> AppleAuthError; `enrich_all` refreshes the access token once
                                    (if `apple_auth_token` is given) and retries, otherwise the whole
                                    run aborts with AppleAuthError (no further Google calls).
    * Apple 429 / 5xx / timeout / invalid or non-object JSON for one venue
                                 -> gps_pending = 1 without calling Google, logged, run continues.
    * `enrich_all(max_google_calls=500)` caps Google calls; beyond the cap venues without an Apple
      result become gps_pending without Google and one warning is logged.

Enriched record = input venue plus the keys:
    lat, lon        float | None
    opening_hours   normalized list of (day, "HH:MM", "HH:MM")
    gps_source      "apple_maps" | "google_places_fallback" | None
    gps_pending     0 | 1   (1 <=> no GPS found; lat/lon are None)
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable

import httpx

from .opening_hours import normalize_opening_hours

logger = logging.getLogger(__name__)


class _RedactApiKeyFilter(logging.Filter):
    """Scrub `key=<secret>` query values from records of the `httpx` logger.

    httpx logs every request at INFO as `HTTP Request: GET <full url> ...`, and the Google URL
    carries the API key in its query string (`key=<GOOGLE_API_KEY>`).
    """

    _PATTERN = re.compile(r"([?&]key=)[^&\s\"']*", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self._PATTERN.sub(r"\g<1>***", message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


_httpx_logger = logging.getLogger("httpx")
if not any(isinstance(f, _RedactApiKeyFilter) for f in _httpx_logger.filters):
    _httpx_logger.addFilter(_RedactApiKeyFilter())

APPLE_TOKEN_URL = "https://maps-api.apple.com/v1/token"
APPLE_SEARCH_URL = "https://maps-api.apple.com/v1/search"
GOOGLE_FIND_PLACE_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"

SOURCE_APPLE = "apple_maps"
SOURCE_GOOGLE = "google_places_fallback"


class AppleAuthError(Exception):
    """Apple Maps rejected the access token (HTTP 401 / 403), see DESIGN.md section 8.9."""


def _safe_error(exc: BaseException) -> str:
    """Describe an exception for logs / re-raised messages without leaking secrets.

    `httpx.HTTPStatusError` (and some transport errors) embed the full request URL in their
    message, and the Google URL carries `key=<GOOGLE_API_KEY>`. So for httpx errors only the
    exception type and the HTTP status code are reported, never `str(exc)` / `repr(exc)`.
    `ValueError` messages come from this module or from JSON decoding and contain no URL.
    """
    name = type(exc).__name__
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{name} (HTTP {exc.response.status_code})"
    if isinstance(exc, httpx.HTTPError):
        return name
    if isinstance(exc, ValueError):
        return f"{name}: {exc}"
    return name


def _query(venue: dict) -> str:
    parts = (venue.get("title"), venue.get("street"), venue.get("city"))
    return " ".join(str(p).strip() for p in parts if p and str(p).strip())


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _json_object(resp: httpx.Response) -> dict:
    """Decode a response body that must be a JSON object; ValueError otherwise."""
    data = resp.json()  # json.JSONDecodeError / UnicodeDecodeError are ValueErrors
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return data


def _apple_coordinates(place: object) -> tuple[float, float] | None:
    """Extract (lat, lon) from an Apple place.

    Apple's documented shape is `coordinate: {latitude, longitude}`; the sketch in
    DESIGN.md 3.2 used `center: {lat, lng}`, so both are accepted.
    """
    if not isinstance(place, dict):
        return None
    coord = place.get("coordinate")
    if isinstance(coord, dict):
        lat, lon = coord.get("latitude"), coord.get("longitude")
        if _is_number(lat) and _is_number(lon):
            return float(lat), float(lon)
    center = place.get("center")
    if isinstance(center, dict):
        lat, lon = center.get("lat"), center.get("lng")
        if _is_number(lat) and _is_number(lon):
            return float(lat), float(lon)
    return None


async def get_apple_access_token(auth_token: str, client: httpx.AsyncClient) -> str:
    """Exchange the Maps auth token (JWT from the developer portal) for an access token.

    Raises httpx.HTTPError on HTTP / transport errors and ValueError on an unusable body.
    """
    resp = await client.get(APPLE_TOKEN_URL, headers={"Authorization": f"Bearer {auth_token}"})
    resp.raise_for_status()
    token = _json_object(resp).get("accessToken")
    if not isinstance(token, str) or not token:
        raise ValueError("Apple token response has no accessToken")
    return token


async def enrich_venue_apple(venue: dict, token: str, client: httpx.AsyncClient) -> dict:
    """Search Apple Maps. Returns an updated copy on a hit, an unchanged copy on HTTP 200 with
    empty results (the only case that means "no result", section 8.9).

    Raises AppleAuthError on 401 / 403, httpx.HTTPError on other HTTP / transport errors and
    ValueError on invalid, non-object or unusable (no coordinates) responses. These are handled
    by `enrich_venue` / `enrich_all`.
    """
    result = dict(venue)
    resp = await client.get(
        APPLE_SEARCH_URL,
        params={"q": _query(venue), "lang": "sk-SK", "resultTypeFilter": "Poi"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code in (401, 403):
        raise AppleAuthError(f"Apple Maps rejected the access token (HTTP {resp.status_code})")
    resp.raise_for_status()
    if resp.status_code != 200:
        raise ValueError(f"unexpected Apple Maps status {resp.status_code}")

    results = _json_object(resp).get("results")
    if results is None:
        return result  # 200 without results == empty -> fallback
    if not isinstance(results, list):
        raise ValueError("Apple Maps 'results' is not a list")
    if not results:
        return result  # -> fallback

    place = results[0]
    coords = _apple_coordinates(place)
    if coords is None:
        raise ValueError("Apple Maps result has no usable coordinates")

    result["lat"], result["lon"] = coords
    result["opening_hours"] = normalize_opening_hours(place.get("openingHours"))
    result["gps_source"] = SOURCE_APPLE
    return result


async def enrich_venue_google_fallback(venue: dict, api_key: str, client: httpx.AsyncClient) -> dict:
    """Google Find Place, GPS only (`fields=geometry`); opening hours stay untouched (section 8.4).

    Raises httpx.HTTPError on transport / HTTP errors and ValueError on invalid / non-object JSON
    (handled by `enrich_venue`).
    """
    result = dict(venue)
    resp = await client.get(
        GOOGLE_FIND_PLACE_URL,
        params={
            "input": _query(venue),
            "inputtype": "textquery",
            "fields": "geometry",
            "key": api_key,
        },
    )
    resp.raise_for_status()
    candidates = _json_object(resp).get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return result

    try:
        location = candidates[0]["geometry"]["location"]
        lat, lon = location["lat"], location["lng"]
    except (KeyError, TypeError):
        return result
    if not (_is_number(lat) and _is_number(lon)):
        return result

    result["lat"], result["lon"] = float(lat), float(lon)
    result["gps_source"] = SOURCE_GOOGLE
    return result


def _has_gps(venue: dict) -> bool:
    return venue.get("lat") is not None and venue.get("lon") is not None


def _valid_hours(hours: object) -> list[tuple[str, str, str]]:
    """Keep already-normalized hours (list of 3 strings each); anything else becomes []."""
    if not isinstance(hours, list):
        return []
    out: list[tuple[str, str, str]] = []
    for item in hours:
        if isinstance(item, (tuple, list)) and len(item) == 3 and all(isinstance(x, str) for x in item):
            out.append((item[0], item[1], item[2]))
    return out


def _finalize(venue: dict) -> dict:
    """Fill in the enriched-record keys; mark gps_pending when no GPS was found.

    `opening_hours` is already normalized by `enrich_venue_apple` - it must not be normalized again
    (normalization expects the raw API payload and would erase it).
    """
    result = dict(venue)
    result["opening_hours"] = _valid_hours(result.get("opening_hours"))
    if _has_gps(result):
        result["gps_pending"] = 0
    else:
        result["lat"] = None
        result["lon"] = None
        result["gps_source"] = None
        result["gps_pending"] = 1
    return result


# Returns True when a Google call may be made (and reserves it).
GoogleGate = Callable[[], bool]


async def _enrich_venue(
    venue: dict,
    apple_token: str,
    google_key: str | None,
    client: httpx.AsyncClient,
    google_gate: GoogleGate | None = None,
) -> dict:
    """Implementation of `enrich_venue` with an optional gate limiting Google calls."""
    current = dict(venue)

    try:
        current = await enrich_venue_apple(current, apple_token, client)
    except (httpx.HTTPError, ValueError) as exc:
        # 429 / 5xx / timeout / invalid JSON: venue stays pending, Google is NOT called (8.9).
        logger.warning(
            "Apple Maps failed for venue %s, marking gps_pending: %s", venue.get("id"), _safe_error(exc)
        )
        return _finalize(current)
    # AppleAuthError is deliberately not caught here.

    if not _has_gps(current):  # Apple answered 200 with empty results
        if not google_key:
            logger.info("Google fallback skipped (no GOOGLE_API_KEY) for venue %s", venue.get("id"))
        elif google_gate is not None and not google_gate():
            logger.debug("Google fallback skipped (call cap reached) for venue %s", venue.get("id"))
        else:
            try:
                current = await enrich_venue_google_fallback(current, google_key, client)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Google fallback failed for venue %s: %s", venue.get("id"), _safe_error(exc))

    return _finalize(current)


async def enrich_venue(
    venue: dict, apple_token: str, google_key: str | None, client: httpx.AsyncClient
) -> dict:
    """Apple -> Google (only if Apple answered 200 with empty results and a key exists) -> gps_pending.

    A venue-level Apple failure (429, 5xx, timeout, bad JSON) or a Google failure is logged and
    yields gps_pending (without calling Google after an Apple failure). Apple 401 / 403 raises
    AppleAuthError; token refresh and the Google call cap are handled by `enrich_all`.
    """
    return await _enrich_venue(venue, apple_token, google_key, client)


class _AppleSession:
    """Shared Apple access token for one `enrich_all` run; refreshed at most once (section 8.9)."""

    def __init__(self, token: str, auth_token: str | None) -> None:
        self.token = token
        self.auth_token = auth_token
        self.refreshed = False
        self.aborted = False
        self._lock = asyncio.Lock()

    async def refresh(self, stale_token: str, client: httpx.AsyncClient) -> str:
        """Return a token newer than `stale_token`, or raise AppleAuthError (and abort the run)."""
        async with self._lock:
            if self.token != stale_token:
                return self.token  # another venue already refreshed it
            if self.refreshed or not self.auth_token:
                self.aborted = True
                reason = "token refresh did not help" if self.refreshed else "no apple_auth_token for refresh"
                raise AppleAuthError(f"Apple Maps authorization failed ({reason})")
            self.refreshed = True
            failure = None
            try:
                self.token = await get_apple_access_token(self.auth_token, client)
            except (httpx.HTTPError, ValueError) as exc:
                failure = _safe_error(exc)
            if failure is not None:
                # Raised outside the `except` block and without `from exc`: the original exception
                # (whose text may embed a URL or headers) must not hang off __cause__ / __context__.
                self.aborted = True
                raise AppleAuthError(f"Apple Maps token refresh failed: {failure}")
            logger.warning("Apple Maps access token rejected, refreshed it once")
            return self.token


async def enrich_all(
    venues: list[dict],
    apple_token: str,
    google_key: str | None,
    client: httpx.AsyncClient,
    concurrency: int = 5,
    apple_auth_token: str | None = None,
    max_google_calls: int = 500,
) -> list[dict]:
    """Enrich all venues with at most `concurrency` venues in flight; order is preserved.

    Raises AppleAuthError (section 8.9) when Apple keeps rejecting the token, after one refresh
    via `get_apple_access_token(apple_auth_token, client)` if `apple_auth_token` was given.
    At most `max_google_calls` Google requests are made per run.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))
    session = _AppleSession(apple_token, apple_auth_token)
    google_calls = 0
    cap_warned = False

    def google_gate() -> bool:
        nonlocal google_calls, cap_warned
        if session.aborted:
            return False
        if google_calls >= max_google_calls:
            if not cap_warned:
                cap_warned = True
                logger.warning(
                    "max_google_calls=%d reached; remaining venues without an Apple result "
                    "are marked gps_pending without calling Google",
                    max_google_calls,
                )
            return False
        google_calls += 1
        return True

    async def run(venue: dict) -> dict:
        async with semaphore:
            if session.aborted:
                return _finalize(venue)  # run is being aborted; make no further calls
            try:
                token = session.token
                try:
                    return await _enrich_venue(venue, token, google_key, client, google_gate)
                except AppleAuthError:
                    token = await session.refresh(token, client)
                    try:
                        return await _enrich_venue(venue, token, google_key, client, google_gate)
                    except AppleAuthError:
                        session.aborted = True
                        raise
            except AppleAuthError:
                raise
            except Exception as exc:  # last resort: one venue must never abort the whole run
                # No traceback / message: an unexpected exception could embed a request URL or header.
                logger.error("Unexpected error enriching venue %s: %s", venue.get("id"), _safe_error(exc))
                return _finalize(venue)

    tasks = [asyncio.ensure_future(run(v)) for v in venues]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
