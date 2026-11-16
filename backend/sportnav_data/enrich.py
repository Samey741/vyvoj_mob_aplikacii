"""Enrichment of scraped venues with GPS and opening hours via OpenStreetMap Nominatim
(DESIGN.md sections 3.2, 8.3, 8.4, 8.9, 9.1).

Pipeline per venue: POI query ("title, street, city") -> address query ("street, city", only when the
POI query returned `[]`) -> gps_pending. The `httpx.AsyncClient` is always passed in, so tests can use
`httpx.MockTransport`.

Usage policy (section 3.2): venues are processed strictly sequentially and at least `min_interval`
seconds pass between the starts of two consecutive requests, including the two requests of one venue.

Error policy (section 8.9):
    * "nothing found" means HTTP 200 with an empty JSON array; only then the next phase is tried.
    * HTTP 403                        -> NominatimBlockedError, the whole run stops immediately.
    * 429 / other 4xx / 5xx / timeout / connection error / invalid JSON / JSON that is not an array
                                      -> this venue becomes gps_pending (no further phase), the error is
                                         logged and the run continues.
    * a result without valid coordinates counts as an empty result of that phase.
    * httpx exceptions are logged by type and HTTP status only (never the URL, which carries the e-mail).

Enriched record = input venue plus the keys:
    lat, lon        float | None
    opening_hours   normalized list of (day, "HH:MM", "HH:MM")
    gps_source      "nominatim_poi" | "nominatim_address" | None
    gps_pending     0 | 1   (1 <=> no GPS found; lat/lon are None)
The input venue is never modified.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time

import httpx

from .opening_hours import normalize_opening_hours

logger = logging.getLogger(__name__)


class _RedactEmailFilter(logging.Filter):
    """Scrub `email=<address>` query values from records of the `httpx` logger.

    httpx logs every request at INFO as `HTTP Request: GET <full url> ...`, and the Nominatim URL
    carries the optional contact e-mail in its query string.
    """

    _PATTERN = re.compile(r"([?&]email=)[^&\s\"']*", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self._PATTERN.sub(r"\g<1>***", message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


_httpx_logger = logging.getLogger("httpx")
if not any(isinstance(f, _RedactEmailFilter) for f in _httpx_logger.filters):
    _httpx_logger.addFilter(_RedactEmailFilter())

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "SportNav-data-import/1.0"

SOURCE_POI = "nominatim_poi"
SOURCE_ADDRESS = "nominatim_address"

PROGRESS_EVERY = 50  # log progress after this many venues in `enrich_all`


class NominatimBlockedError(Exception):
    """Nominatim answered HTTP 403 (IP blocked for violating the usage policy), see DESIGN.md 8.9."""


def _safe_error(exc: BaseException) -> str:
    """Describe an exception for logs without leaking the request URL (it carries the e-mail).

    For httpx errors only the exception type and the HTTP status code are reported, never
    `str(exc)` / `repr(exc)`. `ValueError` messages come from this module or from JSON decoding.
    """
    name = type(exc).__name__
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{name} (HTTP {exc.response.status_code})"
    if isinstance(exc, httpx.HTTPError):
        return name
    if isinstance(exc, ValueError):
        return f"{name}: {exc}"
    return name


async def nominatim_search(query: str, client: httpx.AsyncClient, email: str | None = None) -> dict | None:
    """Return the first Nominatim result for `query`, or None for HTTP 200 with `[]`.

    Raises NominatimBlockedError on HTTP 403, httpx.HTTPError on other HTTP / transport errors and
    ValueError when the body is not valid JSON or not an array. Note that "lat" / "lon" in the
    response are strings.
    """
    params: dict[str, str | int] = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "extratags": 1,
        "countrycodes": "cz,sk",
        "accept-language": "cs",
    }
    if email:
        params["email"] = email
    resp = await client.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT})
    if resp.status_code == 403:
        raise NominatimBlockedError("Nominatim answered HTTP 403 (blocked), run aborted")
    resp.raise_for_status()
    results = resp.json()  # json.JSONDecodeError / UnicodeDecodeError are ValueErrors
    if not isinstance(results, list):
        raise ValueError(f"expected a JSON array, got {type(results).__name__}")
    if not results:
        return None
    first = results[0]
    return first if isinstance(first, dict) else {}  # not an object -> no usable coordinates


def _coordinate(value: object, limit: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number) or abs(number) > limit:
        return None
    return number


def _coordinates(result: dict) -> tuple[float, float] | None:
    lat, lon = _coordinate(result.get("lat"), 90.0), _coordinate(result.get("lon"), 180.0)
    if lat is None or lon is None:
        return None
    return lat, lon


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _join(*parts: object) -> str:
    return ", ".join(p for p in (_text(part) for part in parts) if p)


def _poi_hours(result: dict) -> list[tuple[str, str, str]]:
    extratags = result.get("extratags")
    raw = extratags.get("opening_hours") if isinstance(extratags, dict) else None
    return normalize_opening_hours(raw)


class _Throttle:
    """Keeps at least `min_interval` seconds between the starts of consecutive requests."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self._last_start: float | None = None

    async def wait(self) -> None:
        if self._last_start is not None:
            while True:
                remaining = self._last_start + self.min_interval - time.perf_counter()
                if remaining <= 0:
                    break
                await asyncio.sleep(remaining)
        self._last_start = time.perf_counter()


