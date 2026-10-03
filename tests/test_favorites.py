import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from craigslist.favorites import (
    EMPTY_TEXT,
    FAVORITES_KEY,
    HIDDEN_EMPTY_TEXT,
    HIDDEN_KEY,
    SavedListing,
    SavedSearch,
    add_saved,
    button_text,
    favorite_row,
    hidden_tab_text,
    listing_from_json,
    listing_to_json,
    move_saved,
    price_text,
    read_saved,
    remove_saved,
    saved_from_json,
    saved_ids,
    saved_to_json,
    update_from_search,
    write_saved,
)
from craigslist.listings import Listing, ListingSourceError, OwnerType, Source
from craigslist.search import Search, SearchResult
from craigslist.sources import SOURCES

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


# --- Updates From Later Searches

LATER = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
COVERING = Search("CA", "Sf Bay Area", "Honda", "Civic")


def result_of(*listings: Listing, **fields) -> SearchResult:
    return SearchResult(list(listings), {}, {}, **fields)


def test_a_returned_favorite_takes_the_new_snapshot_and_keeps_its_first_saved_price():
    cheaper = replace(CARMAX, price=17_500, mileage=41_200, images=("https://img2.carmax.com/new.jpg",))
    entries = update_from_search([saved(CARMAX)], COVERING, result_of(cheaper), LATER)
    again = update_from_search(entries, COVERING, result_of(replace(cheaper, price=16_900)), LATER)

    assert entries == [SavedListing(cheaper, ORIGIN, SAVED, saved_price=19_998)]
    assert again[0].listing.price == 16_900
    assert again[0].saved_price == 19_998


def test_a_new_favorite_keeps_its_own_price_as_the_first_saved_price():
    assert add_saved([], CARMAX, ORIGIN, SAVED)[0].saved_price == 19_998
    assert saved(CARMAX).saved_price == 19_998


def test_a_covering_complete_search_without_the_favorite_marks_it_missing_with_the_date():
    entries = [saved(CRAIGSLIST), saved(CARFAX), saved(CARMAX)]

    updated = update_from_search(entries, COVERING, result_of(), LATER)

    assert [entry.missing_since for entry in updated] == [LATER, LATER, LATER]
    assert [entry.listing for entry in updated] == [CRAIGSLIST, CARFAX, CARMAX]


def test_a_search_returning_a_missing_favorite_clears_the_mark():
    missing = update_from_search([saved(CARMAX)], COVERING, result_of(), LATER)

    assert update_from_search(missing, COVERING, result_of(CARMAX), LATER) == [saved(CARMAX)]


@pytest.mark.parametrize(
    "result",
    [
        result_of(cancelled=True),
        result_of(error=ListingSourceError("Craigslist down")),
        result_of(source_errors={Source.CARFAX: ListingSourceError("Carfax down")}),
    ],
    ids=["cancelled", "craigslist-error", "source-error"],
)
def test_a_cancelled_or_failed_search_marks_nothing_missing(result):
    entries = [saved(CRAIGSLIST) if result.error else saved(CARFAX)]

    assert update_from_search(entries, COVERING, result, LATER) == entries


def test_a_failed_source_still_lets_the_other_sources_mark_their_favorites():
    entries = [saved(CARFAX), saved(CARMAX)]
    result = result_of(source_errors={Source.CARFAX: ListingSourceError("Carfax down")})

    assert [entry.missing_since for entry in update_from_search(entries, COVERING, result, LATER)] == [None, LATER]


@pytest.mark.parametrize(
    "search, entry",
    [
        (Search("CA", "Los Angeles", "Honda", "Civic"), saved(CARMAX)),
        (Search("CA", "Sf Bay Area", "Honda", "Accord"), saved(CRAIGSLIST)),
        (Search("CA", "Sf Bay Area", "Honda", "Civic", (OwnerType.OWNER, OwnerType.DEALER), (Source.CARFAX,)), saved(CARMAX)),
        (Search("CA", "Sf Bay Area", "Honda", "Civic", (OwnerType.DEALER,), tuple(SOURCES)), saved(CRAIGSLIST)),
    ],
    ids=["other-city", "other-model", "source-not-fetched", "owner-type-not-fetched"],
)
def test_a_search_not_covering_the_favorite_marks_nothing(search, entry):
    assert update_from_search([entry], search, result_of(), LATER) == [entry]


