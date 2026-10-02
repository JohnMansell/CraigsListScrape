"""Run a validated car search from lookup values through fitted price curves."""
from collections.abc import Callable
from dataclasses import dataclass

from craigslist import lookup
from craigslist.carfax import HttpFetcher as CarfaxHttpFetcher, Search as CarfaxSearch, search_carfax
from craigslist.curve import NotEnoughData, PriceCurve, fit_price_curve
from craigslist.listings import Fetch, HttpFetcher, Listing, ListingSourceError, OwnerType, Search as ListingSearch, search_listings


OnBatch = Callable[[list[Listing]], None]
"""Gets each API page's new Listings as the page arrives."""
ShouldStop = Callable[[], bool]
"""Asked before every API request; True means make no more."""


class SearchError(ValueError):
    """The caller supplied a state, city, make, or model outside the lookup tables, or a
    Search with none of Owner, Dealer, or Carfax chosen."""


@dataclass(frozen=True)
class Search:
    """The lookup values and Sources for one whole car search. `owner_types` chooses
    Craigslist Owner and/or Dealer listings; `carfax` independently chooses Carfax's
    (dealer-only) listings. At least one of the three must be chosen."""

    state: str
    city: str
    make: str
    model: str
    owner_types: tuple[OwnerType, ...] = (OwnerType.OWNER, OwnerType.DEALER)
    carfax: bool = True


@dataclass(frozen=True)
class SearchResult:
    """Listings from every chosen Source, and one independently fitted Price curve per
    Craigslist owner type plus one for Carfax."""

    listings: list[Listing]
    curves: dict[OwnerType, PriceCurve | NotEnoughData]
    reported_totals: dict[OwnerType, int]
    carfax_curve: PriceCurve | NotEnoughData | None = None
    """None when the Search did not include Carfax."""
    carfax_reported_total: int = 0
    requests: int = 0
    """API requests that got an answer, from every Source."""
    error: ListingSourceError | None = None
    """Craigslist failed mid-Search. `listings` holds what arrived from it before that."""
    carfax_error: ListingSourceError | None = None
    """Carfax failed mid-Search. A Craigslist failure does not cause this, and the other
    way around: one Source failing keeps the other's Listings."""
    cancelled: bool = False
    """The Search was stopped early. `listings` holds what arrived before that."""


def run_search(
    search: Search, fetch: Fetch, on_batch: OnBatch | None = None, should_stop: ShouldStop | None = None
) -> SearchResult:
    """Validate and execute ``search`` against every Source it chooses, reporting each
    API page's Listings through ``on_batch`` as it arrives, from either Source.

    A Source failing or a stop leaves the Listings that arrived from it in the result;
    the other Source is unaffected. Curves are fitted to whatever arrived. The same cars
    can appear from both Sources: they are not matched or deduplicated against each other.
    """
    if not search.owner_types and not search.carfax:
        raise SearchError("choose at least one of Owner, Dealer, or Carfax")
    city = _city(search)

    listings: list[Listing] = []
    requests = 0
    error: ListingSourceError | None = None
    cancelled = False
    reported_totals: dict[OwnerType, int] = {}
    if search.owner_types:
        listing_search = ListingSearch(city, search.make, search.model, search.owner_types)
        source_result = search_listings(listing_search, fetch, on_batch, should_stop)
        listings += source_result.listings
        requests += source_result.requests
        error = source_result.error
        cancelled = cancelled or source_result.cancelled
        reported_totals = source_result.reported_totals

    carfax_listings: list[Listing] = []
    carfax_requests = 0
    carfax_error: ListingSourceError | None = None
    carfax_reported_total = 0
    if search.carfax:
        carfax_search = CarfaxSearch(city, search.make, search.model)
        carfax_result = search_carfax(carfax_search, fetch, on_batch, should_stop)
        carfax_listings = carfax_result.listings
        carfax_requests = carfax_result.requests
        carfax_error = carfax_result.error
        cancelled = cancelled or carfax_result.cancelled
        carfax_reported_total = carfax_result.reported_total

    listings += carfax_listings
    curves = {
        owner_type: fit_price_curve(
            (listing.mileage, listing.price) for listing in listings if listing.owner_type == owner_type
        )
        for owner_type in search.owner_types
    }
    carfax_curve = (
        fit_price_curve((listing.mileage, listing.price) for listing in carfax_listings) if search.carfax else None
    )
    return SearchResult(
        listings,
        curves,
        reported_totals,
        carfax_curve,
        carfax_reported_total,
        requests + carfax_requests,
        error,
        carfax_error,
        cancelled,
    )


def run_live_search(
    search: Search, fetch: Fetch | None = None, on_batch: OnBatch | None = None, should_stop: ShouldStop | None = None
) -> SearchResult:
    """Run `search` with `fetch`, or with live HttpFetchers (one per Source) that are
    closed afterwards."""
    if fetch is not None:
        return run_search(search, fetch, on_batch, should_stop)
    http = HttpFetcher()
    carfax_http = CarfaxHttpFetcher()

    def dispatch(url: str) -> str:
        return carfax_http(url) if "carfax.com" in url else http(url)

    try:
        return run_search(search, dispatch, on_batch, should_stop)
    finally:
        http.close()
        carfax_http.close()


def _city(search: Search) -> lookup.City:
    _required(search.state, "state")
    _required(search.city, "city")
    _required(search.make, "make")
    _required(search.model, "model")

    if not any(state.casefold() == search.state.casefold() for state in lookup.states()):
        raise SearchError(f"unknown state {search.state!r}")
    city = next((city for city in lookup.cities(search.state) if city.name.casefold() == search.city.casefold()), None)
    if city is None:
        raise SearchError(f"unknown city {search.city!r} in state {search.state!r}")
    if not any(make.casefold() == search.make.casefold() for make in lookup.makes()):
        raise SearchError(f"unknown make {search.make!r}")
    if not any(model.casefold() == search.model.casefold() for model in lookup.models(search.make)):
        raise SearchError(f"unknown model {search.model!r} for make {search.make!r}")
    return city


def _required(value: str, name: str) -> None:
    if not value.strip():
        raise SearchError(f"{name} is required")