def _pending(venue: dict) -> dict:
    result = dict(venue)
    result.update(lat=None, lon=None, opening_hours=[], gps_source=None, gps_pending=1)
    return result


def _found(venue: dict, coords: tuple[float, float], hours: list[tuple[str, str, str]], source: str) -> dict:
    result = dict(venue)
    result.update(lat=coords[0], lon=coords[1], opening_hours=hours, gps_source=source, gps_pending=0)
    return result


async def _enrich_venue(
    venue: dict, client: httpx.AsyncClient, email: str | None, throttle: _Throttle
) -> dict:
    """Implementation of `enrich_venue` with a throttle that may be shared by a whole run."""
    poi_query = _join(venue.get("title"), venue.get("street"), venue.get("city"))
    address_query = _join(venue.get("street"), venue.get("city"))

    phases: list[tuple[str, str]] = []
    if poi_query:
        phases.append((poi_query, SOURCE_POI))
    if address_query and address_query != poi_query:
        phases.append((address_query, SOURCE_ADDRESS))

    for query, source in phases:
        await throttle.wait()
        try:
            hit = await nominatim_search(query, client, email)
        except NominatimBlockedError:
            raise
        except Exception as exc:  # noqa: BLE001 - any per-venue error, incl. httpx errors outside HTTPError
            # 429 / other 4xx / 5xx / timeout / invalid JSON / InvalidURL / StreamError ...:
            # pending, no further phase (8.9). Only the exception type / HTTP code is logged.
            logger.warning(
                "Nominatim request failed for venue %s, marking gps_pending: %s",
                venue.get("id"),
                _safe_error(exc),
            )
            return _pending(venue)

        coords = _coordinates(hit) if hit is not None else None
        if coords is not None:
            hours = _poi_hours(hit) if source == SOURCE_POI else []  # address hit: GPS only (3.2)
            return _found(venue, coords, hours, source)
        # empty result (or one without valid coordinates): try the next phase

    return _pending(venue)


async def enrich_venue(
    venue: dict, client: httpx.AsyncClient, email: str | None = None, min_interval: float = 1.0
) -> dict:
    """POI query -> address query (only when the POI query returned `[]`) -> gps_pending.

    A failure of one venue (429, other HTTP errors, timeout, bad JSON) is logged and yields
    gps_pending without the next phase. HTTP 403 raises NominatimBlockedError. `min_interval` is
    the gap between the two requests of this venue.
    """
    return await _enrich_venue(venue, client, email, _Throttle(min_interval))


async def enrich_all(
    venues: list[dict], client: httpx.AsyncClient, email: str | None = None, min_interval: float = 1.0
) -> list[dict]:
    """Enrich all venues sequentially (no concurrency), preserving their order (section 8.4).

    At least `min_interval` seconds pass between the starts of two consecutive requests of the
    run. Raises NominatimBlockedError on HTTP 403; no further request is sent after that.
    """
    throttle = _Throttle(min_interval)
    total = len(venues)
    enriched: list[dict] = []
    for index, venue in enumerate(venues, start=1):
        try:
            enriched.append(await _enrich_venue(venue, client, email, throttle))
        except NominatimBlockedError:
            raise
        except Exception as exc:  # last resort: one venue must never abort the whole run
            # No traceback / message: an unexpected exception could embed the request URL.
            logger.error("Unexpected error enriching venue %s: %s", venue.get("id"), _safe_error(exc))
            enriched.append(_pending(venue))
        if index % PROGRESS_EVERY == 0 or index == total:
            logger.info("Enriched %d / %d venues", index, total)
    return enriched
