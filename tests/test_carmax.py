import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from loguru import logger

from craigslist import carmax
from craigslist.carmax import HttpFetcher, Search, SearchResults, search_carmax
from craigslist.listings import ListingSourceError, OwnerType, Source
from craigslist.lookup import City

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_PAGE_SIZE = 20
"""The saved fixtures are trimmed to this many results; see tests/fixtures/refresh.py."""
SAN_FRANCISCO = City("Sf Bay Area", "https://sfbay.craigslist.org", "94103")
CIVIC = Search(SAN_FRANCISCO, "Honda", "Civic")


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class FakeFetcher:
    """Serves one fixture per requested `skip`, and records each URL."""

    def __init__(self, **by_skip: dict) -> None:
        self.by_skip = by_skip
        self.urls: list[str] = []

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        return json.dumps(self.by_skip[parse_qs(urlsplit(url).query)["skip"][0]])

    def queries(self) -> list[dict[str, str]]:
        return [{key: values[0] for key, values in parse_qs(urlsplit(url).query).items()} for url in self.urls]


def civic_pages() -> FakeFetcher:
    return FakeFetcher(
        **{"0": fixture("carmax_page_1.json"), "20": fixture("carmax_page_2.json"), "40": fixture("carmax_last_page.json")}
    )


@pytest.fixture
def small_pages(monkeypatch):
    monkeypatch.setattr(carmax, "PAGE_SIZE", FIXTURE_PAGE_SIZE)


@pytest.fixture
def log_messages():
    messages: list[str] = []
    handler_id = logger.add(lambda message: messages.append(message.record["message"]), level="DEBUG")
    yield messages
    logger.remove(handler_id)


# Parsing an item


def test_a_listing_carries_the_preview_fields():
    item = fixture("carmax_page_1.json")["items"][1]

    listing = carmax._parse_item(item)

    assert listing is not None
    assert listing.id == f"carmax:{item['stockNumber']}"
    assert listing.source == Source.CARMAX
    assert listing.owner_type == OwnerType.DEALER
    assert listing.title == f"{item['year']} {item['make']} {item['model']} {item['trim']}"
    assert listing.price == 17998
    assert listing.mileage == item["mileage"]
    assert listing.url == f"https://www.carmax.com/car/{item['stockNumber']}"
    assert listing.images == (item["heroImageUrl"],)
    assert listing.dealer == item["storeName"]
    assert listing.location == f"{item['storeCity']}, {item['stateAbbreviation']}"
    assert listing.posted is not None and listing.posted.isoformat().startswith("2026-09-10T03:14:15")
    assert listing.price_dropped is False
    assert listing.one_owner is True  # highlights has singleOwner
    assert listing.no_accidents is None
    assert listing.year == item["year"]
    assert listing.trim == item["trim"]


def test_an_empty_trim_is_unknown():
    item = dict(fixture("carmax_page_1.json")["items"][1], trim="")

    listing = carmax._parse_item(item)

    assert listing is not None and listing.trim is None


def test_one_owner_is_none_never_false_without_single_owner():
    item = dict(fixture("carmax_page_1.json")["items"][1], highlights=["fuelEfficient"])

    listing = carmax._parse_item(item)

    assert listing is not None and listing.one_owner is None


def test_a_missing_sale_date_gives_none():
    item = dict(fixture("carmax_page_1.json")["items"][1], lastMadeSaleableDate=None)

    listing = carmax._parse_item(item)

    assert listing is not None and listing.posted is None


def test_a_result_with_no_price_is_skipped_and_logged(log_messages):
    item = fixture("carmax_page_1.json")["items"][0]
    assert "basePrice" not in item

    assert carmax._parse_item(item) is None
    assert any("no price" in message for message in log_messages)


def test_a_result_with_no_mileage_gets_none():
    item = dict(fixture("carmax_page_1.json")["items"][1])
    del item["mileage"]

    listing = carmax._parse_item(item)

    assert listing is not None and listing.mileage is None


# Paging


def test_search_pages_until_a_short_page(small_pages):
    fetch = civic_pages()

    results = search_carmax(CIVIC, fetch)

    assert [query["skip"] for query in fetch.queries()] == ["0", "20", "40"]
    expected = sum(len(fixture(f"carmax_{name}.json")["items"]) for name in ("page_1", "page_2", "last_page")) - 1
    assert len(results.listings) == expected  # one has no price
    assert results.reported_total == 51
    assert results.requests == 3
    assert results.error is None
    assert all(listing.owner_type == OwnerType.DEALER for listing in results.listings)


