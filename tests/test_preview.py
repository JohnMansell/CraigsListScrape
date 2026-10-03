from dataclasses import replace
from datetime import UTC, datetime

from craigslist.listings import Listing, OwnerType, Source
from craigslist.preview import (
    EMPTY_TEXT,
    LOADING_TEXT,
    detail_lines,
    hide_label,
    hide_tooltip,
    key_action,
    key_target,
    load_details,
    no_mileage_listings,
    no_mileage_note,
    preview_content,
    save_label,
    save_tooltip,
)
from craigslist.search import Search, SearchResult

SEARCH = Search("CA", "Orange County", "Honda", "Civic", sources=())


def listing(
    post_id: int = 1,
    owner_type: OwnerType = OwnerType.OWNER,
    mileage: int | None = 50_000,
    images: tuple[str, ...] = (),
    posted: datetime | None = None,
    location: str | None = None,
) -> Listing:
    return Listing(
        str(post_id), Source.CRAIGSLIST, f"car {post_id}", 12_500, mileage, f"https://example.org/{post_id}",
        images, owner_type, posted, location,
    )


def carfax_listing(
    post_id: int = 1,
    mileage: int | None = 50_000,
    dealer: str | None = "Honda of Vallejo",
    one_owner: bool | None = True,
    no_accidents: bool | None = True,
    price_dropped: bool | None = True,
) -> Listing:
    return Listing(
        f"carfax:{post_id}", Source.CARFAX, f"car {post_id}", 12_500, mileage,
        f"https://www.carfax.com/vehicle/{post_id}", (), OwnerType.DEALER, None, "Vallejo, CA",
        dealer, one_owner, no_accidents, price_dropped,
    )


DETAIL_PAGE = """<div class="postinginfo">post id: 123</div>
<div class="attrgroup"><span class="attr"><span class="labl">fuel:</span><span class="valu">gas</span></span></div>"""


