from datetime import UTC, datetime

from craigslist.listings import Listing, OwnerType
from craigslist.preview import (
    EMPTY_TEXT,
    LOADING_TEXT,
    detail_lines,
    load_details,
    no_mileage_listings,
    no_mileage_note,
    preview_content,
)
from craigslist.search import Search, SearchResult

SEARCH = Search("CA", "Orange County", "Honda", "Civic")


def listing(
    post_id: int = 1,
    owner_type: OwnerType = OwnerType.OWNER,
    mileage: int | None = 50_000,
    image_codes: tuple[str, ...] = (),
    posted: datetime | None = None,
    location: str | None = None,
) -> Listing:
    return Listing(
        post_id, f"car {post_id}", 12_500, mileage, f"https://example.org/{post_id}", image_codes, owner_type, posted, location
    )


DETAIL_PAGE = """<div class="postinginfo">post id: 123</div>
<div class="attrgroup"><span class="attr"><span class="labl">fuel:</span><span class="valu">gas</span></span></div>"""


def test_content_from_a_full_listing():
    full = listing(
        image_codes=("00a_abc", "00b_def"),
        posted=datetime(2026, 9, 28, 14, 3, tzinfo=UTC),
        location="Irvine",
    )

    content = preview_content(full)

    assert content.title == "car 1"
    assert content.price == "$12,500"
    assert content.mileage == "50,000 mi"
    assert content.owner == "Owner"
    assert content.posted == "Posted 2026-09-28 14:03 UTC"
    assert content.location == "Irvine"
    assert content.image == "https://images.craigslist.org/00a_abc_600x450.jpg"
    assert content.url == "https://example.org/1"


def test_content_without_photo_posted_time_or_location_leaves_them_out():
    content = preview_content(listing(owner_type=OwnerType.DEALER))

    assert content.owner == "Dealer"
    assert content.image is None
    assert content.posted is None
    assert content.location is None


def test_content_without_mileage_says_so():
    assert preview_content(listing(mileage=None)).mileage == "Mileage not listed"


def test_no_mileage_listings_follow_the_shown_owner_types():
    owner, dealer = listing(1, mileage=None), listing(2, OwnerType.DEALER, mileage=None)
    result = SearchResult([owner, dealer, listing(3)], {}, {})

    assert no_mileage_listings(SEARCH, result) == [owner, dealer]
    assert no_mileage_listings(Search("CA", "Orange County", "Honda", "Civic", (OwnerType.DEALER,)), result) == [dealer]


def test_no_mileage_note_counts_and_is_absent_for_none():
    assert no_mileage_note(7) == "7 listings have no mileage"
    assert no_mileage_note(1) == "1 listing has no mileage"
    assert no_mileage_note(0) is None


def test_detail_lines_cover_loading_empty_and_found():
    assert detail_lines(None) == LOADING_TEXT == "Loading details from the listing..."
    assert detail_lines({}) == EMPTY_TEXT == "No details available"
    assert detail_lines({"fuel": "gas"}) == ["fuel: gas"]


def test_load_details_reads_the_listing_page_with_the_given_fetcher():
    fetched = []

    def fake_fetch(url: str) -> str:
        fetched.append(url)
        return DETAIL_PAGE

    assert load_details(listing(), fake_fetch) == {"fuel": "gas"}
    assert fetched == ["https://example.org/1"]


def test_load_details_gives_nothing_when_the_fetch_fails():
    def failing_fetch(url: str) -> str:
        raise OSError("blocked")

    assert load_details(listing(), failing_fetch) == {}