def test_a_search_with_no_results_returns_no_listings(small_pages):
    empty = fixture("carmax_empty.json")
    empty["selectedFacets"][1]["value"] = "clarity"  # the lookup CSV has no Prelude; Clarity stands in
    fetch = FakeFetcher(**{"0": empty})

    results = search_carmax(Search(SAN_FRANCISCO, "Honda", "Clarity"), fetch)

    assert results.listings == []
    assert results.reported_total == 0
    assert results.error is None
    assert len(fetch.urls) == 1


def test_batches_are_reported_in_request_order(small_pages):
    batches: list[list] = []
    fetch = FakeFetcher(**{"0": fixture("carmax_page_1.json"), "20": fixture("carmax_last_page.json")})

    search_carmax(CIVIC, fetch, on_batch=batches.append)

    assert [len(batch) for batch in batches] == [FIXTURE_PAGE_SIZE - 1, 11]


def test_a_repeated_listing_is_reported_once(small_pages):
    fetch = FakeFetcher(**{"0": fixture("carmax_page_1.json"), "20": fixture("carmax_page_1.json")})
    fetch.by_skip["20"] = dict(fixture("carmax_page_1.json"), items=fixture("carmax_page_1.json")["items"][:5])

    results = search_carmax(CIVIC, fetch)

    ids = [listing.id for listing in results.listings]
    assert len(ids) == len(set(ids)) == FIXTURE_PAGE_SIZE - 1


def test_a_search_still_full_at_the_page_cap_stops_and_warns(small_pages, monkeypatch, log_messages):
    monkeypatch.setattr(carmax, "MAX_PAGES", 2)
    full = fixture("carmax_page_1.json")
    fetch = FakeFetcher(**{"0": full, "20": fixture("carmax_page_2.json"), "40": full})

    results = search_carmax(CIVIC, fetch)

    assert len(fetch.urls) == 2  # never asks for the third page
    assert len(results.listings) == 2 * FIXTURE_PAGE_SIZE - 1
    assert results.error is None
    assert any("more may exist" in message for message in log_messages)


def test_the_real_page_cap_is_ten_pages_of_a_hundred():
    assert (carmax.PAGE_SIZE, carmax.MAX_PAGES) == (100, 10)


# URL


def test_the_url_keeps_raw_slashes_in_uri_and_carries_the_decided_parameters(small_pages):
    fetch = FakeFetcher(**{"0": fixture("carmax_last_page.json")})

    search_carmax(CIVIC, fetch)

    url = fetch.urls[0]
    assert "uri=/cars/honda/civic&" in url
    assert "%2F" not in url
    query = fetch.queries()[0]
    assert query["zipCode"] == "94103"
    assert query["radius"] == "radius-50"
    assert query["shipping"] == "0"
    assert query["take"] == str(FIXTURE_PAGE_SIZE)


def test_a_make_with_no_model_searches_the_make_page(small_pages):
    page = dict(fixture("carmax_last_page.json"), selectedFacets=[{"category": "make", "value": "honda"}])
    fetch = FakeFetcher(**{"0": page})

    results = search_carmax(Search(SAN_FRANCISCO, "Honda"), fetch)

    assert fetch.queries()[0]["uri"] == "/cars/honda"
    assert results.listings


# Slugs CarMax does not know


def test_a_model_with_no_carmax_name_is_skipped_and_logged(log_messages):
    def fetch(url: str) -> str:
        raise AssertionError("should not fetch when the model has no CarMax name")

    results = search_carmax(Search(SAN_FRANCISCO, "Mercedes-Benz", "GLC"), fetch)

    assert results == SearchResults([])
    assert any("no CarMax name" in message for message in log_messages)


def test_an_ignored_model_slug_is_skipped_with_a_warning_and_no_listings(small_pages, log_messages):
    fetch = FakeFetcher(**{"0": fixture("carmax_unknown_model.json")})  # all Hondas, selectedFacets has no model
    batches: list[list] = []

    results = search_carmax(CIVIC, fetch, on_batch=batches.append)

    assert results.listings == []
    assert results.error is None
    assert batches == []
    assert len(fetch.urls) == 1  # no paging through the broader results
    assert any("ignored" in message for message in log_messages)


