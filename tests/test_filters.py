from dataclasses import replace

import pytest

from craigslist.filters import (
    Filters,
    Flag,
    hidden_count,
    match_counts,
    trim_options,
    unhidden,
    year_bounds,
    year_options,
)
from craigslist.listings import Listing, OwnerType, Source

CAR = Listing("carfax:1", Source.CARFAX, "car", 10_000, 50_000, "https://example.org/1", (), OwnerType.DEALER)


def test_no_filters_pass_everything_and_are_inactive():
    assert Filters().passes(CAR)
    assert not Filters().active()


@pytest.mark.parametrize(
    "value, include_unknown, passes",
    [
        (True, True, True),
        (True, False, True),
        (False, True, False),
        (False, False, False),
        (None, True, True),
        (None, False, False),
    ],
)
@pytest.mark.parametrize("attribute", ["one_owner", "no_accidents", "price_dropped"])
def test_a_flag_that_is_on_passes_true_fails_false_and_follows_include_unknown(attribute, value, include_unknown, passes):
    filters = replace(Filters(), **{attribute: Flag(on=True, include_unknown=include_unknown)})

    assert filters.passes(replace(CAR, **{attribute: value})) is passes
    assert filters.active()


@pytest.mark.parametrize("value", [True, False, None])
def test_a_flag_that_is_off_passes_everything_whatever_include_unknown_says(value):
    filters = Filters(one_owner=Flag(on=False, include_unknown=False))

    assert filters.passes(replace(CAR, one_owner=value))
    assert not filters.active()


def test_a_listing_must_pass_every_active_flag():
    filters = Filters(one_owner=Flag(on=True), price_dropped=Flag(on=True))

    assert filters.passes(replace(CAR, one_owner=True, price_dropped=True))
    assert not filters.passes(replace(CAR, one_owner=True, price_dropped=False))


def test_craigslist_listings_pass_while_unknowns_are_included():
    craigslist = Listing("1", Source.CRAIGSLIST, "car", 1, 1, "u", (), OwnerType.OWNER)
    on = Flag(on=True)

    assert Filters(one_owner=on, no_accidents=on, price_dropped=on).passes(craigslist)
    assert not Filters(one_owner=Flag(on=True, include_unknown=False)).passes(craigslist)


def test_match_counts_split_listings_into_matched_and_faded():
    listings = [replace(CAR, one_owner=True), replace(CAR, one_owner=False), replace(CAR, one_owner=None)]

    assert match_counts(listings, Filters(one_owner=Flag(on=True))) == (2, 1)
    assert match_counts(listings, Filters(one_owner=Flag(on=True, include_unknown=False))) == (1, 2)
    assert match_counts(listings, Filters()) == (3, 0)


# Year range


@pytest.mark.parametrize(
    "year, passes",
    [(2017, False), (2018, True), (2019, True), (2020, True), (2021, False), (None, True)],
)
def test_a_year_range_passes_years_inside_it_inclusive(year, passes):
    filters = Filters(min_year=2018, max_year=2020)

    assert filters.passes(replace(CAR, year=year)) is passes
    assert filters.active()


def test_an_open_ended_year_range_bounds_one_side_only():
    assert Filters(min_year=2018).passes(replace(CAR, year=2030))
    assert not Filters(min_year=2018).passes(replace(CAR, year=2010))
    assert Filters(max_year=2018).passes(replace(CAR, year=1990))


def test_unknown_years_fail_once_include_unknown_year_is_unticked():
    assert not Filters(min_year=2018, include_unknown_year=False).passes(replace(CAR, year=None))
    assert not Filters(include_unknown_year=False).passes(replace(CAR, year=None))
    assert Filters(include_unknown_year=False).passes(replace(CAR, year=2001))
    assert Filters(include_unknown_year=False).active()


def test_year_options_are_the_distinct_known_years_in_order():
    listings = [replace(CAR, year=year) for year in (2019, None, 2015, 2019, 2021)]

    assert year_options(listings) == [2015, 2019, 2021]
    assert year_options([]) == []


def test_a_chosen_year_at_either_end_of_the_options_leaves_that_side_open():
    options = [2015, 2018, 2021]

    assert year_bounds(2015, 2021, options) == (None, None)
    assert year_bounds(2018, 2021, options) == (2018, None)
    assert year_bounds(2015, 2018, options) == (None, 2018)
    assert year_bounds(None, None, options) == (None, None)
    assert year_bounds(None, None, []) == (None, None)


# Trim


def test_a_hidden_trim_fades_its_listings_and_unknown_is_its_own_chip():
    sport, plain, unknown = replace(CAR, trim="Sport"), replace(CAR, trim="LX"), replace(CAR, trim=None)

    hide_sport = Filters(hidden_trims=frozenset({"Sport"}))
    assert not hide_sport.passes(sport) and hide_sport.passes(plain) and hide_sport.passes(unknown)
    assert hide_sport.active()
    hide_unknown = Filters(hidden_trims=frozenset({None}))
    assert hide_unknown.passes(sport) and not hide_unknown.passes(unknown)


def test_trim_options_are_the_distinct_known_trims_grouped_by_exact_text():
    listings = [replace(CAR, trim=trim) for trim in ("Sport", None, "EX-L", "Sport", "sport", "EX L")]

    assert trim_options(listings) == ["EX L", "EX-L", "Sport", "sport"]


def test_unhidden_drops_hidden_ids_only_and_the_same_car_on_another_source_stays():
    carmax_twin = replace(CAR, id="carmax:1", source=Source.CARMAX)
    other = replace(CAR, id="carfax:2")

    assert unhidden([CAR, carmax_twin, other], {"carfax:1"}) == [carmax_twin, other]
    assert unhidden([CAR, other], frozenset()) == [CAR, other]


def test_hidden_count_counts_the_listings_whose_id_is_hidden():
    other = replace(CAR, id="carfax:2")

    assert hidden_count([CAR, other], {"carfax:1", "carfax:99"}) == 1
    assert hidden_count([CAR, other], frozenset()) == 0
