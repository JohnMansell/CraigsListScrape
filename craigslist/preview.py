"""What the Preview panel shows for a Listing, built without NiceGUI so it tests without a browser."""
from dataclasses import dataclass
from datetime import UTC, datetime

from craigslist.listings import Fetch, HttpFetcher, Listing, Source, listing_attributes
from craigslist.search import Search, SearchResult

LOADING_TEXT = "Loading details from the listing..."
EMPTY_TEXT = "No details available"
IDLE_TEXT = "Hover a point to preview it. Click a point to pin it."
UNKNOWN_MILEAGE = "Mileage not listed"
LINK_LABELS = {Source.CRAIGSLIST: "Open on Craigslist", Source.CARFAX: "Open on Carfax", Source.CARMAX: "Open on CarMax"}


@dataclass(frozen=True)
class PreviewContent:
    """The text and photo the panel draws for one Listing."""

    title: str
    price: str
    mileage: str
    owner: str
    posted: str | None
    """None when the response did not carry a posted time."""
    location: str | None
    """None when unknown, so the panel leaves the line out."""
    image: str | None
    """A hotlinked 600x450 photo URL, or None so the panel draws no image block."""
    url: str
    link_label: str
    """"Open on Craigslist", "Open on Carfax" or "Open on CarMax"."""
    dealer: str | None
    """The dealer's name (CarMax: the store). None for a Craigslist Listing."""
    owners: str | None
    """"One owner" or "Previous owners". Carfax; CarMax only ever "One owner". None for Craigslist."""
    accidents: str | None
    """"No accidents reported" or "Accident reported". Carfax only; None otherwise."""
    price_drop: str | None
    """A note when Carfax's price history or CarMax's `hasPriceDrop` shows a drop. None otherwise."""
    year: str | None = None
    """"Model year 2015", or None when the year is unknown."""
    trim: str | None = None
    """"Trim: Sport", or None when the trim is unknown."""


def preview_content(listing: Listing) -> PreviewContent:
    """The panel content for `listing`. Missing posted time, location, or photo become None."""
    return PreviewContent(
        title=listing.title,
        price=f"${listing.price:,}",
        mileage=f"{listing.mileage:,} mi" if listing.mileage is not None else UNKNOWN_MILEAGE,
        owner=str(listing.owner_type).capitalize(),
        posted=_dated_text(listing),
        location=listing.location or None,
        image=listing.images[0] if listing.images else None,
        url=listing.url,
        link_label=LINK_LABELS[listing.source],
        dealer=listing.dealer,
        owners=_owners_text(listing.one_owner),
        accidents=_accidents_text(listing.no_accidents),
        price_drop="Price dropped" if listing.price_dropped else None,
        year=f"Model year {listing.year}" if listing.year is not None else None,
        trim=f"Trim: {listing.trim}" if listing.trim else None,
    )


def _dated_text(listing: Listing) -> str | None:
    """Craigslist and Carfax "Posted ..."; CarMax's date is when the car went on sale."""
    text = posted_text(listing.posted)
    if text is not None and listing.source == Source.CARMAX:
        return "On sale since" + text.removeprefix("Posted")
    return text


def _owners_text(one_owner: bool | None) -> str | None:
    if one_owner is None:
        return None
    return "One owner" if one_owner else "Previous owners"


def _accidents_text(no_accidents: bool | None) -> str | None:
    if no_accidents is None:
        return None
    return "No accidents reported" if no_accidents else "Accident reported"


def posted_text(posted: datetime | None) -> str | None:
    """A posted time as "Posted 2026-09-28 14:03 UTC", or None when unknown."""
    if posted is None:
        return None
    return "Posted " + posted.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def save_label(saved: bool) -> str:
    """The Save toggle beside the "Open on ..." link, showing whether the Listing is a favorite."""
    return "★ Saved" if saved else "☆ Save"


def no_mileage_listings(shown: Search, result: SearchResult) -> list[Listing]:
    """The Listings of the shown Sources that are left off the chart for having no mileage."""
    return [
        listing
        for listing in result.listings
        if listing.mileage is None and (
            (listing.source == Source.CRAIGSLIST and listing.owner_type in shown.owner_types)
            or (listing.source != Source.CRAIGSLIST and listing.source in shown.sources)
        )
    ]


def no_mileage_note(count: int) -> str | None:
    """"7 listings have no mileage", or None when there are none."""
    if count == 0:
        return None
    return "1 listing has no mileage" if count == 1 else f"{count} listings have no mileage"


def detail_lines(details: dict[str, str] | None) -> list[str] | str:
    """The Listing details as "key: value" lines, LOADING_TEXT while `details` is None, EMPTY_TEXT when empty."""
    if details is None:
        return LOADING_TEXT
    if not details:
        return EMPTY_TEXT
    return [f"{key}: {value}" for key, value in details.items()]


def load_details(listing: Listing, fetch: Fetch | None = None) -> dict[str, str]:
    """Fetch `listing`'s detail page attributes. Blocking, so run it off the UI thread.

    With no `fetch`, uses a live HttpFetcher that is closed afterwards. Only Craigslist
    Listings have a detail page to fetch: another source's Listing already carries every
    detail Preview shows (`www.carfax.com` is DataDome-blocked and CarMax's robots.txt disallows
    `/car/*`), so this never requests it.
    """
    if listing.source != Source.CRAIGSLIST:
        return {}
    if fetch is not None:
        return listing_attributes(listing, fetch)
    http = HttpFetcher()
    try:
        return listing_attributes(listing, http)
    finally:
        http.close()
