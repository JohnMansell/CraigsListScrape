"""What the Preview panel shows for a Listing, built without NiceGUI so it tests without a browser."""
from dataclasses import dataclass
from datetime import UTC, datetime

from craigslist.listings import Fetch, HttpFetcher, Listing, image_url, listing_attributes
from craigslist.search import Search, SearchResult

LOADING_TEXT = "Loading details from the listing..."
EMPTY_TEXT = "No details available"
IDLE_TEXT = "Hover a point to preview it. Click a point to pin it."
UNKNOWN_MILEAGE = "Mileage not listed"


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


def preview_content(listing: Listing) -> PreviewContent:
    """The panel content for `listing`. Missing posted time, location, or photo become None."""
    return PreviewContent(
        title=listing.title,
        price=f"${listing.price:,}",
        mileage=f"{listing.mileage:,} mi" if listing.mileage is not None else UNKNOWN_MILEAGE,
        owner=str(listing.owner_type).capitalize(),
        posted=posted_text(listing.posted),
        location=listing.location or None,
        image=image_url(listing.image_codes[0]) if listing.image_codes else None,
        url=listing.url,
    )


def posted_text(posted: datetime | None) -> str | None:
    """A posted time as "Posted 2026-09-28 14:03 UTC", or None when unknown."""
    if posted is None:
        return None
    return "Posted " + posted.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def no_mileage_listings(shown: Search, result: SearchResult) -> list[Listing]:
    """The Listings of the shown owner types that are left off the chart for having no mileage."""
    return [
        listing
        for listing in result.listings
        if listing.mileage is None and listing.owner_type in shown.owner_types
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

    With no `fetch`, uses a live HttpFetcher that is closed afterwards.
    """
    if fetch is not None:
        return listing_attributes(listing, fetch)
    http = HttpFetcher()
    try:
        return listing_attributes(listing, http)
    finally:
        http.close()
