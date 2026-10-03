"""Display filters: which Listings the chart draws in full and which it fades.

A filter only changes how a point is drawn. Price curves and the default axes are still
fitted to every Listing, so filtering never makes a curve less accurate. No NiceGUI here,
so the rules test without a browser.
"""
from collections.abc import Iterable
from dataclasses import dataclass

from craigslist.listings import Listing


@dataclass(frozen=True)
class Flag:
    """One yes/no filter, such as "one owner". Off passes every Listing."""

    on: bool = False
    include_unknown: bool = True
    """Pass a Listing whose Source does not report this attribute."""

    def passes(self, value: bool | None) -> bool:
        if not self.on:
            return True
        if value is None:
            return self.include_unknown
        return value


@dataclass(frozen=True)
class Filters:
    """The display filters the Search page holds. The defaults fade nothing."""

    one_owner: Flag = Flag()
    no_accidents: Flag = Flag()
    price_dropped: Flag = Flag()
    min_year: int | None = None
    """None leaves the range open below; the page sets it only when narrower than the results."""
    max_year: int | None = None
    include_unknown_year: bool = True
    """Pass a Listing whose model year could not be read."""
    hidden_trims: frozenset[str | None] = frozenset()
    """The trim chips deselected, by exact text; None is the Unknown chip. Empty fades nothing."""

    def passes(self, listing: Listing) -> bool:
        """Whether `listing` is drawn in full rather than faded."""
        return (
            self.one_owner.passes(listing.one_owner)
            and self.no_accidents.passes(listing.no_accidents)
            and self.price_dropped.passes(listing.price_dropped)
            and self._year_passes(listing.year)
            and listing.trim not in self.hidden_trims
        )

    def _year_passes(self, year: int | None) -> bool:
        if year is None:
            return self.include_unknown_year
        return (self.min_year is None or year >= self.min_year) and (self.max_year is None or year <= self.max_year)

    def active(self) -> bool:
        """Whether any filter can fade a Listing."""
        flags = any(flag.on for flag in (self.one_owner, self.no_accidents, self.price_dropped))
        years = self.min_year is not None or self.max_year is not None or not self.include_unknown_year
        return flags or years or bool(self.hidden_trims)


def match_counts(listings: Iterable[Listing], filters: Filters) -> tuple[int, int]:
    """How many of `listings` pass `filters`, and how many are faded."""
    passed = [filters.passes(listing) for listing in listings]
    return sum(passed), len(passed) - sum(passed)


def year_options(listings: Iterable[Listing]) -> list[int]:
    """The distinct known model years in `listings`, oldest first, for the year range controls."""
    return sorted({listing.year for listing in listings if listing.year is not None})


def year_bounds(chosen_min: int | None, chosen_max: int | None, options: list[int]) -> tuple[int | None, int | None]:
    """`Filters.min_year` and `max_year` for the chosen years: None at either end of
    `options`, so the full range fades no known year."""
    low = chosen_min if options and chosen_min is not None and chosen_min != options[0] else None
    high = chosen_max if options and chosen_max is not None and chosen_max != options[-1] else None
    return low, high


def trim_options(listings: Iterable[Listing]) -> list[str]:
    """The distinct known trims in `listings`, sorted, one chip each. Grouped by exact text:
    Carfax and CarMax may spell one trim differently, and merging them would be a guess."""
    return sorted({listing.trim for listing in listings if listing.trim})