def test_a_favorite_saved_without_a_search_is_never_marked_missing():
    entries = [SavedListing(CARMAX, None, SAVED)]

    assert update_from_search(entries, COVERING, result_of(), LATER) == entries


def test_a_missing_mark_and_first_saved_price_round_trip_through_json():
    entry = SavedListing(replace(CARMAX, price=17_500), ORIGIN, SAVED, saved_price=19_998, missing_since=LATER)

    assert saved_from_json(json.loads(json.dumps(saved_to_json(entry)))) == entry


def test_an_entry_stored_before_updates_existed_loads_at_its_current_price_and_not_missing():
    data = saved_to_json(saved(CARMAX))
    del data["saved_price"], data["missing_since"]

    entry = saved_from_json(data)

    assert entry.saved_price == CARMAX.price
    assert entry.missing_since is None


def test_the_price_text_shows_the_change_since_saving():
    assert price_text(12_500, 13_900) == "$12,500, was $13,900 when saved"
    assert price_text(12_500, 12_500) == "$12,500"


def test_a_drawer_row_shows_the_price_change_and_the_missing_mark():
    entry = SavedListing(replace(CARMAX, price=17_500), ORIGIN, SAVED, saved_price=19_998, missing_since=LATER)

    row = favorite_row(entry)

    assert row.price_mileage == "$17,500, was $19,998 when saved  |  41,000 mi"
    assert row.missing == f"Not in latest Search ({LATER.astimezone():%Y-%m-%d})"
    assert favorite_row(saved(CARMAX)).missing is None


# --- Hidden Listings


def test_hidden_listings_are_kept_under_their_own_key_in_the_same_json():
    storage: dict = {}

    write_saved(storage, HIDDEN_KEY, [saved(CARMAX)])

    assert HIDDEN_KEY != FAVORITES_KEY and FAVORITES_KEY not in storage
    assert read_saved(storage, HIDDEN_KEY) == [saved(CARMAX)]
    assert storage[HIDDEN_KEY] == [saved_to_json(saved(CARMAX))]


def test_hiding_a_favorite_removes_it_from_favorites_and_keeps_its_origin():
    favorites = [saved(CARMAX), saved(CARFAX)]

    favorites, hidden = move_saved(favorites, [], CARMAX, None, LATER)

    assert saved_ids(favorites) == {CARFAX.id}
    assert hidden == [SavedListing(CARMAX, ORIGIN, LATER)]


def test_saving_a_hidden_car_unhides_it_and_the_given_origin_wins():
    elsewhere = SavedSearch("CA", "Orange County", "Honda", "Civic")
    hidden = [saved(CRAIGSLIST), saved(CARMAX)]

    hidden, favorites = move_saved(hidden, [saved(CARFAX)], CRAIGSLIST, elsewhere, LATER)

    assert saved_ids(hidden) == {CARMAX.id}
    assert favorites[0] == SavedListing(CRAIGSLIST, elsewhere, LATER)
    assert saved_ids(favorites) == {CRAIGSLIST.id, CARFAX.id}


def test_a_car_is_never_both_a_favorite_and_hidden():
    favorites: list[SavedListing] = []
    hidden: list[SavedListing] = []
    for step in range(6):
        if step % 2:
            favorites, hidden = move_saved(favorites, hidden, CARMAX, ORIGIN, SAVED)
        else:
            hidden, favorites = move_saved(hidden, favorites, CARMAX, ORIGIN, SAVED)
        assert not saved_ids(favorites) & saved_ids(hidden)
        assert saved_ids(favorites) | saved_ids(hidden) == {CARMAX.id}


def test_a_hidden_row_says_when_it_was_hidden_and_the_tab_counts_them():
    assert favorite_row(saved(CARMAX), "hidden").source.startswith("CarMax  ·  hidden ")
    assert hidden_tab_text(0) == "Hidden (0)" and hidden_tab_text(3) == "Hidden (3)"
    assert "Hide" in HIDDEN_EMPTY_TEXT
