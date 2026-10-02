"""Carfax Listing source: turn a Search into Listings, read from Carfax's undocumented
helix JSON search API (see docs/research/carfax-search.md). Nothing here touches the
network except `HttpFetcher`: the search takes a `fetch(url) -> str` callable, so tests
serve saved responses instead.

Carfax's terms of use limit this to personal, non-commercial use (the #25 decisions on
issue #24): keep this source local, never point it at a server shown to other people.

A search pages one price band (`zip`, fixed `RADIUS_MILES`, make/model) at a time, `rows`
at `PAGE_SIZE` until a page comes back short or empty, never past `MAX_PAGE`. A band that
is still full at `MAX_PAGE` may hold more than `PAGE_SIZE * MAX_PAGE` Listings, so it is
split in two by price and each half is paged the same way.
"""
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from loguru import logger

from craigslist.listings import Fetch, Listing, ListingSourceError, OwnerType, Source
from craigslist.lookup import City, carfax_model

API_NAME = "Carfax search API"
API_BASE = "https://helix.carfax.com/search/v2/vehicles"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"

RADIUS_MILES = 50
"""Fixed per the #25 decisions on #24: no control on the Search page."""
PAGE_SIZE = 25
"""Carfax's page size cap."""
MAX_PAGE = 50
"""Carfax's page number cap."""
PRICE_CEILING = 500_000
"""Far above any real used-car price, so a price band always has somewhere to split to."""
REQUEST_DELAY = 0.5
"""Seconds between API requests."""


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
    """Carfax's `totalListingCount` for the whole search (its first, unsplit band)."""
    requests: int = 0
    """API requests that got an answer."""
    error: ListingSourceError | None = None
    """Set when the search stopped early on a failed request. `listings` then holds what
    arrived before it."""
    cancelled: bool = False
    """True when `should_stop` ended the search early. `listings` holds what arrived."""


class _Stopped(Exception):
    """Raised inside a search when `should_stop` says to make no further requests."""


