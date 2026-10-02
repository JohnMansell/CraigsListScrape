import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from craigslist.curve import NotEnoughData, PriceCurve
from craigslist import listings
from craigslist.listings import Listing, ListingSourceError, OwnerType, Source
from craigslist.search import Search, SearchError, run_live_search, run_search


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def empty_response() -> str:
    response = json.loads(fixture("owner_full.json"))
    response["data"]["items"] = []
    return json.dumps(response)


def test_run_search_returns_listings_and_a_curve_per_owner_type():
    responses = {
        OwnerType.OWNER: fixture("owner_full.json"),
        OwnerType.DEALER: fixture("dealer_full.json"),
    }

    def fetch(url: str) -> str:
        return responses[OwnerType.DEALER if "purveyor=dealer" in url else OwnerType.OWNER]

    result = run_search(Search("CA", "Orange County", "honda", "civic"), fetch)

    assert {listing.owner_type for listing in result.listings} == {OwnerType.OWNER, OwnerType.DEALER}
    assert set(result.curves) == {OwnerType.OWNER, OwnerType.DEALER}
    assert all(isinstance(curve, PriceCurve) for curve in result.curves.values())


def test_run_search_returns_empty_listings_and_not_enough_data_per_owner_type():
    empty = empty_response()

    result = run_search(Search("CA", "Orange County", "honda", "civic"), lambda url: empty)

    assert result.listings == []
    assert all(isinstance(curve, NotEnoughData) for curve in result.curves.values())


@pytest.mark.parametrize(
    ("search", "message"),
    [
        (Search("XX", "Orange County", "honda", "civic"), "unknown state 'XX'"),
        (Search("CA", "Nowhere", "honda", "civic"), "unknown city 'Nowhere' in state 'CA'"),
        (Search("CA", "Orange County", "not-a-make", "civic"), "unknown make 'not-a-make'"),
        (Search("CA", "Orange County", "honda", "not-a-model"), "unknown model 'not-a-model' for make 'honda'"),
    ],
)
def test_run_search_rejects_unknown_lookup_values(search, message):
    with pytest.raises(SearchError, match=message):
        run_search(search, lambda url: pytest.fail("lookup validation should run before fetching"))


def paged_fetch(responses: dict[str, str]):
    def fetch(url: str) -> str:
        query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        step = query["batch"].split("-")
        if urlsplit(url).path.endswith("/batch"):
            return responses[f"batch_{step[1]}"]
        return responses["owner_full" if step[1] == "0" else "owner_cache"]

    return fetch


@pytest.fixture
def paged_responses(monkeypatch) -> dict[str, str]:
    monkeypatch.setattr(listings, "FULL_PAGE_SIZE", 20)
    monkeypatch.setattr(listings, "BATCH_PAGE_SIZE", 20)
    return {
        "owner_full": fixture("owner_full.json"),
        "owner_cache": fixture("owner_cache.json"),
        "batch_0": fixture("owner_batch_0.json"),
        "batch_20": fixture("owner_batch_20.json"),
    }


OWNER_SEARCH = Search("CA", "Orange County", "honda", "civic", owner_types=(OwnerType.OWNER,), carfax=False)


def test_run_search_reports_each_batch_and_they_add_up_to_the_listings(paged_responses):
    batches: list[list[Listing]] = []

    result = run_search(OWNER_SEARCH, paged_fetch(paged_responses), on_batch=batches.append)

    assert len(batches) == 3
    assert [listing for batch in batches for listing in batch] == result.listings
    assert result.requests == 4


