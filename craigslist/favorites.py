"""Favorites: Listings a browser saved, kept as JSON snapshots, built without NiceGUI.

A saved Listing is a snapshot of every Listing field, the Search it came from and when it
was saved, so it shows in Preview even when no later Search finds it. The page keeps the
list in `app.storage.user` under `FAVORITES_KEY`, newest first; these helpers take any
mapping and a key, so another list of saved Listings can use them under its own key.
Identity is `Listing.id`: the same car on two Sources is two entries.
"""
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Any

from loguru import logger

from craigslist.listings import Listing, OwnerType, Source
from craigslist.preview import UNKNOWN_MILEAGE
from craigslist.search import Search
from craigslist.sources import SOURCES

FAVORITES_KEY = "favorites"
"""The `app.storage.user` key holding this browser's favorites, a list of `saved_to_json` dicts."""
EMPTY_TEXT = "Nothing saved yet. Hover or click a point, then ☆ Save in the Preview panel."
_LISTING_FIELDS = {field.name for field in fields(Listing)}


@dataclass(frozen=True)
class SavedSearch:
    """Where a saved Listing was found: the Search's place and car, not its Sources."""

    state: str
    city: str
    make: str
    model: str

    @classmethod
    def of(cls, search: Search) -> "SavedSearch":
        return cls(search.state, search.city, search.make, search.model)


@dataclass(frozen=True)
class SavedListing:
    """One saved Listing: its snapshot, the Search it came from, and when it was saved."""

    listing: Listing
    search: SavedSearch | None
    """None when the Listing was saved with no Search on the page that found it."""
    saved: datetime
    """Timezone-aware."""


@dataclass(frozen=True)
class FavoriteRow:
    """The text and photo of one drawer row."""

    image: str | None
    """A hotlinked photo URL, never downloaded, or None for no photo."""
    title: str
    price_mileage: str
    source: str
    """Source name and saved date: "CarMax  ·  saved 2026-10-01 09:30"."""


def listing_to_json(listing: Listing) -> dict[str, Any]:
    """Every Listing field as JSON-ready values: enums as their values, `posted` as ISO text."""
    data = asdict(listing)
    data["source"] = listing.source.value
    data["owner_type"] = listing.owner_type.value
    data["images"] = list(listing.images)
    data["posted"] = listing.posted.isoformat() if listing.posted is not None else None
    return data


def listing_from_json(data: Mapping[str, Any]) -> Listing:
    """The inverse of `listing_to_json`. Unknown keys are ignored and missing optional fields
    take their defaults; a missing required field raises KeyError or TypeError."""
    values = {key: value for key, value in data.items() if key in _LISTING_FIELDS}
    values["source"] = Source(data["source"])
    values["owner_type"] = OwnerType(data["owner_type"])
    values["images"] = tuple(data["images"])
    if values.get("posted") is not None:
        values["posted"] = datetime.fromisoformat(values["posted"])
    return Listing(**values)


def saved_to_json(entry: SavedListing) -> dict[str, Any]:
    return {
        "listing": listing_to_json(entry.listing),
        "search": asdict(entry.search) if entry.search is not None else None,
        "saved": entry.saved.isoformat(),
    }


def saved_from_json(data: Mapping[str, Any]) -> SavedListing:
    """The inverse of `saved_to_json`. Raises KeyError, TypeError or ValueError when unreadable."""
    search = data["search"]
    return SavedListing(
        listing_from_json(data["listing"]),
        SavedSearch(**search) if search is not None else None,
        datetime.fromisoformat(data["saved"]),
    )


def read_saved(storage: Mapping[str, Any], key: str) -> list[SavedListing]:
    """The saved Listings under `key`, in stored order. An unreadable entry is logged and skipped."""
    entries = []
    for data in storage.get(key) or []:
        try:
            entries.append(saved_from_json(data))
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            logger.warning("Skipped an unreadable saved Listing under {!r}: {!r}", key, error)
    return entries


def write_saved(storage: MutableMapping[str, Any], key: str, entries: Sequence[SavedListing]) -> None:
    storage[key] = [saved_to_json(entry) for entry in entries]


def add_saved(
    entries: Sequence[SavedListing], listing: Listing, search: SavedSearch | None, saved: datetime
) -> list[SavedListing]:
    """`entries` with `listing` first, newest first. Unchanged when its id is already there."""
    if listing.id in saved_ids(entries):
        return list(entries)
    return [SavedListing(listing, search, saved), *entries]


def remove_saved(entries: Sequence[SavedListing], listing_id: str) -> list[SavedListing]:
    return [entry for entry in entries if entry.listing.id != listing_id]


def saved_ids(entries: Sequence[SavedListing]) -> frozenset[str]:
    return frozenset(entry.listing.id for entry in entries)


def button_text(count: int) -> str:
    """The toolbar button that opens the Favorites drawer."""
    return f"★ Favorites ({count})"


def source_name(listing: Listing) -> str:
    """"Carfax", "CarMax", or "Craigslist owner"/"Craigslist dealer"."""
    if listing.source == Source.CRAIGSLIST:
        return f"Craigslist {listing.owner_type}"
    return SOURCES[listing.source].name


def favorite_row(entry: SavedListing) -> FavoriteRow:
    """A drawer row. The saved date is in the server's local time."""
    listing = entry.listing
    mileage = f"{listing.mileage:,} mi" if listing.mileage is not None else UNKNOWN_MILEAGE
    return FavoriteRow(
        image=listing.images[0] if listing.images else None,
        title=listing.title,
        price_mileage=f"${listing.price:,}  |  {mileage}",
        source=f"{source_name(listing)}  ·  saved {entry.saved.astimezone():%Y-%m-%d %H:%M}",
    )
