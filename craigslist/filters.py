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

    def passes(self, listing: Listing) -> bool:
        """Whether `listing` is drawn in full rather than faded."""
        return (
            self.one_owner.passes(listing.one_owner)
            and self.no_accidents.passes(listing.no_accidents)
            and self.price_dropped.passes(listing.price_dropped)
        )

    def active(self) -> bool:
        """Whether any filter can fade a Listing."""
        return any(flag.on for flag in (self.one_owner, self.no_accidents, self.price_dropped))


def match_counts(listings: Iterable[Listing], filters: Filters) -> tuple[int, int]:
    """How many of `listings` pass `filters`, and how many are faded."""
    passed = [filters.passes(listing) for listing in listings]
    return sum(passed), len(passed) - sum(passed)