def test_run_search_keeps_the_listings_that_arrived_before_a_failure(paged_responses):
    calls = 0
    fetch = paged_fetch(paged_responses)

    def failing(url: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ListingSourceError("HTTP 500")
        return fetch(url)

    result = run_search(OWNER_SEARCH, failing)

    assert result.error is not None
    assert result.requests == 2
    assert len(result.listings) == 20
    assert isinstance(result.curves[OwnerType.OWNER], PriceCurve)


def test_run_search_stops_when_asked(paged_responses):
    urls: list[str] = []
    fetch = paged_fetch(paged_responses)

    def counting(url: str) -> str:
        urls.append(url)
        return fetch(url)

    result = run_search(OWNER_SEARCH, counting, should_stop=lambda: len(urls) >= 1)

    assert len(urls) == 1
    assert result.cancelled
    assert len(result.listings) == 20


def test_run_live_search_uses_the_given_fetcher():
    dealer_full = fixture("dealer_full.json")

    result = run_live_search(
        Search("CA", "Orange County", "honda", "civic", (OwnerType.DEALER,), carfax=False), lambda url: dealer_full
    )

    assert {listing.owner_type for listing in result.listings} == {OwnerType.DEALER}


# Carfax


def dual_fetch(craigslist_response: str, carfax_response: str):
    def fetch(url: str) -> str:
        return carfax_response if "carfax.com" in url else craigslist_response

    return fetch


BOTH_SEARCH = Search("CA", "Orange County", "honda", "civic", owner_types=(OwnerType.DEALER,))


def test_run_search_includes_carfax_listings_alongside_craigslist():
    result = run_search(BOTH_SEARCH, dual_fetch(fixture("dealer_full.json"), fixture("carfax_last_page.json")))

    assert {listing.source for listing in result.listings} == {Source.CRAIGSLIST, Source.CARFAX}
    assert sum(listing.source == Source.CARFAX for listing in result.listings) == 7
    assert all(listing.owner_type == OwnerType.DEALER for listing in result.listings if listing.source == Source.CARFAX)


def test_carfax_has_its_own_curve_separate_from_the_dealer_curve():
    result = run_search(BOTH_SEARCH, dual_fetch(fixture("dealer_full.json"), fixture("carfax_page_1.json")))

    assert isinstance(result.carfax_curve, PriceCurve)
    assert isinstance(result.curves[OwnerType.DEALER], PriceCurve)
    carfax_prices = {listing.price for listing in result.listings if listing.source == Source.CARFAX}
    dealer_prices = {listing.price for listing in result.listings if listing.source == Source.CRAIGSLIST}
    assert carfax_prices and dealer_prices and carfax_prices != dealer_prices


def test_a_car_in_both_sources_is_not_deduplicated():
    result = run_search(BOTH_SEARCH, dual_fetch(fixture("dealer_full.json"), fixture("carfax_last_page.json")))

    ids = [listing.id for listing in result.listings]
    assert len(ids) == len(set(ids))  # unique across Sources
    assert len(result.listings) == 19 + 7  # dealer_full has one no-price result, carfax_last_page has two


def test_a_carfax_failure_keeps_the_craigslist_listings():
    def fetch(url: str) -> str:
        if "carfax.com" in url:
            raise ListingSourceError("HTTP 500")
        return fixture("dealer_full.json")

    result = run_search(BOTH_SEARCH, fetch)

    assert isinstance(result.carfax_error, ListingSourceError)
    assert result.error is None
    assert all(listing.source == Source.CRAIGSLIST for listing in result.listings)
    assert len(result.listings) == 19


def test_a_craigslist_failure_keeps_the_carfax_listings():
    def fetch(url: str) -> str:
        if "carfax.com" in url:
            return fixture("carfax_last_page.json")
        raise ListingSourceError("HTTP 500")

    result = run_search(BOTH_SEARCH, fetch)

    assert isinstance(result.error, ListingSourceError)
    assert result.carfax_error is None
    assert all(listing.source == Source.CARFAX for listing in result.listings)
    assert len(result.listings) == 7


def test_should_stop_stops_both_sources():
    result = run_search(BOTH_SEARCH, dual_fetch(fixture("dealer_full.json"), fixture("carfax_last_page.json")), should_stop=lambda: True)

    assert result.cancelled
    assert result.listings == []
    assert result.requests == 0


def test_a_search_with_neither_owner_type_nor_carfax_is_rejected():
    with pytest.raises(SearchError, match="at least one"):
        run_search(Search("CA", "Orange County", "honda", "civic", owner_types=(), carfax=False), lambda url: "")


def test_carfax_alone_needs_no_owner_type():
    result = run_search(
        Search("CA", "Orange County", "honda", "civic", owner_types=(), carfax=True),
        lambda url: fixture("carfax_last_page.json"),
    )

    assert len(result.listings) == 7
    assert result.curves == {}