def test_a_series_slug_counts_as_the_model(small_pages):
    page = dict(fixture("carmax_last_page.json"), selectedFacets=[
        {"category": "make", "value": "bmw"}, {"category": "series", "value": "3-series"},
    ])
    fetch = FakeFetcher(**{"0": page})

    results = search_carmax(Search(SAN_FRANCISCO, "BMW", "3"), fetch)

    assert fetch.queries()[0]["uri"] == "/cars/bmw/3-series"
    assert results.listings


# Failure and cancelling


def test_a_failed_request_returns_listings_so_far_and_the_error(small_pages):
    pages = {"0": fixture("carmax_page_1.json")}

    def fetch(url: str) -> str:
        if parse_qs(urlsplit(url).query)["skip"][0] != "0":
            raise ListingSourceError("HTTP 403")
        return json.dumps(pages["0"])

    results = search_carmax(CIVIC, fetch)

    assert len(results.listings) == FIXTURE_PAGE_SIZE - 1
    assert isinstance(results.error, ListingSourceError)
    assert not results.cancelled


def test_a_response_that_is_not_json_is_an_error():
    results = search_carmax(CIVIC, lambda url: "<HTML>Access Denied</HTML>")

    assert isinstance(results.error, ListingSourceError)
    assert results.listings == []


def test_cancelling_makes_no_further_requests(small_pages):
    fetch = civic_pages()

    results = search_carmax(CIVIC, fetch, should_stop=lambda: len(fetch.urls) >= 1)

    assert len(fetch.urls) == 1
    assert results.cancelled
    assert len(results.listings) == FIXTURE_PAGE_SIZE - 1


# The live fetcher, over a mock transport


class Site:
    """A mock CarMax: records requests and answers each with the next status, 200 when out."""

    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.statuses.pop(0) if self.statuses else 200
        return httpx.Response(status, text="{}" if status == 200 else "<HTML>Access Denied</HTML>")


def fetcher(site: Site, sleeps: list[float] | None = None) -> HttpFetcher:
    now = [0.0]
    slept = sleeps if sleeps is not None else []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    return HttpFetcher(httpx.Client(transport=httpx.MockTransport(site)), clock=lambda: now[0], sleep=sleep)


def test_the_fetcher_warms_up_once_on_the_search_page_with_a_referer():
    site = Site()
    fetch = fetcher(site)

    fetch(carmax.search_url("94103", "/cars/honda/civic", 0))
    fetch(carmax.search_url("94103", "/cars/honda/civic", 100))

    urls = [str(request.url) for request in site.requests]
    assert urls[0] == "https://www.carmax.com/cars/honda/civic"
    assert len(urls) == 3  # one warm-up, two API requests
    assert all(request.headers["Referer"] == "https://www.carmax.com/cars/honda/civic" for request in site.requests)


def test_a_403_after_the_warm_up_is_not_retried():
    site = Site(403, 403)  # the warm-up, then the API request
    fetch = fetcher(site)

    results = search_carmax(CIVIC, fetch)

    assert len(site.requests) == 2  # no third request
    assert isinstance(results.error, ListingSourceError)
    assert "403" in str(results.error)
    assert results.listings == []


def test_a_403_on_the_warm_up_alone_is_ignored():
    site = Site(403, 200)
    fetch = fetcher(site)

    assert fetch(carmax.search_url("94103", "/cars/honda/civic", 0)) == "{}"


def test_requests_are_at_least_a_second_apart():
    site = Site()
    sleeps: list[float] = []
    fetch = fetcher(site, sleeps)

    fetch(carmax.search_url("94103", "/cars/honda/civic", 0))
    fetch(carmax.search_url("94103", "/cars/honda/civic", 100))

    assert sleeps == [1.0, 1.0]  # warm-up to request, request to request


def test_a_network_error_becomes_a_listing_source_error():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    fetch = HttpFetcher(httpx.Client(transport=httpx.MockTransport(refuse)))

    with pytest.raises(ListingSourceError):
        fetch(carmax.search_url("94103", "/cars/honda/civic", 0))
