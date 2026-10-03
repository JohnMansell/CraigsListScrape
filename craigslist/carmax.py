"""CarMax Listing source: turn a Search into Listings, read from the JSON search API behind
carmax.com's own search page (see docs/research/carmax-search.md). Nothing here touches the
network except `HttpFetcher`: the search takes a `fetch(url) -> str` callable, so tests serve
saved responses instead.

CarMax's terms of use ban scraping, even for personal use. The #42 decisions on issue #41
accept that risk for local, personal use only: keep this source local, never point it at a
server shown to other people.

A search pages `skip`/`take` at `PAGE_SIZE` until a page comes back short or empty (the API's
`totalCount` is unreliable), never past `MAX_PAGES`. CarMax silently ignores a make or model
slug it does not know and returns a broader search, so the response's `selectedFacets` is
checked against the slugs asked for; a search that fails the check is skipped with a logged
warning and returns no Listings, rather than putting every car of the make on the chart.
"""
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from loguru import logger

from craigslist.listings import Fetch, Listing, ListingSourceError, OwnerType, Source
from craigslist.lookup import City, carmax_make, carmax_model

API_NAME = "CarMax search API"
SITE = "https://www.carmax.com"
API_BASE = f"{SITE}/cars/api/search/run"
LISTING_BASE = f"{SITE}/car"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

RADIUS_MILES = 50
"""Fixed per the #42 decisions on #41: no control on the Search page."""
PAGE_SIZE = 100
"""CarMax's `take` cap; 101 is a 400."""
MAX_PAGES = 10
"""At most 1000 Listings per Search (the #42 decisions)."""
REQUEST_DELAY = 1.0
"""Minimum seconds between requests, the warm-up included."""


@dataclass(frozen=True)
class Search:
    city: City
    make: str | None = None
    model: str | None = None
    """Only used together with `make`."""


@dataclass(frozen=True)
class SearchResults:
    listings: list[Listing]
    reported_total: int = 0
    """CarMax's `totalCount` from the first page. A hint only: it drifts between pages."""
    requests: int = 0
    """API requests that got an answer."""
    error: ListingSourceError | None = None
    """Set when the search stopped early on a failed request. `listings` then holds what
    arrived before it."""
    cancelled: bool = False
    """True when `should_stop` ended the search early. `listings` holds what arrived."""
    complete: bool = True
    """False when the search was skipped or stopped at a page cap with no error, so a car it
    would have found may be missing from `listings`."""


class _Stopped(Exception):
    """Raised inside a search when `should_stop` says to make no further requests."""


