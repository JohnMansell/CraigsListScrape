"""Listing source: turn a Search into Listings, read from Craigslist's JSON search API.

This is the API Craigslist's own search page uses (see docs/research/craigslist-search.md).
It is undocumented, so every Craigslist URL and every guess about its response layout
lives in this module. Nothing here touches the network except `HttpFetcher`: the search
takes a `fetch(url) -> str` callable, so tests serve saved responses instead.

A search makes these requests, one set per owner type:

1. `full?batch=0-0-360-0-0`: the reported total, and the first 360 results.
2. Only when step 1 came back full: `full?batch=0-<cacheTs>-0-1-0`, for a cache id.
3. `batch?batch=0-<offset>-1080-1-...` from offset 0, until a batch comes back short.
   The batches start again from the first result, so they repeat step 1's results.
"""
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from loguru import logger
from selectolax.parser import HTMLParser

from craigslist.lookup import City

API_NAME = "Craigslist search API"
DETAIL_PAGE_NAME = "Craigslist listing detail page"
API_BASE = "https://sapi.craigslist.org/web/v8/postings/search"
LISTING_BASE = "https://www.craigslist.org/view/d"
IMAGE_BASE = "https://images.craigslist.org"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"

FULL_PAGE_SIZE = 360
BATCH_PAGE_SIZE = 1080
MAX_BATCH_REQUESTS = 20
REQUEST_DELAY = 0.5
"""Seconds between API requests, the pacing issue #2 recommends."""

# Tags on the [tag, value, ...] lists inside a result.
TAG_IMAGES = 4
TAG_SLUG = 6
TAG_ODOMETER = 9
TAG_PRICE = 10
TAG_TOKEN = 13

Fetch = Callable[[str], str]
"""Returns the response body for a URL, or raises. Owns pacing and headers."""


class OwnerType(StrEnum):
    """Who is selling. The value is the API's `purveyor` parameter."""

    OWNER = "owner"
    DEALER = "dealer"


PURVEYOR_CODES = {145: OwnerType.OWNER, 146: OwnerType.DEALER}
"""Index 2 of a `full` result. `batch` results carry no purveyor code."""


class ListingSourceError(Exception):
    """The search API failed or answered in a shape this module does not understand."""


@dataclass(frozen=True)
class Search:
    city: City
    make: str | None = None
    model: str | None = None
    """Only used together with `make`."""
    owner_types: tuple[OwnerType, ...] = (OwnerType.OWNER, OwnerType.DEALER)


@dataclass(frozen=True)
class Listing:
    post_id: int
    title: str
    price: int
    mileage: int | None
    """None when the seller left the odometer empty."""
    url: str
    image_codes: tuple[str, ...]
    """Deduplicated, in the listing's order. See `image_url` for the full URL."""
    owner_type: OwnerType


@dataclass(frozen=True)
class SearchResults:
    listings: list[Listing]
    reported_totals: dict[OwnerType, int]
    """The API's `totalResultCount` per owner type. It counts local results only, so
    dealer searches often return more Listings than this."""


def image_url(code: str, size: str = "600x450") -> str:
    """Sizes seen: 600x450, 300x300, 50x50c."""
    return f"{IMAGE_BASE}/{code}_{size}.jpg"


def listing_attributes(listing: Listing, fetch: Fetch) -> dict[str, str]:
    """Fetch the extra attributes from one Listing's detail page.

    A failed request or a page without a post id may be a Craigslist block. Log it and
    return no attributes rather than retrying or delaying a Search result.
    """
    try:
        page = HTMLParser(fetch(listing.url))
    except Exception as error:
        logger.warning("{}: failed to fetch {}: {}", DETAIL_PAGE_NAME, listing.url, error)
        return {}

    if not any(re.fullmatch(r"post id:\s*\d+", info.text(strip=True), re.IGNORECASE) for info in page.css(".postinginfo")):
        logger.warning("{}: no post id in {}", DETAIL_PAGE_NAME, listing.url)
        return {}

    attributes = {}
    for attribute in page.css(".attrgroup .attr"):
        label = attribute.css_first(".labl")
        value = attribute.css_first(".valu")
        if label is not None and value is not None:
            key = label.text(strip=True).removesuffix(":")
            if key.casefold() not in {"mileage", "odometer"}:
                attributes[key] = value.text(strip=True)
    return attributes


def search_listings(search: Search, fetch: Fetch) -> SearchResults:
    """All Listings for `search`, one API search per owner type, each Listing tagged
    with the owner type it came from."""
    listings: list[Listing] = []
    totals: dict[OwnerType, int] = {}
    for owner_type in search.owner_types:
        found, totals[owner_type] = _search_owner_type(search, owner_type, fetch)
        listings.extend(found)
    return SearchResults(listings, totals)


