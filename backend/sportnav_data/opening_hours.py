"""Normalization of OSM `opening_hours` tag values to (day, opens, closes) tuples (DESIGN.md 8.5, 8.10).

Supported subset of the OSM opening_hours syntax:

    24/7                                   -> all 7 days 00:00-23:59
    rule; rule; ...                        -> rules separated by ';'
    rule = [day selection] times           e.g. "Mo-Fr 06:00-22:00", "Sa,Su 08:00-20:00"
         | [day selection] off | closed     e.g. "We off"
    day selection: Mo Tu We Th Fr Sa Su, ranges (also wrapping, "Sa-Mo") and lists ("Mo,We,Fr-Su");
                   without a day selection the rule applies to every day
    times: one or more "HH:MM-HH:MM" ranges separated by ',';
           "24:00" as a closing time is stored as "23:59"; closes < opens means "past midnight"

A later rule replaces an earlier one for the days it selects (OSM semantics); `off` / `closed`
empties those days. Anything else (public holidays, months, weeks, sunrise / sunset, comments,
'+', '||', times above 24:00, comma separated rules, ...) makes the whole result [] - all or
nothing. The function never raises.

One tuple describes one block of opening that STARTS on `day`; with closes < opens the venue
closes after midnight of the following day (DESIGN.md 8.10).
"""

from __future__ import annotations

import re

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_OSM_DAYS = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}
_RANGE_RE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")

_Ranges = list[tuple[str, str]]


class _Unsupported(Exception):
    """Internal: the value uses syntax outside the supported subset."""


def _time(hh: str, mm: str, *, closing: bool) -> str:
    h, m = int(hh), int(mm)
    if m > 59:
        raise _Unsupported
    if h == 24 and m == 0 and closing:
        return "23:59"
    if h > 23:
        raise _Unsupported
    return f"{h:02d}:{m:02d}"


def _parse_times(text: str) -> _Ranges | None:
    """Parse "HH:MM-HH:MM,..." or "off" / "closed" (-> []); None when `text` is neither."""
    if text in ("off", "closed"):
        return []
    text = re.sub(r",\s+", ",", text)
    ranges: set[tuple[str, str]] = set()
    for part in text.split(","):
        m = _RANGE_RE.match(part)
        if not m:
            return None
        opens = _time(m.group(1), m.group(2), closing=False)
        closes = _time(m.group(3), m.group(4), closing=True)
        if opens == closes:
            raise _Unsupported
        ranges.add((opens, closes))
    return sorted(ranges)


def _parse_days(selection: str) -> set[int]:
    days: set[int] = set()
    for part in selection.split(","):
        first, sep, last = part.partition("-")
        if first not in _OSM_DAYS or (sep and last not in _OSM_DAYS):
            raise _Unsupported
        start = _OSM_DAYS[first]
        end = _OSM_DAYS[last] if sep else start
        day = start
        days.add(day)
        while day != end:  # a range may wrap around the end of the week ("Sa-Mo")
            day = (day + 1) % 7
            days.add(day)
    return days


def _parse_rule(rule: str) -> tuple[set[int], _Ranges]:
    times = _parse_times(rule)
    if times is not None:  # no day selection -> every day
        return set(range(7)), times
    pieces = rule.split(None, 1)
    if len(pieces) != 2:
        raise _Unsupported
    days = _parse_days(pieces[0])
    times = _parse_times(pieces[1].strip())
    if times is None:
        raise _Unsupported
    return days, times


def _parse(raw: object) -> list[tuple[str, str, str]]:
    if not isinstance(raw, str):
        return []
    text = raw.strip()
    if not text:
        return []
    if text == "24/7":
        return [(day, "00:00", "23:59") for day in _DAYS]

    schedule: dict[int, _Ranges] = {}
    for rule in text.split(";"):
        rule = rule.strip()
        if not rule:  # tolerate a trailing ';'
            continue
        days, times = _parse_rule(rule)
        for day in days:
            schedule[day] = list(times)

    return [
        (_DAYS[day], opens, closes)
        for day in sorted(schedule)
        for opens, closes in sorted(schedule[day])
    ]


def normalize_opening_hours(raw: object) -> list[tuple[str, str, str]]:
    """Convert an OSM `opening_hours` value to [(day, "HH:MM", "HH:MM"), ...]; [] if unusable."""
    try:
        return _parse(raw)
    except Exception:  # unsupported syntax or anything unexpected: never raise (DESIGN.md 8.5)
        return []
