from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from loguru import logger

from craigslist import listings
from craigslist.listings import (
    HttpFetcher,
    Listing,
    ListingSourceError,
    OwnerType,
    Search,
    image_url,
    parse_batch,
    parse_full,
    search_listings,
)
from craigslist.lookup import City

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_PAGE_SIZE = 20
"""The fixtures are trimmed to this many results; see tests/fixtures/refresh.py."""
ORANGE_COUNTY = City("Orange County", "https://orangecounty.craigslist.org")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class FakeFetcher:
    """Serves saved responses by owner type and request step, and records each URL."""

    def __init__(self, **responses: str) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        parts = urlsplit(url)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        step = query["batch"].split("-")
        if parts.path.endswith("/batch"):
            key = f"batch_{step[1]}"
        elif step[1] == "0":
            key = f"{query['purveyor']}_full"
        else:
            key = f"{query['purveyor']}_cache"
        return self.responses[key]

    def queries(self) -> list[dict[str, str]]:
        return [{key: values[0] for key, values in parse_qs(urlsplit(url).query).items()} for url in self.urls]


def paged_owner_fetcher(**overrides: str) -> FakeFetcher:
    responses = {
        "owner_full": fixture("owner_full.json"),
        "owner_cache": fixture("owner_cache.json"),
        "batch_0": fixture("owner_batch_0.json"),
        "batch_20": fixture("owner_batch_20.json"),
    }
    return FakeFetcher(**{**responses, **overrides})


@pytest.fixture
def small_pages(monkeypatch):
    """Page sizes matching the trimmed fixtures, so they page like a large search."""
    monkeypatch.setattr(listings, "FULL_PAGE_SIZE", FIXTURE_PAGE_SIZE)
    monkeypatch.setattr(listings, "BATCH_PAGE_SIZE", FIXTURE_PAGE_SIZE)


@pytest.fixture
def log_messages():
    messages: list[str] = []
    handler_id = logger.add(lambda message: messages.append(message.record["message"]), level="DEBUG")
    yield messages
    logger.remove(handler_id)


def by_post_id(found: list[Listing]) -> dict[int, Listing]:
    return {listing.post_id: listing for listing in found}


# Parsing


def test_parses_a_full_response_into_listings():
    page = parse_full(fixture("owner_full.json"), OwnerType.OWNER)

    assert len(page.listings) == 20
    assert page.reported_total == 1508
    assert page.listings[0] == Listing(
        post_id=7968808449,
        title="2015 MERCEDES BENZ C300 FULLY LOADED VERY CLEAN!!!",
        price=7500,
        mileage=140000,
        url="https://www.craigslist.org/view/d/laguna-niguel-2015-mercedes-benz-c300/rbFpehbubddhXXYr61UQG5",
        image_codes=page.listings[0].image_codes,
        owner_type=OwnerType.OWNER,
    )
    assert image_url(page.listings[0].image_codes[0]) == (
        "https://images.craigslist.org/00h0h_4R4y4ghJzOC_0CI0t2_600x450.jpg"
    )


def test_parses_a_batch_response_into_listings():
    page = parse_batch(fixture("owner_batch_0.json"), OwnerType.OWNER)

    assert page.result_count == 20
    assert len(page.listings) == 18  # two have no price
    corvette = by_post_id(page.listings)[7968774249]
    assert corvette.title == "2004 Chevy Corvette Convertible"
    assert corvette.price == 10900
    assert corvette.mileage == 75000
    assert corvette.url == "https://www.craigslist.org/view/d/westminster-2004-chevy-corvette/f6vnEnsiPRzJzzY9C6CtsJ"
    assert image_url(corvette.image_codes[0]) == "https://images.craigslist.org/01414_4krbn3IWsj9_0wU0oG_600x450.jpg"
    assert corvette.owner_type == OwnerType.OWNER


def test_full_result_with_extra_integer_after_the_image_suffix_is_read():
    rdx = by_post_id(parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings)[7966353423 + 2386698]

    assert rdx.title == "2014 Acura RDX w/Tech Package"
    assert rdx.price == 5000
    assert rdx.mileage == 199400
    assert rdx.image_codes[0] == "00808_gPzpE2Dr7ep_0CI0t2"


