"""The Listing sources other than Craigslist, in one table keyed by `Source`.

Craigslist is not here: it keeps its Owner/Dealer split and its own wiring. Search,
chart and page read this table, so a new source is one entry plus its search function.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from craigslist import lookup
from craigslist.carfax import HttpFetcher as CarfaxHttpFetcher, Search as CarfaxSearch, search_carfax
from craigslist.listings import Fetch, Listing, ListingSourceError, Source

OnBatch = Callable[[list[Listing]], None]
"""Gets each API page's new Listings as the page arrives."""
ShouldStop = Callable[[], bool]
"""Asked before every API request; True means make no more."""


class SourceResults(Protocol):
    """What every source's search function returns."""

    @property
    def listings(self) -> list[Listing]: ...

    @property
    def reported_total(self) -> int: ...

    @property
    def requests(self) -> int: ...

    @property
    def error(self) -> ListingSourceError | None: ...

    @property
    def cancelled(self) -> bool: ...


class SourceFetcher(Protocol):
    """A live `Fetch` that holds a connection and is closed after the Search."""

    def __call__(self, url: str) -> str: ...

    def close(self) -> None: ...


SourceSearchFunction = Callable[[lookup.City, str, str, Fetch, OnBatch | None, ShouldStop | None], SourceResults]
"""(city, make, model, fetch, on_batch, should_stop) -> the source's results."""


@dataclass(frozen=True)
class SourceInfo:
    """Everything the Search, chart and page need to know about one source."""

    name: str
    """Shown on the checkbox, the legend, the status line and failure text."""
    color: str
    """Chart colour of its points and Price curve."""
    marker: str
    """ECharts symbol of its points. Hollow like a Dealer series, so only the shape differs."""
    search: SourceSearchFunction
    make_fetcher: Callable[[], SourceFetcher]
    """Makes the live fetcher for this source, so its requests get its own headers and pacing."""
    query_key: str
    """The URL query parameter and remembered-Search key for its checkbox."""
    default: bool = True
    """Whether its checkbox is ticked when the URL and the browser's memory say nothing."""


def _search_carfax(
    city: lookup.City, make: str, model: str, fetch: Fetch, on_batch: OnBatch | None, should_stop: ShouldStop | None
) -> SourceResults:
    return search_carfax(CarfaxSearch(city, make, model), fetch, on_batch, should_stop)


SOURCES: dict[Source, SourceInfo] = {
    Source.CARFAX: SourceInfo("Carfax", "#2ca02c", "circle", _search_carfax, CarfaxHttpFetcher, "carfax"),
}
"""In checkbox and series order."""


def choices_text(names: list[str]) -> str:
    """"Owner, Dealer, or Carfax": the choices of a Search, for messages."""
    return f"{', '.join(names[:-1])}, or {names[-1]}"
