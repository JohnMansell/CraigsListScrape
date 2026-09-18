"""Run a validated car search from lookup values through fitted price curves."""
from collections.abc import Callable
from dataclasses import dataclass

from craigslist import lookup
from craigslist.curve import NotEnoughData, PriceCurve, fit_price_curve
from craigslist.listings import Fetch, Listing, OwnerType, Search as ListingSearch, search_listings


Progress = Callable[[], None]
"""Called once immediately before each Craigslist API request."""


class SearchError(ValueError):
    """The caller supplied a state, city, make, or model outside the lookup tables."""


@dataclass(frozen=True)
class Search:
    """The lookup values and seller types for one whole car search."""

    state: str
    city: str
    make: str
    model: str
    owner_types: tuple[OwnerType, ...] = (OwnerType.OWNER, OwnerType.DEALER)


@dataclass(frozen=True)
class SearchResult:
    """Listings and one independently fitted price curve for each seller type."""

    listings: list[Listing]
    curves: dict[OwnerType, PriceCurve | NotEnoughData]
    reported_totals: dict[OwnerType, int]


def run_search(search: Search, fetch: Fetch, progress: Progress | None = None) -> SearchResult:
    """Validate and execute ``search``, reporting each API request through ``progress``."""
    listing_search = _listing_search(search)

    def tracked_fetch(url: str) -> str:
        if progress:
            progress()
        return fetch(url)

    source_result = search_listings(listing_search, tracked_fetch)
    curves = {
        owner_type: fit_price_curve(
            (listing.mileage, listing.price) for listing in source_result.listings if listing.owner_type == owner_type
        )
        for owner_type in search.owner_types
    }
    return SearchResult(source_result.listings, curves, source_result.reported_totals)


def _listing_search(search: Search) -> ListingSearch:
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
    return ListingSearch(city, search.make, search.model, search.owner_types)


def _required(value: str, name: str) -> None:
    if not value.strip():
        raise SearchError(f"{name} is required")
