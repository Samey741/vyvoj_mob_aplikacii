"""Normalization of API opening hours to (day, opens, closes) tuples.

Supported input (Google Places style, also the shape Apple results are expected to be
converted to, see DESIGN.md section 12):

    {"periods": [{"open": {"day": 1, "time": "0600"}, "close": {"day": 1, "time": "2200"}}, ...]}

A bare list of such periods is accepted too. `day` is 0 = Sunday ... 6 = Saturday.
A period that closes after midnight is kept as one tuple on the opening day with
`closes < opens` (e.g. ("fri", "22:00", "02:00")). A single period with `open` only
(day 0, time 0000, no `close`) means "open 24/7" and expands to every day 00:00-23:59.

Anything that cannot be parsed yields [] - the function never raises.
"""

from __future__ import annotations

import re

_DAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")  # Google numbering
_ORDER = {d: i for i, d in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
_TIME_RE = re.compile(r"^(\d{2}):?(\d{2})$")


def _day(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 6:
        return None
    return _DAYS[value]


def _time(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    m = _TIME_RE.match(value.strip())
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 23 or mm > 59:
        return None
    return f"{hh:02d}:{mm:02d}"


def _parse(raw: object) -> list[tuple[str, str, str]]:
    periods = raw.get("periods") if isinstance(raw, dict) else raw
    if not isinstance(periods, list) or not periods:
        return []

    # 24/7: single period with an `open` and no `close`
    if len(periods) == 1 and isinstance(periods[0], dict) and "close" not in periods[0]:
        opened = periods[0].get("open")
        if (
            isinstance(opened, dict)
            and _day(opened.get("day")) == "sun"  # day 0
            and _time(opened.get("time")) == "00:00"
        ):
            return [(d, "00:00", "23:59") for d in _ORDER]
        return []

    result: list[tuple[str, str, str]] = []
    for period in periods:
        if not isinstance(period, dict):
            continue
        opened, closed = period.get("open"), period.get("close")
        if not isinstance(opened, dict) or not isinstance(closed, dict):
            continue
        day = _day(opened.get("day"))
        opens = _time(opened.get("time"))
        closes = _time(closed.get("time"))
        if day is None or opens is None or closes is None:
            continue
        result.append((day, opens, closes))

    result.sort(key=lambda t: (_ORDER[t[0]], t[1]))
    return result


def normalize_opening_hours(raw: object) -> list[tuple[str, str, str]]:
    """Convert an API opening-hours payload to [(day, "HH:MM", "HH:MM"), ...]; [] if unusable."""
    try:
        return _parse(raw)
    except Exception:  # defensive: must never raise (DESIGN.md section 8.5)
        return []