def test_result_with_no_photos_is_kept_with_no_image_codes():
    full = by_post_id(parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings)
    batch = by_post_id(parse_batch(fixture("owner_batch_0.json"), OwnerType.OWNER).listings)

    assert full[7966353423 + 2369301].image_codes == ()
    assert batch[7954482646 + 14240078].image_codes == ()


def test_result_with_no_mileage_is_kept_with_unknown_mileage():
    civic = by_post_id(parse_batch(fixture("owner_batch_0.json"), OwnerType.OWNER).listings)[7954482646 + 9675779]

    assert civic.title == "2017 Honda Civic"
    assert civic.mileage is None


def test_result_with_no_price_is_skipped_and_logged(log_messages):
    page = parse_batch(fixture("owner_batch_0.json"), OwnerType.OWNER)

    assert 7954482646 + 12735611 not in by_post_id(page.listings)
    assert any("no price" in message and "Chevrolet Sonic" in message for message in log_messages)


def test_duplicate_image_codes_are_collapsed_in_order():
    pilot = by_post_id(parse_batch(fixture("owner_batch_0.json"), OwnerType.OWNER).listings)[7968471033]

    # The fixture lists 00G0G_h8GaX6AVHXa_0CI0t2 twice in a row, at positions 11 and 12.
    assert len(pilot.image_codes) == 18
    assert pilot.image_codes[9:12] == (
        "00V0V_iohoXTev5ow_0CI0t2",
        "00G0G_h8GaX6AVHXa_0CI0t2",
        "00909_8JEMaXX4qIx_0CI0t2",
    )


def test_response_missing_items_raises_an_error_naming_the_api():
    with pytest.raises(ListingSourceError, match="Craigslist search API.*items"):
        parse_full('{"data": {"totalResultCount": 3, "cacheTs": 1, "decode": {"minPostingId": 1}}}', OwnerType.OWNER)


def test_unparseable_response_raises_an_error_naming_the_api():
    with pytest.raises(ListingSourceError, match="Craigslist search API"):
        parse_full("<html>Service unavailable</html>", OwnerType.OWNER)


def test_full_result_from_the_wrong_owner_type_raises():
    with pytest.raises(ListingSourceError, match="asked for owner listings, got dealer listings"):
        parse_full(fixture("dealer_full.json"), OwnerType.OWNER)


def test_full_result_with_an_unknown_purveyor_code_is_skipped_and_logged(log_messages):
    text = fixture("owner_full.json").replace("\n    145,\n", "\n    999,\n", 1)

    page = parse_full(text, OwnerType.OWNER)

    assert len(page.listings) == 19
    assert any("unknown purveyor code" in message for message in log_messages)


# Searching


def test_owner_and_dealer_searches_send_their_purveyor_and_tag_their_listings():
    fetch = FakeFetcher(owner_full=fixture("owner_full.json"), dealer_full=fixture("dealer_full.json"))
    search = Search(ORANGE_COUNTY, "honda", "civic", owner_types=(OwnerType.OWNER, OwnerType.DEALER))

    results = search_listings(search, fetch)

    assert [query["purveyor"] for query in fetch.queries()] == ["owner", "dealer"]
    assert all(query["searchPath"] == "area/orangecounty" for query in fetch.queries())
    assert all(query["auto_make_model"] == "honda civic" for query in fetch.queries())
    owner_types = [listing.owner_type for listing in results.listings]
    assert owner_types == [OwnerType.OWNER] * 20 + [OwnerType.DEALER] * 19  # one dealer result has no price
    assert results.reported_totals == {OwnerType.OWNER: 1508, OwnerType.DEALER: 15}


def test_search_with_no_make_sends_no_make_model_filter():
    fetch = FakeFetcher(owner_full=fixture("owner_full.json"))

    search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), fetch)

    assert "auto_make_model" not in fetch.queries()[0]