def search_carmax(
    search: Search,
    fetch: Fetch,
    on_batch: Callable[[list[Listing]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> SearchResults:
    """All CarMax Listings for `search`. Every Listing is tagged `OwnerType.DEALER`.

    `on_batch` gets each API page's new Listings, in request order, as the page arrives.
    `should_stop` is asked before every request; once true, no more are made. A failed
    request (an Akamai 403 included, which is never retried) ends the search too, but is
    returned in `SearchResults.error` beside the Listings that arrived before it.

    The search is skipped with a logged warning, returning no Listings, when
    `search.make`/`search.model` has no CarMax slug (`lookup.carmax_model`), or when the
    first page's `selectedFacets` does not echo the slugs asked for (CarMax ignored them).
    A search still full at `MAX_PAGES` logs a warning and returns what was fetched.
    """
    # --- Slugs
    make_slug = carmax_make(search.make) if search.make else None
    model_slug = None
    if search.make and search.model:
        model_slug = carmax_model(search.make, search.model)
        if model_slug is None:
            logger.warning("{}: {} {} has no CarMax name, skipping", API_NAME, search.make, search.model)
            return SearchResults([], complete=False)
    uri = "/cars" + (f"/{make_slug}" if make_slug else "") + (f"/{model_slug}" if model_slug else "")

    # --- Pages
    results: dict[str, Listing] = {}
    requests = 0
    reported_total = 0
    error: ListingSourceError | None = None
    cancelled = False
    complete = True
    try:
        for page in range(MAX_PAGES):
            if should_stop is not None and should_stop():
                raise _Stopped
            body = _data(fetch(search_url(search.city.zip, uri, page * PAGE_SIZE)))
            requests += 1
            items = _require(body, "items", list)
            if page == 0:
                reported_total = _require(body, "totalCount", int)
                if not _facets_match(body, make_slug, model_slug):
                    logger.warning(
                        "{}: CarMax ignored {} (it does not know the slug), skipping", API_NAME, uri
                    )
                    return SearchResults([], reported_total, requests, complete=False)
            batch = [listing for item in items if isinstance(item, dict) and (listing := _parse_item(item)) is not None]
            new = [listing for listing in batch if listing.id not in results]
            results.update({listing.id: listing for listing in new})
            if new and on_batch is not None:
                on_batch(new)
            if len(items) < PAGE_SIZE:
                break
        else:
            complete = False
            logger.warning(
                "{}: {} pages of {} were all full, stopping at {} Listings; more may exist",
                API_NAME, MAX_PAGES, PAGE_SIZE, len(results),
            )
    except _Stopped:
        cancelled = True
        logger.info("{}: cancelled after {} requests with {} Listings", API_NAME, requests, len(results))
    except ListingSourceError as failure:
        error = failure
        logger.warning("{}: failed after {} requests with {} Listings: {}", API_NAME, requests, len(results), failure)
    return SearchResults(list(results.values()), reported_total, requests, error, cancelled, complete)


def _facets_match(body: dict[str, Any], make_slug: str | None, model_slug: str | None) -> bool:
    """True when `selectedFacets` has the make (and model or series) that was asked for."""
    facets = body.get("selectedFacets")
    if not isinstance(facets, list):
        return False
    selected = {
        (facet.get("category"), str(facet.get("value")).casefold()) for facet in facets if isinstance(facet, dict)
    }
    if make_slug and ("make", make_slug) not in selected:
        return False
    return not model_slug or ("model", model_slug) in selected or ("series", model_slug) in selected


# URLs


def search_url(zip_code: str, uri: str, skip: int, take: int | None = None) -> str:
    """`uri` is the search page path, such as `/cars/honda/civic`. Its slashes stay raw:
    `%2F` is blocked by CarMax's bot protection."""
    params: dict[str, str | int] = {
        "uri": uri, "zipCode": zip_code, "radius": f"radius-{RADIUS_MILES}", "shipping": 0,
        "sort": "price-asc", "skip": skip, "take": take or PAGE_SIZE,
    }
    return f"{API_BASE}?{urlencode(params, safe='/')}"


# Parsing


def _parse_item(item: dict[str, Any]) -> Listing | None:
    stock, year, make, model = item.get("stockNumber"), item.get("year"), item.get("make"), item.get("model")
    if not (
        _is_int(stock) and _is_int(year) and isinstance(make, str) and isinstance(model, str)
    ):
        logger.warning("{}: skipping unreadable result {!r}", API_NAME, item)
        return None

    price = item.get("basePrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or round(price) <= 0:
        logger.info("{}: skipping {} with no price: {} {} {}", API_NAME, stock, year, make, model)
        return None

    trim = item.get("trim")
    if not (isinstance(trim, str) and trim):
        trim = None
    title = f"{year} {make} {model}"
    if trim:
        title += f" {trim}"

    mileage = item.get("mileage")
    image = item.get("heroImageUrl")
    store, city, state = item.get("storeName"), item.get("storeCity"), item.get("stateAbbreviation")
    price_drop = item.get("hasPriceDrop")
    highlights = item.get("highlights")

    return Listing(
        id=f"{Source.CARMAX}:{stock}",
        source=Source.CARMAX,
        title=title,
        price=round(price),
        mileage=mileage if _is_int(mileage) else None,
        url=f"{LISTING_BASE}/{stock}",
        images=(image,) if isinstance(image, str) and image else (),
        owner_type=OwnerType.DEALER,
        posted=_on_sale(item.get("lastMadeSaleableDate")),
        location=f"{city}, {state}" if isinstance(city, str) and isinstance(state, str) else None,
        dealer=store if isinstance(store, str) else None,
        one_owner=True if isinstance(highlights, list) and "singleOwner" in highlights else None,
        no_accidents=None,
        price_dropped=price_drop if isinstance(price_drop, bool) else None,
        year=year,
        trim=trim,
    )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _on_sale(text: Any) -> datetime | None:
    """`lastMadeSaleableDate`, ISO 8601 UTC; `null` on a few cars."""
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _data(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ListingSourceError(f"{API_NAME}: response is not JSON: {text[:200]!r}") from error
    if not isinstance(data, dict):
        raise ListingSourceError(f"{API_NAME}: response is not a JSON object: {text[:200]!r}")
    return data


def _require[T](body: dict[str, Any], key: str, kind: type[T]) -> T:
    value = body.get(key)
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise ListingSourceError(f"{API_NAME}: response has no {kind.__name__} `{key}`")
    return value


# Fetching


class HttpFetcher:
    """A `Fetch` over httpx for CarMax's Akamai-protected API.

    Akamai needs HTTP/2 (`h2`), browser headers and a Referer, and cookies it sets on a
    warm-up request. The first call makes that one warm-up request (a GET of the search
    page named by the URL's `uri`; its status is ignored, since it is often a 403 that
    still sets the cookies). Requests are at least `delay` seconds apart. A non-200 answer
    raises ListingSourceError and is never retried. Use one fetcher per Search.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        delay: float = REQUEST_DELAY,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(headers=HEADERS, timeout=30, http2=True, follow_redirects=True)
        self._delay = delay
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None
        self._warmed_up = False

    def __call__(self, url: str) -> str:
        page = SITE + parse_qs(urlsplit(url).query).get("uri", ["/cars"])[0]
        referer = {"Referer": page}
        if not self._warmed_up:
            self._warmed_up = True
            logger.debug("GET {} (warm-up)", page)
            self._get(page, referer)
        response = self._get(url, referer)
        if response.status_code != 200:
            raise ListingSourceError(f"{API_NAME}: HTTP {response.status_code} from {url}: {response.text[:200]!r}")
        return response.text

    def _get(self, url: str, headers: dict[str, str]) -> httpx.Response:
        if self._last_request is not None:
            wait = self._last_request + self._delay - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()
        logger.debug("GET {}", url)
        try:
            return self._client.get(url, headers=headers)
        except httpx.HTTPError as error:
            raise ListingSourceError(f"{API_NAME}: request failed: {error}") from error

    def close(self) -> None:
        self._client.close()