def search_carfax(
    search: Search,
    fetch: Fetch,
    on_batch: Callable[[list[Listing]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> SearchResults:
    """All Carfax Listings for `search`. Every Listing is tagged `OwnerType.DEALER`;
    Carfax has no private sellers.

    `on_batch` gets each API page's new Listings, in request order, as the page arrives.
    `should_stop` is asked before every request; once true, no more are made. A failed
    request ends the search too, but is returned in `SearchResults.error` beside the
    Listings that arrived before it, not raised.

    When `search.make`/`search.model` has no Carfax name (`lookup.carfax_model`), the
    search is skipped with a logged warning and returns no Listings.
    """
    carfax_make = search.make
    carfax_model_name = None
    if search.make and search.model:
        carfax_model_name = carfax_model(search.make, search.model)
        if carfax_model_name is None:
            logger.warning("{}: {} {} has no Carfax name, skipping", API_NAME, search.make, search.model)
            return SearchResults([])

    results: dict[str, Listing] = {}
    requests = 0
    error: ListingSourceError | None = None
    cancelled = False
    reported_total = 0
    first_band = True

    def counted_fetch(url: str) -> str:
        nonlocal requests
        if should_stop is not None and should_stop():
            raise _Stopped
        text = fetch(url)
        requests += 1
        return text

    def emit(batch: list[Listing]) -> None:
        new = [listing for listing in batch if listing.id not in results]
        if new:
            results.update({listing.id: listing for listing in new})
            if on_batch is not None:
                on_batch(new)

    bands: list[tuple[int | None, int | None]] = [(None, None)]
    try:
        while bands:
            price_min, price_max = bands.pop()
            hit_cap, band_total = _page_band(search.city.zip, carfax_make, carfax_model_name, price_min, price_max, counted_fetch, emit)
            if first_band:
                reported_total = band_total
                first_band = False
            if hit_cap:
                split = _split_band(price_min, price_max)
                if split is None:
                    logger.warning("{}: price band ${:,}-${:,} would not split further, some Listings may be missing", API_NAME, price_min or 0, price_max or PRICE_CEILING)
                else:
                    bands.extend(split)
    except _Stopped:
        cancelled = True
        logger.info("{}: cancelled after {} requests with {} Listings", API_NAME, requests, len(results))
    except ListingSourceError as failure:
        error = failure
        logger.warning("{}: failed after {} requests with {} Listings: {}", API_NAME, requests, len(results), failure)
    return SearchResults(list(results.values()), reported_total, requests, error, cancelled)


def _page_band(
    zip_code: str,
    make: str | None,
    model: str | None,
    price_min: int | None,
    price_max: int | None,
    fetch: Fetch,
    emit: Callable[[list[Listing]], None],
) -> tuple[bool, int]:
    """Pages one price band until a short or empty page. Returns whether `MAX_PAGE` was
    reached while the page was still full (so the band may hold more than
    `PAGE_SIZE * MAX_PAGE` Listings and should be split), and the band's reported total."""
    total = 0
    for page in range(1, MAX_PAGE + 1):
        body = _data(fetch(_search_url(zip_code, make, model, price_min, price_max, page)))
        items = body.get("listings")
        if items is None:  # no results in this band
            return False, 0
        if not isinstance(items, list):
            raise ListingSourceError(f"{API_NAME}: response has no list `listings`")
        if page == 1:
            total = _require(body, "totalListingCount", int)
        emit([listing for item in items if isinstance(item, dict) and (listing := _parse_item(item)) is not None])
        if len(items) < PAGE_SIZE:
            return False, total
    return True, total


def _split_band(price_min: int | None, price_max: int | None) -> list[tuple[int, int]] | None:
    """Halves a price band by price. None when it is already down to a single dollar."""
    low = price_min or 0
    high = price_max if price_max is not None else PRICE_CEILING
    mid = (low + high) // 2
    if mid <= low:
        return None
    return [(low, mid), (mid + 1, high)]


# URLs


def _search_url(
    zip_code: str, make: str | None, model: str | None, price_min: int | None, price_max: int | None, page: int
) -> str:
    params: dict[str, str | int] = {
        "zip": zip_code, "radius": RADIUS_MILES, "vehicleCondition": "USED", "rows": PAGE_SIZE, "page": page,
    }
    if make:
        params["make"] = make
    if model:
        params["model"] = model
    if price_min is not None:
        params["priceMin"] = price_min
    if price_max is not None:
        params["priceMax"] = price_max
    return f"{API_BASE}?{urlencode(params)}"


# Parsing


def _parse_item(item: dict[str, Any]) -> Listing | None:
    item_id, vdp_url = item.get("id"), item.get("vdpUrl")
    year, make, model = item.get("year"), item.get("make"), item.get("model")
    if not (
        isinstance(item_id, str) and isinstance(vdp_url, str)
        and isinstance(year, int) and not isinstance(year, bool)
        and isinstance(make, str) and isinstance(model, str)
    ):
        logger.warning("{}: skipping unreadable result {!r}", API_NAME, item)
        return None

    price = item.get("currentPrice")
    if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
        logger.info("{}: skipping {} with no price: {} {} {}", API_NAME, item_id, year, make, model)
        return None

    trim = item.get("trim")
    title = f"{year} {make} {model}"
    if isinstance(trim, str) and trim and trim != "Unspecified":
        title += f" {trim}"

    mileage = item.get("mileage")
    images = _images(item.get("images"))
    location = _dealer_location(item.get("dealer"))
    posted = _first_seen(item.get("firstSeen"))

    return Listing(
        id=f"{Source.CARFAX}:{item_id}",
        source=Source.CARFAX,
        title=title,
        price=price,
        mileage=mileage if isinstance(mileage, int) and not isinstance(mileage, bool) else None,
        url=vdp_url,
        images=images,
        owner_type=OwnerType.DEALER,
        posted=posted,
        location=location,
    )


def _images(images: Any) -> tuple[str, ...]:
    if not isinstance(images, dict):
        return ()
    large = images.get("large")
    if not isinstance(large, list):
        return ()
    return tuple(url for url in large if isinstance(url, str))


def _dealer_location(dealer: Any) -> str | None:
    if not isinstance(dealer, dict):
        return None
    city, state = dealer.get("city"), dealer.get("state")
    return f"{city}, {state}" if isinstance(city, str) and isinstance(state, str) else None


def _first_seen(first_seen: Any) -> datetime | None:
    if not isinstance(first_seen, str):
        return None
    try:
        return datetime.strptime(first_seen, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


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
