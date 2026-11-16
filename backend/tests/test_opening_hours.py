import pytest

from sportnav_data.opening_hours import normalize_opening_hours


def period(open_day, open_time, close_day, close_time):
    return {
        "open": {"day": open_day, "time": open_time},
        "close": {"day": close_day, "time": close_time},
    }


def test_google_periods_format():
    raw = {"periods": [period(1, "0600", 1, "2200")]}
    assert normalize_opening_hours(raw) == [("mon", "06:00", "22:00")]


def test_bare_list_of_periods_and_sorting_and_sunday():
    raw = [period(0, "0900", 0, "1300"), period(2, "0700", 2, "2100"), period(1, "0600", 1, "2200")]
    assert normalize_opening_hours(raw) == [
        ("mon", "06:00", "22:00"),
        ("tue", "07:00", "21:00"),
        ("sun", "09:00", "13:00"),
    ]


def test_split_hours_same_day():
    raw = {"periods": [period(3, "1400", 3, "2000"), period(3, "0700", 3, "1100")]}
    assert normalize_opening_hours(raw) == [("wed", "07:00", "11:00"), ("wed", "14:00", "20:00")]


def test_overnight_crossing_midnight():
    raw = {"periods": [period(5, "2200", 6, "0200")]}
    assert normalize_opening_hours(raw) == [("fri", "22:00", "02:00")]


def test_sunday_to_monday_wraparound():
    raw = {"periods": [period(0, "2200", 1, "0100")]}
    assert normalize_opening_hours(raw) == [("sun", "22:00", "01:00")]


def test_open_24_7():
    raw = {"periods": [{"open": {"day": 0, "time": "0000"}}]}
    days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    assert normalize_opening_hours(raw) == [(d, "00:00", "23:59") for d in days]


@pytest.mark.parametrize("day", [1, 3, 6])
def test_open_only_period_not_on_day_zero_is_not_24_7(day):
    raw = {"periods": [{"open": {"day": day, "time": "0000"}}]}
    assert normalize_opening_hours(raw) == []


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        [],
        "",
        "Mon-Fri 6-22",
        42,
        3.5,
        True,
        {"periods": None},
        {"periods": "nope"},
        {"periods": [None, 1, "x", []]},
        {"periods": [{"open": {"day": 1, "time": "0600"}}, {"open": {"day": 1, "time": "0600"}}]},
        {"periods": [period(7, "0600", 7, "2200")]},
        {"periods": [period(1, "2500", 1, "2200")]},
        {"periods": [period(1, "abc", 1, "2200")]},
        {"periods": [period("mon", "0600", "mon", "2200")]},
        {"periods": [{"open": "x", "close": "y"}]},
        {"openingHours": {"text": ["Mon 6-22"]}},
        object(),
    ],
)
def test_none_and_unknown_format_returns_empty_without_exception(raw):
    assert normalize_opening_hours(raw) == []


def test_invalid_periods_are_skipped_valid_kept():
    raw = {"periods": [period(1, "0600", 1, "2200"), period(9, "0600", 9, "2200"), "junk"]}
    assert normalize_opening_hours(raw) == [("mon", "06:00", "22:00")]


def test_output_format_hhmm():
    result = normalize_opening_hours({"periods": [period(1, "0605", 1, "2230")]})
    assert result == [("mon", "06:05", "22:30")]