def _search_owner_type(search: Search, owner_type: OwnerType, fetch: Fetch) -> tuple[list[Listing], int]:
    page = parse_full(fetch(full_url(search, owner_type)), owner_type)
    results = {listing.post_id: listing for listing in page.listings}
    results_seen = page.result_count
    """How far into the results paging got, counting results skipped while parsing."""

    cache = None
    if page.result_count >= FULL_PAGE_SIZE:
        cache = _read_cache(fetch(cache_url(search, owner_type, page.cache_ts)))
    if cache:
        cache_id, max_posted_ts = cache
        for batch_number in range(MAX_BATCH_REQUESTS):
            offset = batch_number * BATCH_PAGE_SIZE
            batch = parse_batch(fetch(batch_url(offset, cache_id, max_posted_ts, page.cache_ts)), owner_type)
            # Batches restart from the first result, so they repeat the `full` page.
            for listing in batch.listings:
                results.setdefault(listing.post_id, listing)
            results_seen = max(results_seen, offset + batch.result_count)
            if batch.result_count < BATCH_PAGE_SIZE:
                break
        else:
            logger.warning(
                "{} {}: stopped after {} batch requests, there may be more results",
                API_NAME, owner_type, MAX_BATCH_REQUESTS,
            )

    if results_seen != page.reported_total:
        # Normal for dealer searches: the total leaves out results syndicated from other areas.
        logger.debug("{} {}: got {} results, API reported {}", API_NAME, owner_type, results_seen, page.reported_total)
    logger.info("{} {}: {} Listings", API_NAME, owner_type, len(results))
    return list(results.values()), page.reported_total


# URLs


def search_path(city: City) -> str:
    """`area/<slug>` from a city's base URL, such as https://orangecounty.craigslist.org"""
    return "area/" + (urlsplit(city.url).hostname or "").removesuffix(".craigslist.org")


def _search_params(search: Search, owner_type: OwnerType) -> dict[str, str]:
    params = {"cat": "cta", "purveyor": owner_type.value, "searchPath": search_path(search.city), "lang": "en", "cc": "us"}
    if search.make:
        params["auto_make_model"] = f"{search.make} {search.model}" if search.model else search.make
    return params


def full_url(search: Search, owner_type: OwnerType) -> str:
    """Step 1: the reported total and the first FULL_PAGE_SIZE results."""
    return f"{API_BASE}/full?batch=0-0-{FULL_PAGE_SIZE}-0-0&{urlencode(_search_params(search, owner_type))}"


def cache_url(search: Search, owner_type: OwnerType, cache_ts: int) -> str:
    """Step 2: the cache id and max posted time that batch requests need."""
    return f"{API_BASE}/full?batch=0-{cache_ts}-0-1-0&{urlencode(_search_params(search, owner_type))}"


def batch_url(offset: int, cache_id: str, max_posted_ts: int, cache_ts: int) -> str:
    """Step 3: up to BATCH_PAGE_SIZE results starting at `offset`."""
    batch = f"0-{offset}-{BATCH_PAGE_SIZE}-1-0-{max_posted_ts}-{cache_ts}"
    return f"{API_BASE}/batch?{urlencode({'batch': batch, 'cacheId': cache_id, 'lang': 'en', 'cc': 'us'})}"


def listing_url(slug: str, token: str) -> str:
    return f"{LISTING_BASE}/{slug}/{token}"


# Parsing


@dataclass(frozen=True)
class FullPage:
    listings: list[Listing]
    result_count: int
    """Results in the response, including any skipped while parsing."""
    reported_total: int
    cache_ts: int


@dataclass(frozen=True)
class BatchPage:
    listings: list[Listing]
    result_count: int


def parse_full(text: str, owner_type: OwnerType) -> FullPage:
    """Parse a step-1 `full` response. Raises ListingSourceError if a result's purveyor
    code names the other owner type: the owner filter would then be broken."""
    body = _data(text)
    items = _require(body, "items", list)
    decode = _require(body, "decode", dict)
    min_posting_id = _require(decode, "minPostingId", int)
    listings = []
    for item in items:
        if not isinstance(item, list) or len(item) < 3:
            logger.warning("{}: skipping unreadable result {!r}", API_NAME, item)
            continue
        purveyor = PURVEYOR_CODES.get(item[2])
        if purveyor is None:
            logger.warning("{}: skipping result with unknown purveyor code {!r}", API_NAME, item)
            continue
        if purveyor != owner_type:
            raise ListingSourceError(f"{API_NAME}: asked for {owner_type} listings, got {purveyor} listings")
        listing = _parse_result(item, item[-1], _tagged(item).get(TAG_IMAGES, []), min_posting_id, owner_type)
        if listing:
            listings.append(listing)
    return FullPage(
        listings, len(items), _require(body, "totalResultCount", int), _require(body, "cacheTs", int)
    )