def test_search_needing_more_than_one_page_returns_every_result(small_pages):
    fetch = paged_owner_fetcher()

    results = search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), fetch)

    expected = (
        by_post_id(parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings)
        | by_post_id(parse_batch(fixture("owner_batch_0.json"), OwnerType.OWNER).listings)
        | by_post_id(parse_batch(fixture("owner_batch_20.json"), OwnerType.OWNER).listings)
    )
    assert len(expected) > FIXTURE_PAGE_SIZE
    assert sorted(listing.post_id for listing in results.listings) == sorted(expected)


def test_paging_stops_on_a_short_batch_not_on_the_reported_total(small_pages, log_messages):
    fetch = paged_owner_fetcher()

    results = search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), fetch)

    # The API reports 1508, but the batch at offset 20 is short, so paging ends there.
    assert results.reported_totals[OwnerType.OWNER] == 1508
    assert [query["batch"].split("-")[1] for query in fetch.queries()] == ["0", "1789758620", "0", "20"]
    assert any("got 27 results, API reported 1508" in message for message in log_messages)


def test_paging_continues_past_a_reported_total_below_one_page(small_pages, log_messages):
    # Like a dealer search, whose total counts only local results.
    full = fixture("owner_full.json").replace('"totalResultCount": 1508', '"totalResultCount": 5')
    fetch = paged_owner_fetcher(owner_full=full)

    results = search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), fetch)

    assert sum(urlsplit(url).path.endswith("/batch") for url in fetch.urls) == 2
    assert len(results.listings) == len(
        search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), paged_owner_fetcher()).listings
    )
    assert any("got 27 results, API reported 5" in message for message in log_messages)


def test_results_beyond_the_reported_total_are_all_returned_and_logged(log_messages):
    fetch = FakeFetcher(dealer_full=fixture("dealer_full.json"))

    results = search_listings(Search(ORANGE_COUNTY, "honda", "civic", owner_types=(OwnerType.DEALER,)), fetch)

    assert results.reported_totals[OwnerType.DEALER] == 15
    assert len(results.listings) == 19  # one of the 20 results has no price
    assert any("got 20 results, API reported 15" in message for message in log_messages)


def test_batches_repeating_the_first_page_give_no_duplicate_listings(small_pages):
    results = search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), paged_owner_fetcher())
    post_ids = [listing.post_id for listing in results.listings]

    assert len(post_ids) == len(set(post_ids))


def test_full_first_page_with_no_cache_id_ends_the_search(small_pages):
    cache = fixture("owner_cache.json").replace('"cacheId"', '"noCacheId"')
    fetch = paged_owner_fetcher(owner_cache=cache)

    results = search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), fetch)

    assert len(results.listings) == 20
    assert not any(urlsplit(url).path.endswith("/batch") for url in fetch.urls)


def test_paging_stops_at_the_batch_request_limit(small_pages, monkeypatch, log_messages):
    monkeypatch.setattr(listings, "MAX_BATCH_REQUESTS", 1)
    fetch = paged_owner_fetcher()

    search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), fetch)

    assert sum(urlsplit(url).path.endswith("/batch") for url in fetch.urls) == 1
    assert any("stopped after 1 batch requests" in message for message in log_messages)


# Fetching


def test_http_fetcher_sends_a_user_agent_and_returns_the_body():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="body")

    fetch = HttpFetcher(httpx.Client(transport=httpx.MockTransport(handler)))

    assert fetch("https://sapi.craigslist.org/x") == "body"
    assert "Mozilla" in seen[0].headers["User-Agent"]


def test_http_fetcher_raises_an_error_naming_the_api_on_a_non_200_status():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(400, text="bad max_posting_ts")))

    with pytest.raises(ListingSourceError, match="Craigslist search API: HTTP 400"):
        HttpFetcher(client)("https://sapi.craigslist.org/x")


def test_http_fetcher_waits_between_requests():
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="")))
    fetch = HttpFetcher(client, delay=0.5, clock=lambda: now[0], sleep=sleep)

    fetch("https://sapi.craigslist.org/1")
    now[0] += 0.2
    fetch("https://sapi.craigslist.org/2")

    assert sleeps == [pytest.approx(0.3)]
