from dataclasses import replace

import pytest

from craigslist.filters import Filters, Flag, match_counts
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
