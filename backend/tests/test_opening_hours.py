import pytest

from sportnav_data.opening_hours import normalize_opening_hours

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def test_weekday_and_weekend_rules_give_seven_rows():
    assert normalize_opening_hours("Mo-Fr 06:00-22:00; Sa,Su 08:00-20:00") == [
        ("mon", "06:00", "22:00"),
        ("tue", "06:00", "22:00"),
        ("wed", "06:00", "22:00"),
        ("thu", "06:00", "22:00"),
        ("fri", "06:00", "22:00"),
        ("sat", "08:00", "20:00"),
        ("sun", "08:00", "20:00"),
    ]


def test_24_7_is_every_day_all_day():
    assert normalize_opening_hours("24/7") == [(d, "00:00", "23:59") for d in DAYS]
    assert normalize_opening_hours("  24/7 ") == [(d, "00:00", "23:59") for d in DAYS]


def test_multiple_ranges_in_one_day_are_sorted_by_opening_time():
    assert normalize_opening_hours("Mo-Su 16:00-22:00,10:00-14:00") == [
        row for d in DAYS for row in ((d, "10:00", "14:00"), (d, "16:00", "22:00"))
    ]
    assert normalize_opening_hours("Mo 10:00-14:00, 16:00-22:00") == [
        ("mon", "10:00", "14:00"),
        ("mon", "16:00", "22:00"),
    ]


def test_past_midnight_stays_one_row_on_the_opening_day():
    assert normalize_opening_hours("Fr 22:00-02:00") == [("fri", "22:00", "02:00")]


def test_24_00_closing_becomes_23_59():
    assert normalize_opening_hours("Mo 08:00-24:00") == [("mon", "08:00", "23:59")]
    assert normalize_opening_hours("Mo-Su 00:00-24:00") == [(d, "00:00", "23:59") for d in DAYS]


def test_range_wrapping_over_the_end_of_the_week():
    assert normalize_opening_hours("Sa-Mo 10:00-12:00") == [
        ("mon", "10:00", "12:00"),
        ("sat", "10:00", "12:00"),
        ("sun", "10:00", "12:00"),
    ]
    assert normalize_opening_hours("Su-Tu 09:00-10:00") == [
        ("mon", "09:00", "10:00"),
        ("tue", "09:00", "10:00"),
        ("sun", "09:00", "10:00"),
    ]


def test_day_lists_mixed_with_ranges():
    assert normalize_opening_hours("Mo,We,Fr-Su 09:00-17:00") == [
        (d, "09:00", "17:00") for d in ("mon", "wed", "fri", "sat", "sun")
    ]


def test_rule_without_days_applies_to_every_day():
    assert normalize_opening_hours("08:00-20:00") == [(d, "08:00", "20:00") for d in DAYS]


def test_later_rule_replaces_earlier_one_and_off_empties_a_day():
    assert normalize_opening_hours("Mo-Fr 08:00-20:00; We off") == [
        ("mon", "08:00", "20:00"),
        ("tue", "08:00", "20:00"),
        ("thu", "08:00", "20:00"),
        ("fri", "08:00", "20:00"),
    ]
    assert normalize_opening_hours("Mo-Fr 08:00-20:00; Sa 09:00-12:00; Fr closed") == [
        ("mon", "08:00", "20:00"),
        ("tue", "08:00", "20:00"),
        ("wed", "08:00", "20:00"),
        ("thu", "08:00", "20:00"),
        ("sat", "09:00", "12:00"),
    ]
    # replacement, not merge
    assert normalize_opening_hours("Mo-Fr 08:00-20:00; Fr 10:00-12:00") == [
        ("mon", "08:00", "20:00"),
        ("tue", "08:00", "20:00"),
        ("wed", "08:00", "20:00"),
        ("thu", "08:00", "20:00"),
        ("fri", "10:00", "12:00"),
    ]


def test_result_is_sorted_by_day_then_opening_time():
    assert normalize_opening_hours("Su 10:00-12:00; Mo 18:00-20:00,08:00-10:00") == [
        ("mon", "08:00", "10:00"),
        ("mon", "18:00", "20:00"),
        ("sun", "10:00", "12:00"),
    ]


def test_trailing_semicolon_and_extra_whitespace_are_tolerated():
    assert normalize_opening_hours("  Mo   08:00-09:00 ;") == [("mon", "08:00", "09:00")]


@pytest.mark.parametrize(
    "raw",
    [
        "Mo-Fr 08:00-17:00; PH off",
        "PH off",
        "sunrise-sunset",
        "Mo-Fr sunrise-sunset",
        "Mo-Fr 08:00-12:00, Sa 09:00-12:00",  # comma separated rules
        "Mo-Fr 08:00-12:00,Sa 09:00-12:00",
        "Mo-Fr 08:00-12:00 || Sa 09:00-12:00",
        'Mo-Fr 08:00-17:00 "by appointment"',
        "Mo-Fr 08:00+",
        "Jan-Mar Mo-Fr 08:00-17:00",
        "week 1-10 Mo 08:00-17:00",
        "Mo-Fr 08:00-25:00",
        "Mo-Fr 08:00-24:30",
        "Mo-Fr 24:00-02:00",
        "Mo-Fr 08:60-10:00",
        "Mo-Fr 8:00-10:00",
        "Mo-Fr",
        "Xx 08:00-10:00",
        "Mo-Fr 08:00-10:00; garbage",
        "24/7; Mo off",
        "Mo 08:00-08:00",
    ],
)
def test_unsupported_syntax_gives_empty_result_all_or_nothing(raw):
    assert normalize_opening_hours(raw) == []


@pytest.mark.parametrize("raw", [None, 42, 3.5, True, [], {}, b"Mo 08:00-10:00", "", "   ", ";"])
def test_non_strings_and_empty_strings_give_empty_list_without_exception(raw):
    assert normalize_opening_hours(raw) == []