def test_content_from_a_full_listing():
    full = listing(
        images=("https://images.craigslist.org/00a_abc_600x450.jpg", "https://images.craigslist.org/00b_def_600x450.jpg"),
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


# Carfax


def test_content_from_a_carfax_listing_shows_its_extras():
    content = preview_content(carfax_listing())

    assert content.link_label == "Open on Carfax"
    assert content.dealer == "Honda of Vallejo"
    assert content.owners == "One owner"
    assert content.accidents == "No accidents reported"
    assert content.price_drop == "Price dropped"


def test_content_from_a_craigslist_listing_has_no_carfax_extras():
    content = preview_content(listing())

    assert content.link_label == "Open on Craigslist"
    assert content.dealer is None
    assert content.owners is None
    assert content.accidents is None
    assert content.price_drop is None


def test_content_describes_multiple_owners_and_a_reported_accident():
    content = preview_content(carfax_listing(one_owner=False, no_accidents=False, price_dropped=False))

    assert content.owners == "Previous owners"
    assert content.accidents == "Accident reported"
    assert content.price_drop is None


def test_load_details_never_fetches_a_carfax_listing():
    def fetch(url: str) -> str:
        raise AssertionError("must not fetch a Carfax Listing: www.carfax.com is DataDome-blocked")

    assert load_details(carfax_listing(), fetch) == {}


def test_no_mileage_listings_includes_carfax_when_shown():
    owner, found = listing(1, mileage=None), carfax_listing(2, mileage=None)
    result = SearchResult([owner, found, listing(3)], {}, {})

    shown = Search("CA", "Orange County", "Honda", "Civic", owner_types=(OwnerType.OWNER,), sources=(Source.CARFAX,))
    assert no_mileage_listings(shown, result) == [owner, found]

    not_shown = Search("CA", "Orange County", "Honda", "Civic", owner_types=(OwnerType.OWNER,), sources=())
    assert no_mileage_listings(not_shown, result) == [owner]


def test_no_mileage_listings_excludes_a_carfax_dealer_from_the_craigslist_dealer_bucket():
    # Both carry OwnerType.DEALER; only Source tells them apart.
    found = carfax_listing(1, mileage=None)
    result = SearchResult([found], {}, {})

    shown = Search("CA", "Orange County", "Honda", "Civic", owner_types=(OwnerType.DEALER,), sources=())
    assert no_mileage_listings(shown, result) == []


# CarMax


def carmax_listing(
    stock: int = 1,
    mileage: int | None = 50_000,
    one_owner: bool | None = True,
    price_dropped: bool | None = True,
    posted: datetime | None = datetime(2026, 9, 28, 14, 3, tzinfo=UTC),
) -> Listing:
    return Listing(
        f"carmax:{stock}", Source.CARMAX, f"car {stock}", 12_500, mileage,
        f"https://www.carmax.com/car/{stock}", ("https://img.carmax.com/hero.jpg",), OwnerType.DEALER, posted,
        "Vallejo, CA", "CarMax Vallejo", one_owner, None, price_dropped,
    )


def test_content_from_a_carmax_listing_shows_store_city_on_sale_date_and_price_drop():
    content = preview_content(carmax_listing())

    assert content.link_label == "Open on CarMax"
    assert content.url == "https://www.carmax.com/car/1"
    assert content.dealer == "CarMax Vallejo"
    assert content.location == "Vallejo, CA"
    assert content.posted == "On sale since 2026-09-28 14:03 UTC"
    assert content.price_drop == "Price dropped"
    assert content.owners == "One owner"
    assert content.accidents is None
    assert content.image == "https://img.carmax.com/hero.jpg"


def test_a_carmax_listing_says_one_owner_only_when_known():
    content = preview_content(carmax_listing(one_owner=None, price_dropped=None, posted=None))

    assert content.owners is None
    assert content.price_drop is None
    assert content.posted is None


def test_load_details_never_fetches_a_carmax_listing():
    def fetch(url: str) -> str:
        raise AssertionError("must not fetch a CarMax Listing: robots.txt disallows /car/*")

    assert load_details(carmax_listing(), fetch) == {}


def test_no_mileage_listings_includes_carmax_when_shown():
    found = carmax_listing(1, mileage=None)
    result = SearchResult([found], {}, {})

    shown = Search("CA", "Orange County", "Honda", "Civic", owner_types=(), sources=(Source.CARMAX,))
    assert no_mileage_listings(shown, result) == [found]
    assert no_mileage_listings(SEARCH, result) == []


def test_content_shows_the_model_year_when_known():
    assert preview_content(replace(listing(), year=2015)).year == "Model year 2015"
    assert preview_content(listing()).year is None


def test_content_shows_the_trim_when_known():
    assert preview_content(replace(carfax_listing(), trim="Sport")).trim == "Trim: Sport"
    assert preview_content(listing()).trim is None


def test_the_save_button_shows_whether_the_listing_is_saved():
    assert save_label(False) == "☆ Save"
    assert save_label(True) == "★ Saved"


def test_no_mileage_listings_leave_out_hidden_listings():
    first, second = listing(1, mileage=None), listing(2, mileage=None)
    result = SearchResult([first, second], {}, {})

    assert no_mileage_listings(SEARCH, result, hidden_ids={"1"}) == [second]


def test_hide_label_shows_whether_the_listing_is_hidden():
    assert hide_label(False) == "Hide"
    assert hide_label(True) == "Unhide"


def test_the_save_and_hide_tooltips_name_their_keys():
    assert save_tooltip(False) == "Save (F)"
    assert save_tooltip(True) == "Remove from favorites (F)"
    assert hide_tooltip(False) == "Hide (H)"
    assert hide_tooltip(True) == "Unhide (H)"


def test_f_saves_and_h_hides_in_either_case():
    assert key_action("f") == "save"
    assert key_action("F") == "save"
    assert key_action("h") == "hide"
    assert key_action("H") == "hide"
    assert key_action("g") is None
    assert key_action("Enter") is None


def test_a_key_held_with_ctrl_alt_or_meta_does_nothing():
    assert key_action("f", ctrl=True) is None
    assert key_action("h", alt=True) is None
    assert key_action("f", meta=True) is None


def test_a_hotkey_acts_on_the_pinned_listing_before_the_hovered_one():
    pinned, hovered = listing(1), listing(2)
    assert key_target(pinned, hovered) is pinned
    assert key_target(None, hovered) is hovered
    assert key_target(None, None) is None
