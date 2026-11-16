import logging

import pytest

from sportnav_data.categories import CATEGORIES, CATEGORY_SLUGS, map_category_names

EXPECTED = {
    "Bazény a vodní sporty": "bazeny-a-vodni-sporty-1",
    "Jóga a zdravotní cvičení": "joga-a-zdravotni-cviceni-3",
    "Lezecké stěny": "lezecke-steny-4",
    "Posilovny a silové tréninky": "posilovny-a-silove-treninky-5",
    "Raketové a míčové sporty": "raketove-a-micove-sporty-7",
    "Skupinové a taneční lekce": "skupinove-a-tanecni-lekce-9",
    "Wellness a relax": "wellness-a-relax-10",
}


@pytest.mark.parametrize("name,slug", EXPECTED.items())
def test_each_name_maps_to_slug(name, slug):
    assert CATEGORY_SLUGS[name] == slug
    assert map_category_names([name]) == [slug]


def test_exactly_seven_categories_consistent():
    assert CATEGORY_SLUGS == EXPECTED
    assert len(CATEGORIES) == 7
    assert {name: slug for slug, name in CATEGORIES} == EXPECTED


def test_unknown_category_skipped_and_logged(caplog):
    venue = {"title": "Legion Gym", "categories": ["Posilovny a silové tréninky", "Neznáma"]}
    with caplog.at_level(logging.WARNING, logger="sportnav_data.categories"):
        slugs = map_category_names(venue["categories"])
    assert slugs == ["posilovny-a-silove-treninky-5"]
    assert "Neznáma" in caplog.text
    assert venue["title"] == "Legion Gym"  # venue itself is untouched / kept


def test_only_unknown_categories_gives_empty_list_without_exception(caplog):
    with caplog.at_level(logging.WARNING):
        assert map_category_names(["Neznáma"]) == []
    assert map_category_names(None) == []
    assert map_category_names([]) == []


def test_single_string_is_one_category_name(caplog):
    with caplog.at_level(logging.WARNING):
        assert map_category_names("Wellness a relax") == ["wellness-a-relax-10"]
    assert caplog.records == []  # no per-character warnings


def test_single_unknown_string_logs_once(caplog):
    with caplog.at_level(logging.WARNING, logger="sportnav_data.categories"):
        assert map_category_names("Neznáma") == []
    assert len(caplog.records) == 1


@pytest.mark.parametrize("bad", [None, 5, 3.5, True, object()])
def test_non_iterable_returns_empty_and_logs(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="sportnav_data.categories"):
        assert map_category_names(bad) == []
    assert len(caplog.records) == 1


def test_duplicates_removed():
    assert map_category_names(["Wellness a relax", "Wellness a relax"]) == ["wellness-a-relax-10"]
