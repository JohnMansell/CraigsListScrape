import json
from datetime import UTC, datetime

import pytest

from craigslist.favorites import (
    EMPTY_TEXT,
    FAVORITES_KEY,
    SavedListing,
    SavedSearch,
    add_saved,
    button_text,
    favorite_row,
    listing_from_json,
    listing_to_json,
    read_saved,
    remove_saved,
    saved_from_json,
    saved_ids,
    saved_to_json,
    write_saved,
)
from craigslist.listings import Listing, OwnerType, Source
from craigslist.search import Search

POSTED = datetime(2026, 9, 28, 14, 3, tzinfo=UTC)
SAVED = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
ORIGIN = SavedSearch("CA", "Sf Bay Area", "Honda", "Civic")

CRAIGSLIST = Listing(
    "craigslist:7712345678", Source.CRAIGSLIST, "2015 Honda Civic LX", 12_500, 88_000,
    "https://sfbay.craigslist.org/view/d/7712345678", ("https://images.craigslist.org/00a_abc_600x450.jpg",),
    OwnerType.OWNER, POSTED, "Oakland", year=2015,
)
CARFAX = Listing(
    "carfax:1HGCM82633A004352", Source.CARFAX, "2018 Honda Civic Sport", 18_995, None,
    "https://www.carfax.com/vehicle/1HGCM82633A004352", (), OwnerType.DEALER, None, "Vallejo, CA",
    "Honda of Vallejo", True, False, True, 2018, "Sport",
)
CARMAX = Listing(
    "carmax:27766554", Source.CARMAX, "2019 Honda Civic EX", 19_998, 41_000,
    "https://www.carmax.com/car/27766554", ("https://img2.carmax.com/img/vehicles/27766554/1.jpg",),
    OwnerType.DEALER, datetime(2026, 9, 1, 0, 0, tzinfo=UTC), "Pleasanton, CA",
    "CarMax Pleasanton", None, None, False, 2019, "EX",
)


def saved(listing: Listing, when: datetime = SAVED) -> SavedListing:
    return SavedListing(listing, ORIGIN, when)


@pytest.mark.parametrize("listing", [CRAIGSLIST, CARFAX, CARMAX], ids=["craigslist", "carfax", "carmax"])
def test_a_listing_round_trips_through_json_text(listing):
    text = json.dumps(listing_to_json(listing))

    assert listing_from_json(json.loads(text)) == listing


@pytest.mark.parametrize("listing", [CRAIGSLIST, CARFAX, CARMAX], ids=["craigslist", "carfax", "carmax"])
def test_a_saved_listing_round_trips_with_its_search_and_saved_time(listing):
    text = json.dumps(saved_to_json(saved(listing)))

    assert saved_from_json(json.loads(text)) == saved(listing)


def test_a_saved_listing_without_a_search_round_trips():
    entry = SavedListing(CARMAX, None, SAVED)

    assert saved_from_json(json.loads(json.dumps(saved_to_json(entry)))) == entry


def test_a_snapshot_missing_newer_fields_takes_their_defaults():
    data = listing_to_json(CRAIGSLIST)
    del data["trim"], data["year"], data["posted"]

    assert listing_from_json(data) == Listing(
        CRAIGSLIST.id, CRAIGSLIST.source, CRAIGSLIST.title, CRAIGSLIST.price, CRAIGSLIST.mileage,
        CRAIGSLIST.url, CRAIGSLIST.images, CRAIGSLIST.owner_type, location="Oakland",
    )


def test_the_saved_search_is_the_place_and_car_of_a_search():
    search = Search("CA", "Sf Bay Area", "Honda", "Civic", (OwnerType.DEALER,), ())

    assert SavedSearch.of(search) == ORIGIN


def test_adding_puts_the_newest_first_and_keeps_the_list_given():
    first = add_saved([], CRAIGSLIST, ORIGIN, SAVED)
    both = add_saved(first, CARMAX, ORIGIN, datetime(2026, 10, 2, tzinfo=UTC))

    assert [entry.listing for entry in both] == [CARMAX, CRAIGSLIST]
    assert [entry.listing for entry in first] == [CRAIGSLIST]


def test_adding_a_saved_listing_again_changes_nothing():
    entries = [saved(CARFAX), saved(CRAIGSLIST)]

    assert add_saved(entries, CRAIGSLIST, None, datetime(2026, 10, 2, tzinfo=UTC)) == entries


def test_the_same_car_on_two_sources_is_two_favorites():
    other = Listing("carmax:1", Source.CARMAX, CARFAX.title, CARFAX.price, CARFAX.mileage, CARFAX.url, (), OwnerType.DEALER)

    entries = add_saved(add_saved([], CARFAX, ORIGIN, SAVED), other, ORIGIN, SAVED)

    assert saved_ids(entries) == frozenset({CARFAX.id, "carmax:1"})


def test_removing_drops_only_that_id():
    entries = [saved(CARMAX), saved(CARFAX), saved(CRAIGSLIST)]

    assert remove_saved(entries, CARFAX.id) == [saved(CARMAX), saved(CRAIGSLIST)]
    assert remove_saved(entries, "craigslist:0") == entries


def test_storage_round_trips_under_the_key_newest_first():
    storage: dict[str, object] = {}
    entries = add_saved(add_saved([], CRAIGSLIST, ORIGIN, SAVED), CARFAX, None, datetime(2026, 10, 2, tzinfo=UTC))

    write_saved(storage, FAVORITES_KEY, entries)

    assert list(storage) == [FAVORITES_KEY]
    assert read_saved(json.loads(json.dumps(storage)), FAVORITES_KEY) == entries


def test_nothing_stored_reads_as_no_favorites():
    assert read_saved({}, FAVORITES_KEY) == []


def test_an_unreadable_stored_entry_is_skipped():
    storage = {FAVORITES_KEY: [{"listing": {"id": "x"}}, saved_to_json(saved(CARMAX)), "junk"]}

    assert read_saved(storage, FAVORITES_KEY) == [saved(CARMAX)]


def test_the_toolbar_button_counts_the_favorites():
    assert button_text(0) == "★ Favorites (0)"
    assert button_text(3) == "★ Favorites (3)"
    assert "Save" in EMPTY_TEXT


def test_a_drawer_row_shows_photo_title_price_mileage_source_and_saved_date():
    row = favorite_row(saved(CARMAX))

    assert row.image == CARMAX.images[0]
    assert row.title == "2019 Honda Civic EX"
    assert row.price_mileage == "$19,998  |  41,000 mi"
    assert row.source.startswith("CarMax  ·  saved ")


def test_a_drawer_row_names_craigslist_by_owner_type_and_says_when_mileage_is_missing():
    assert favorite_row(saved(CRAIGSLIST)).source.startswith("Craigslist owner  ·  saved ")
    carfax_row = favorite_row(saved(CARFAX))
    assert carfax_row.image is None
    assert carfax_row.price_mileage == "$18,995  |  Mileage not listed"
