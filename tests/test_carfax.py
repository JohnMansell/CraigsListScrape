import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from loguru import logger

from craigslist import carfax
from craigslist.carfax import Search, SearchResults, search_carfax
from craigslist.listings import ListingSourceError, OwnerType, Source
from craigslist.lookup import City

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_PAGE_SIZE = 20
"""The saved fixtures are trimmed to this many results; see tests/fixtures/refresh.py."""
SAN_FRANCISCO = City("Sf Bay Area", "https://sfbay.craigslist.org", "94103")


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class FakeFetcher:
    """Serves one fixture per requested page number, and records each URL."""

    def __init__(self, **by_page: dict) -> None:
        self.by_page = by_page
        self.urls: list[str] = []

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        page = parse_qs(urlsplit(url).query)["page"][0]
        return json.dumps(self.by_page[page])

    def queries(self) -> list[dict[str, str]]:
        return [{key: values[0] for key, values in parse_qs(urlsplit(url).query).items()} for url in self.urls]


@pytest.fixture
def small_pages(monkeypatch):
    monkeypatch.setattr(carfax, "PAGE_SIZE", FIXTURE_PAGE_SIZE)


@pytest.fixture
def log_messages():
    messages: list[str] = []
    handler_id = logger.add(lambda message: messages.append(message.record["message"]), level="DEBUG")
    yield messages
    logger.remove(handler_id)


# Parsing a page


def test_a_full_page_is_parsed_into_dealer_listings(small_pages):
    fetch = FakeFetcher(**{"1": fixture("carfax_last_page.json")})

    results = search_carfax(Search(SAN_FRANCISCO, "Honda", "Fit"), fetch)

    assert len(results.listings) == 9  # the saved last page is short, so paging stops there
    assert all(listing.owner_type == OwnerType.DEALER for listing in results.listings)
    assert all(listing.source == Source.CARFAX for listing in results.listings)
    assert all(listing.id.startswith("carfax:") for listing in results.listings)
    assert results.reported_total == fixture("carfax_last_page.json")["totalListingCount"]


def test_a_listing_carries_title_price_mileage_url_and_image():
    page = fixture("carfax_page_1.json")
    # The first listing in this fixture has no price; use the second, full one.
    item = page["listings"][1]

    listing = carfax._parse_item(item)

    assert listing is not None
    assert listing.title == f"{item['year']} {item['make']} {item['model']} {item['trim']}"
    assert listing.price == item["currentPrice"]
    assert listing.mileage == item["mileage"]
    assert listing.url == item["vdpUrl"]
    assert listing.images == tuple(item["images"]["large"])
    assert listing.location == f"{item['dealer']['city']}, {item['dealer']['state']}"
    assert listing.posted is not None and listing.posted.isoformat().startswith(item["firstSeen"])


def test_a_result_with_no_price_is_skipped_and_logged(log_messages):
    item = fixture("carfax_page_1.json")["listings"][0]
    assert "currentPrice" not in item

    assert carfax._parse_item(item) is None
    assert any("no price" in message for message in log_messages)


def test_a_result_with_no_mileage_gets_none():
    item = dict(fixture("carfax_page_1.json")["listings"][1])
    del item["mileage"]

    listing = carfax._parse_item(item)

    assert listing is not None and listing.mileage is None


# Paging


def test_search_pages_until_a_short_page(small_pages):
    fetch = FakeFetcher(
        **{
            "1": fixture("carfax_page_1.json"),
            "2": fixture("carfax_page_2.json"),
            "3": fixture("carfax_last_page.json"),
        }
    )

    results = search_carfax(Search(SAN_FRANCISCO, "Honda", "Civic"), fetch)

    assert len(fetch.urls) == 3
    expected = len(fixture("carfax_page_1.json")["listings"]) - 1  # one has no price
    expected += len(fixture("carfax_page_2.json")["listings"])
    expected += len(fixture("carfax_last_page.json")["listings"])
    assert len(results.listings) == expected
    assert results.reported_total == fixture("carfax_page_1.json")["totalListingCount"]


def test_a_search_with_no_results_returns_no_listings():
    fetch = FakeFetcher(**{"1": fixture("carfax_empty.json")})

    results = search_carfax(Search(SAN_FRANCISCO, "Honda", "Civic"), fetch)

    assert results.listings == []
    assert results.reported_total == 0
    assert len(fetch.urls) == 1