def parse_batch(text: str, owner_type: OwnerType) -> BatchPage:
    """Parse a step-3 `batch` response. Its results carry no purveyor code, so they are
    tagged with `owner_type`, the type the search asked for."""
    body = _data(text)
    items = _require(body, "batch", list)
    min_posting_id = _require(body, "minPostingId", int)
    listings = []
    for item in items:
        if not isinstance(item, list) or len(item) < 3 or not isinstance(item[2], list):
            logger.warning("{}: skipping unreadable result {!r}", API_NAME, item)
            continue
        listing = _parse_result(item, item[1], item[2], min_posting_id, owner_type)
        if listing:
            listings.append(listing)
    return BatchPage(listings, len(items))


def _parse_result(
    item: list[Any], title: Any, images: list[Any], min_posting_id: int, owner_type: OwnerType
) -> Listing | None:
    """The layout-independent part: `title` and `images` are found by the caller."""
    tagged = _tagged(item)
    offset = item[0]
    slug, token = _first(tagged.get(TAG_SLUG)), _first(tagged.get(TAG_TOKEN))
    if not (isinstance(offset, int) and isinstance(title, str) and isinstance(slug, str) and isinstance(token, str)):
        logger.warning("{}: skipping unreadable result {!r}", API_NAME, item)
        return None
    post_id = min_posting_id + offset

    price = _price(_first(tagged.get(TAG_PRICE)))
    if price is None:
        logger.info("{}: skipping post {} with no price: {}", API_NAME, post_id, title)
        return None

    mileage = _first(tagged.get(TAG_ODOMETER))
    codes = (image.removeprefix("3:") for image in images if isinstance(image, str))
    return Listing(
        post_id=post_id,
        title=title,
        price=price,
        mileage=mileage if isinstance(mileage, int) else None,
        url=listing_url(slug, token),
        image_codes=tuple(dict.fromkeys(codes)),
        owner_type=owner_type,
    )


def _tagged(item: list[Any]) -> dict[int, list[Any]]:
    """The [tag, value, ...] lists in a result, keyed by tag."""
    return {
        field[0]: field[1:]
        for field in item
        if isinstance(field, list) and field and isinstance(field[0], int) and not isinstance(field[0], bool)
    }


def _first(values: list[Any] | None) -> Any:
    return values[0] if values else None


def _price(text: Any) -> int | None:
    """"$2,900" -> 2900."""
    if not isinstance(text, str):
        return None
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def _read_cache(text: str) -> tuple[str, int] | None:
    """The cache id and max posted time from a step-2 response, or None when the
    response lists all the results itself, which it does when there are too few to page."""
    body = _data(text)
    if "cacheId" not in body and len(_require(body, "items", list)) <= FULL_PAGE_SIZE:
        return None
    return _require(body, "cacheId", str), _require(body, "maxPostedTs", int)


def _data(text: str) -> dict[str, Any]:
    """The `data` object of a response body."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ListingSourceError(f"{API_NAME}: response is not JSON: {text[:200]!r}") from error
    if not isinstance(data, dict):
        raise ListingSourceError(f"{API_NAME}: response is not a JSON object: {text[:200]!r}")
    return _require(data, "data", dict)


def _require[T](body: dict[str, Any], key: str, kind: type[T]) -> T:
    value = body.get(key)
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise ListingSourceError(f"{API_NAME}: response has no {kind.__name__} `{key}`")
    return value


# Fetching


class HttpFetcher:
    """A `Fetch` over httpx: sends a browser User-Agent, waits `delay` seconds between
    requests, and raises ListingSourceError on a failed request or non-200 status."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        delay: float = REQUEST_DELAY,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(timeout=30, follow_redirects=True)
        self._delay = delay
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None

    def __call__(self, url: str) -> str:
        if self._last_request is not None:
            wait = self._last_request + self._delay - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()
        logger.debug("GET {}", url)
        try:
            response = self._client.get(url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as error:
            raise ListingSourceError(f"{API_NAME}: request failed: {error}") from error
        if response.status_code != 200:
            raise ListingSourceError(f"{API_NAME}: HTTP {response.status_code} from {url}: {response.text[:200]!r}")
        return response.text

    def close(self) -> None:
        self._client.close()
