"""Run a validated car search from lookup values through fitted price curves."""
from contextlib import ExitStack
from dataclasses import dataclass, field

from craigslist import lookup
from craigslist.curve import NotEnoughData, PriceCurve, fit_price_curve
from craigslist.listings import Fetch, HttpFetcher, Listing, ListingSourceError, OwnerType, Search as ListingSearch, Source, search_listings
from craigslist.sources import SOURCES, OnBatch, ShouldStop, choices_text


def _choices() -> str:
    return choices_text(["Owner", "Dealer", *(info.name for info in SOURCES.values())])


class SearchError(ValueError):
    """The caller supplied a state, city, make, or model outside the lookup tables, or a
    Search with none of Owner, Dealer, or another source chosen."""


@dataclass(frozen=True)
class Search:
    """The lookup values and Sources for one whole car search. `owner_types` chooses
    Craigslist Owner and/or Dealer listings; `sources` independently chooses the other
    sources (see `craigslist.sources`). At least one of them must be chosen."""

    state: str
    city: str
    make: str
    model: str
    owner_types: tuple[OwnerType, ...] = (OwnerType.OWNER, OwnerType.DEALER)
    sources: tuple[Source, ...] = tuple(SOURCES)


@dataclass(frozen=True)
class SearchResult:
    """Listings from every chosen Source, and one independently fitted Price curve per
    Craigslist owner type plus one per other source."""

    listings: list[Listing]
    curves: dict[OwnerType, PriceCurve | NotEnoughData]
    reported_totals: dict[OwnerType, int]
    source_curves: dict[Source, PriceCurve | NotEnoughData] = field(default_factory=dict)
    """One per other source the Search chose."""
    source_reported_totals: dict[Source, int] = field(default_factory=dict)
    requests: int = 0
    """API requests that got an answer, from every Source."""
    error: ListingSourceError | None = None
    """Craigslist failed mid-Search. `listings` holds what arrived from it before that."""
    source_errors: dict[Source, ListingSourceError] = field(default_factory=dict)
    """Other sources that failed mid-Search. A Craigslist failure does not cause these, and
    the other way around: one Source failing keeps the others' Listings."""
    cancelled: bool = False
    """The Search was stopped early. `listings` holds what arrived before that."""


def run_search(
    search: Search, fetch: Fetch, on_batch: OnBatch | None = None, should_stop: ShouldStop | None = None
) -> SearchResult:
    """Validate and execute ``search`` against every Source it chooses, reporting each
    API page's Listings through ``on_batch`` as it arrives, from any Source. ``fetch``
    serves every Source.

    A Source failing or a stop leaves the Listings that arrived from it in the result;
    the other Sources are unaffected. Curves are fitted to whatever arrived. The same cars
    can appear from several Sources: they are not matched or deduplicated against each other.
    """
    return _run(search, {}, fetch, on_batch, should_stop)


def run_live_search(
    search: Search, fetch: Fetch | None = None, on_batch: OnBatch | None = None, should_stop: ShouldStop | None = None
) -> SearchResult:
    """Run `search` with `fetch`, or with live HttpFetchers (one per Source) that are
    closed afterwards."""
    if fetch is not None:
        return run_search(search, fetch, on_batch, should_stop)
    with ExitStack() as stack:
        http = HttpFetcher()
        stack.callback(http.close)
        fetchers: dict[Source, Fetch] = {}
        for source in search.sources:
            fetcher = SOURCES[source].make_fetcher()
            stack.callback(fetcher.close)
            fetchers[source] = fetcher
        return _run(search, fetchers, http, on_batch, should_stop)


def _run(
    search: Search,
    fetchers: dict[Source, Fetch],
    fetch: Fetch,
    on_batch: OnBatch | None,
    should_stop: ShouldStop | None,
) -> SearchResult:
    """Run every chosen Source. A Source with no entry in `fetchers` uses `fetch`, which
    is also Craigslist's."""
    if not search.owner_types and not search.sources:
        raise SearchError(f"choose at least one of {_choices()}")
    city = _city(search)

    # --- Craigslist
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
        cancelled = source_result.cancelled
        reported_totals = source_result.reported_totals

    # --- Other Sources
    by_source: dict[Source, list[Listing]] = {}
    source_totals: dict[Source, int] = {}
    source_errors: dict[Source, ListingSourceError] = {}
    for source in search.sources:
        found = SOURCES[source].search(
            city, search.make, search.model, fetchers.get(source, fetch), on_batch, should_stop
        )
        by_source[source] = found.listings
        listings += found.listings
        requests += found.requests
        cancelled = cancelled or found.cancelled
        source_totals[source] = found.reported_total
        if found.error is not None:
            source_errors[source] = found.error

    # --- Price Curves
    curves = {
        owner_type: fit_price_curve(
            (listing.mileage, listing.price)
            for listing in listings
            if listing.source == Source.CRAIGSLIST and listing.owner_type == owner_type
        )
        for owner_type in search.owner_types
    }
    source_curves = {
        source: fit_price_curve((listing.mileage, listing.price) for listing in found)
        for source, found in by_source.items()
    }
    return SearchResult(
        listings, curves, reported_totals, source_curves, source_totals, requests, error, source_errors, cancelled
    )


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
