import json
from datetime import UTC, datetime
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
    Source,
    listing_attributes,
    model_year,
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
    return {int(listing.id.split(":", 1)[1]): listing for listing in found}


# Parsing


def test_parses_a_full_response_into_listings():
    page = parse_full(fixture("owner_full.json"), OwnerType.OWNER)

    assert len(page.listings) == 20
    assert page.reported_total == 1508
    assert page.listings[0] == Listing(
        id="craigslist:7968808449",
        source=Source.CRAIGSLIST,
        title="2015 MERCEDES BENZ C300 FULLY LOADED VERY CLEAN!!!",
        price=7500,
        mileage=140000,
        url="https://www.craigslist.org/view/d/laguna-niguel-2015-mercedes-benz-c300/rbFpehbubddhXXYr61UQG5",
        images=page.listings[0].images,
        owner_type=OwnerType.OWNER,
        posted=datetime(2026, 9, 18, 19, 2, 16, tzinfo=UTC),
        location="Laguna Niguel",
        year=2015,
    )
    assert page.listings[0].images[0] == "https://images.craigslist.org/00h0h_4R4y4ghJzOC_0CI0t2_600x450.jpg"


def test_parses_a_batch_response_into_listings():
    page = parse_batch(fixture("owner_batch_0.json"), OwnerType.OWNER)

    assert page.result_count == 20
    assert len(page.listings) == 18  # two have no price
    corvette = by_post_id(page.listings)[7968774249]
    assert corvette.title == "2004 Chevy Corvette Convertible"
    assert corvette.price == 10900
    assert corvette.mileage == 75000
    assert corvette.url == "https://www.craigslist.org/view/d/westminster-2004-chevy-corvette/f6vnEnsiPRzJzzY9C6CtsJ"
    assert corvette.images[0] == "https://images.craigslist.org/01414_4krbn3IWsj9_0wU0oG_600x450.jpg"
    assert corvette.owner_type == OwnerType.OWNER
    assert corvette.year == 2004


def test_full_result_with_extra_integer_after_the_image_suffix_is_read():
    rdx = by_post_id(parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings)[7966353423 + 2386698]

    assert rdx.title == "2014 Acura RDX w/Tech Package"
    assert rdx.price == 5000
    assert rdx.mileage == 199400
    assert rdx.images[0] == "https://images.craigslist.org/00808_gPzpE2Dr7ep_0CI0t2_600x450.jpg"


def test_listing_attributes_parse_a_saved_detail_page():
    listing = parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings[0]

    attributes = listing_attributes(listing, lambda url: fixture("listing_detail.html"))

    assert attributes == {
        "VIN": "55SWF4JBXFU078066",
        "contact": "sms: 949-555-0100",
        "condition": "excellent",
        "cylinders": "4 cylinders",
        "fuel": "gas",
        "title status": "clean",
        "transmission": "automatic",
        "type": "sedan",
    }
    assert "odometer" not in attributes


def test_listing_attributes_do_not_read_mileage_from_the_detail_page():
    listing = parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings[0]

    attributes = listing_attributes(listing, lambda url: fixture("listing_detail.html").replace("odometer:", "mileage:"))

    assert "mileage" not in attributes


def test_listing_attribute_value_containing_a_colon_is_kept_whole():
    listing = parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings[0]

    attributes = listing_attributes(listing, lambda url: fixture("listing_detail.html"))

    assert attributes["contact"] == "sms: 949-555-0100"


def test_failed_listing_attribute_fetch_is_logged_and_returns_no_attributes(log_messages):
    listing = parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings[0]

    attributes = listing_attributes(listing, lambda url: (_ for _ in ()).throw(ListingSourceError("HTTP 403")))

    assert attributes == {}
    assert any("listing detail page: failed to fetch" in message for message in log_messages)


def test_detail_page_without_a_post_id_is_logged_and_returns_no_attributes(log_messages):
    listing = parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings[0]

    attributes = listing_attributes(listing, lambda url: fixture("listing_detail.html").replace("post id: 7968808449", ""))

    assert attributes == {}
    assert any("listing detail page: no post id" in message for message in log_messages)


def test_result_with_no_photos_is_kept_with_no_image_codes():
    full = by_post_id(parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings)
    batch = by_post_id(parse_batch(fixture("owner_batch_0.json"), OwnerType.OWNER).listings)

    assert full[7966353423 + 2369301].images == ()
    assert batch[7954482646 + 14240078].images == ()


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
    assert len(pilot.images) == 18
    assert pilot.images[9:12] == (
        "https://images.craigslist.org/00V0V_iohoXTev5ow_0CI0t2_600x450.jpg",
        "https://images.craigslist.org/00G0G_h8GaX6AVHXa_0CI0t2_600x450.jpg",
        "https://images.craigslist.org/00909_8JEMaXX4qIx_0CI0t2_600x450.jpg",
    )


def test_search_with_no_results_parses_although_decode_is_zero():
    # A live search with no results answers "decode": 0 instead of an object.
    page = parse_full('{"data": {"items": [], "totalResultCount": 0, "cacheTs": 1, "decode": 0}}', OwnerType.OWNER)

    assert page.listings == []
    assert page.result_count == page.reported_total == 0


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
    assert sorted(int(listing.id.split(":", 1)[1]) for listing in results.listings) == sorted(expected)


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
    ids = [listing.id for listing in results.listings]

    assert len(ids) == len(set(ids))


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


# Streaming, failure and cancelling


class FailsAfter:
    """Wraps a fetch and raises ListingSourceError from request number `n` + 1."""

    def __init__(self, fetch: FakeFetcher, n: int) -> None:
        self.fetch, self.n, self.calls = fetch, n, 0

    def __call__(self, url: str) -> str:
        self.calls += 1
        if self.calls > self.n:
            raise ListingSourceError("HTTP 429")
        return self.fetch(url)