def test_batches_are_reported_in_request_order(small_pages):
    batches: list[list] = []
    fetch = FakeFetcher(
        **{"1": fixture("carfax_page_1.json"), "2": fixture("carfax_last_page.json")}
    )

    search_carfax(Search(SAN_FRANCISCO, "Honda", "Civic"), fetch, on_batch=batches.append)

    assert len(batches) == 2
    assert len(batches[0]) == FIXTURE_PAGE_SIZE - 1  # one listing has no price
    assert len(batches[1]) == 9


# Price bands


def test_a_band_still_full_at_the_page_cap_is_split_and_deduplicated(monkeypatch):
    monkeypatch.setattr(carfax, "PAGE_SIZE", 2)
    monkeypatch.setattr(carfax, "MAX_PAGE", 2)
    monkeypatch.setattr(carfax, "PRICE_CEILING", 4)

    def item(item_id: str, price: int) -> dict:
        return {
            "id": item_id, "vdpUrl": f"https://www.carfax.com/vehicle/{item_id}",
            "year": 2020, "make": "Honda", "model": "Civic", "currentPrice": price,
        }

    def fetch(url: str) -> str:
        query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        page = int(query["page"])
        price_min, price_max = int(query.get("priceMin", 0)), int(query.get("priceMax", 4))
        if price_min == 0 and price_max == 4:
            # The unsplit band: always full, two pages, forcing a split.
            return json.dumps({
                "totalListingCount": 5,
                "listings": [item(f"full-{price_min}-{page}-{n}", 1) for n in range(2)],
            })
        # A split band: one short page of listings unique to that band.
        if page > 1:
            return json.dumps({"totalListingCount": 0, "listings": []})
        return json.dumps({
            "totalListingCount": 1,
            "listings": [item(f"band-{price_min}-{price_max}", (price_min + price_max) // 2)],
        })

    results = search_carfax(Search(SAN_FRANCISCO, "Honda", "Civic"), fetch)

    ids = [listing.id for listing in results.listings]
    assert len(ids) == len(set(ids))  # deduplicated
    assert any("band-" in listing_id for listing_id in ids)  # the split bands were actually paged
    assert results.reported_total == 5  # taken from the first, unsplit band


# Failure and cancelling


def test_a_failed_request_returns_listings_so_far_and_the_error(small_pages):
    def fetch(url: str) -> str:
        raise ListingSourceError("HTTP 429")

    results = search_carfax(Search(SAN_FRANCISCO, "Honda", "Civic"), fetch)

    assert results.listings == []
    assert isinstance(results.error, ListingSourceError)
    assert not results.cancelled


def test_cancelling_makes_no_further_requests(small_pages):
    fetch = FakeFetcher(**{"1": fixture("carfax_page_1.json"), "2": fixture("carfax_page_2.json")})

    results = search_carfax(
        Search(SAN_FRANCISCO, "Honda", "Civic"), fetch, should_stop=lambda: len(fetch.urls) >= 1
    )

    assert len(fetch.urls) == 1
    assert results.cancelled
    assert len(results.listings) == FIXTURE_PAGE_SIZE - 1  # page 1's Listings, one skipped for no price


def test_cancelling_before_the_first_request_makes_none():
    def fetch(url: str) -> str:
        raise AssertionError("should not fetch when already stopped")

    results = search_carfax(Search(SAN_FRANCISCO, "Honda", "Civic"), fetch, should_stop=lambda: True)

    assert results.cancelled
    assert results.listings == []


# Make/model with no Carfax name


def test_a_model_with_no_carfax_name_is_skipped_and_logged(log_messages):
    def fetch(url: str) -> str:
        raise AssertionError("should not fetch when the model has no Carfax name")

    results = search_carfax(Search(SAN_FRANCISCO, "Porsche", "718"), fetch)

    assert results == SearchResults([])
    assert any("no Carfax name" in message for message in log_messages)


def test_a_make_with_no_model_searches_without_a_model_filter(small_pages):
    fetch = FakeFetcher(**{"1": fixture("carfax_last_page.json")})

    search_carfax(Search(SAN_FRANCISCO, "Honda"), fetch)

    assert "model" not in fetch.queries()[0]
    assert fetch.queries()[0]["make"] == "Honda"


def test_radius_is_fixed_and_zip_comes_from_the_city(small_pages):
    fetch = FakeFetcher(**{"1": fixture("carfax_last_page.json")})

    search_carfax(Search(SAN_FRANCISCO, "Honda", "Fit"), fetch)

    query = fetch.queries()[0]
    assert query["zip"] == "94103"
    assert query["radius"] == str(carfax.RADIUS_MILES)