def test_batches_are_reported_in_request_order_and_add_up_to_the_listings(small_pages):
    batches: list[list[Listing]] = []

    results = search_listings(
        Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), paged_owner_fetcher(), on_batch=batches.append
    )

    assert len(batches) == 3  # the full page, then batches at offsets 0 and 20
    assert [listing for batch in batches for listing in batch] == results.listings
    assert batches[0] == parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings
    assert not {listing.id for listing in batches[1]} & {listing.id for listing in batches[0]}
    assert results.error is None and not results.cancelled and results.requests == 4


def test_a_failure_after_some_pages_returns_their_listings_and_the_error(small_pages):
    batches: list[list[Listing]] = []
    fetch = FailsAfter(paged_owner_fetcher(), 3)  # full, cache, batch 0 answer; batch 20 fails

    results = search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), fetch, on_batch=batches.append)

    assert isinstance(results.error, ListingSourceError)
    assert results.requests == 3
    assert not results.cancelled
    assert results.listings == [listing for batch in batches for listing in batch]
    assert len(results.listings) > FIXTURE_PAGE_SIZE - 1


def test_a_failure_on_the_first_request_returns_no_listings_and_the_error():
    results = search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), FailsAfter(FakeFetcher(), 0))

    assert results.listings == []
    assert results.requests == 0
    assert results.error is not None


def test_a_failure_in_the_first_owner_type_keeps_it_and_skips_the_second():
    fetch = FailsAfter(FakeFetcher(owner_full=fixture("owner_full.json")), 1)
    search = Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER, OwnerType.DEALER))

    results = search_listings(search, fetch)

    assert len(results.listings) == 20
    assert fetch.calls == 2
    assert results.error is not None


def test_cancelling_makes_no_further_requests(small_pages):
    fetch = paged_owner_fetcher()
    batches: list[list[Listing]] = []

    results = search_listings(
        Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)),
        fetch,
        on_batch=batches.append,
        should_stop=lambda: len(fetch.urls) >= 2,  # stop once the full and cache requests are made
    )

    assert len(fetch.urls) == 2
    assert results.cancelled
    assert results.error is None
    assert results.listings == batches[0]


def test_cancelling_before_the_first_request_makes_none():
    fetch = FakeFetcher()

    results = search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), fetch, should_stop=lambda: True)

    assert fetch.urls == []
    assert results.cancelled and results.listings == []


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


# Posted time and location


def test_full_result_has_posted_time_and_location():
    listings_by_id = by_post_id(parse_full(fixture("owner_full.json"), OwnerType.OWNER).listings)

    first = listings_by_id[7968808449]
    assert first.posted == datetime.fromtimestamp(1789407924 + 350212, UTC)
    assert first.posted.tzinfo is not None
    assert first.location == "Laguna Niguel"
    assert all(listing.posted for listing in listings_by_id.values())
    assert listings_by_id[7968734514].location is None  # geo index 0 has no description


def test_batch_result_has_no_posted_time_or_location():
    page = parse_batch(fixture("owner_batch_0.json"), OwnerType.OWNER)

    assert all(listing.posted is None and listing.location is None for listing in page.listings)


def test_full_result_without_a_geo_string_or_posted_offset_gets_none():
    body = json.loads(fixture("owner_full.json"))
    item = body["data"]["items"][0]
    item[1], item[4] = None, "not a geo string"
    body["data"]["items"][1][4] = "1:9999~1~2"  # index outside locationDescriptions

    by_id = by_post_id(parse_full(json.dumps(body), OwnerType.OWNER).listings)

    assert (by_id[7968808449].posted, by_id[7968808449].location) == (None, None)
    assert by_id[7966353423 + body["data"]["items"][1][0]].location is None


def test_full_response_without_decode_dates_or_descriptions_gives_none():
    body = json.loads(fixture("owner_full.json"))
    del body["data"]["decode"]["minPostedDate"]
    del body["data"]["decode"]["locationDescriptions"]

    page = parse_full(json.dumps(body), OwnerType.OWNER)

    assert len(page.listings) == 20
    assert all(listing.posted is None and listing.location is None for listing in page.listings)


def test_paged_search_fills_batch_results_from_the_step_2_short_form(small_pages):
    # Shift the first `full` result's id by one, so the batch copy of that post is the
    # only one with that id and carries no posted time or location of its own.
    body = json.loads(fixture("owner_full.json"))
    body["data"]["items"][0][0] += 1
    fetch = paged_owner_fetcher(owner_full=json.dumps(body))

    by_id = by_post_id(search_listings(Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,)), fetch).listings)

    filled = by_id[7968808449]
    assert filled.posted == datetime.fromtimestamp(1787124633 + 2633503, UTC)
    assert filled.location == "Laguna Niguel"
    # A batch result the short form does not list stays unknown rather than failing.
    assert by_id[7968471033].posted is None
    assert by_id[7968471033].location is None


# Model year from the title


@pytest.mark.parametrize(
    "title, year",
    [
        ("2015 Honda Civic EX", 2015),
        ("1967 Ford Mustang fastback", 1967),
        ("Honda Civic 2017 one owner", 2017),
        ("Clean title Civic EX, 2009, runs great", 2009),
        ("Honda Civic EX", None),
        ("Civic EX $8500 obo", None),
        ("Civic 1000 miles on new engine", None),
        ("Civic 3000", None),
        ("Civic 20155 parts", None),
        ("Civic $2015", None),
    ],
)
def test_model_year_is_read_from_the_title(title, year):
    assert model_year(title) == year


def test_a_title_with_no_year_is_logged_at_debug(log_messages):
    model_year("Honda Civic EX")

    assert any("no model year" in message for message in log_messages)
