from craigslist.chart import (
    DEALER_COLOR,
    OWNER_COLOR,
    chart_options,
    empty_message,
    failure_banner,
    progress_text,
    status_text,
)
from craigslist.curve import CurvePoint, NotEnoughData, PriceCurve
from craigslist.listings import Listing, ListingSourceError, OwnerType
from craigslist.search import Search, SearchResult


def listing(post_id: int, owner_type: OwnerType, mileage: int | None, price: int = 10_000) -> Listing:
    return Listing(post_id, f"car {post_id}", price, mileage, f"https://example.org/{post_id}", (), owner_type)


def curve(*points: tuple[float, float]) -> PriceCurve:
    return PriceCurve(tuple(CurvePoint(miles, price) for miles, price in points), 1.0, 1.0, 1.0)


SEARCH = Search("CA", "Orange County", "Honda", "Civic")


def series_named(options: dict, name: str) -> dict:
    return next(series for series in options["series"] if series["name"] == name)


def test_points_and_curves_are_drawn_per_owner_type_in_matching_colours():
    result = SearchResult(
        [listing(1, OwnerType.OWNER, 50_000, 12_000), listing(2, OwnerType.DEALER, 80_000, 9_000)],
        {OwnerType.OWNER: curve((0, 20_000), (100_000, 8_000)), OwnerType.DEALER: curve((0, 18_000), (90_000, 7_000))},
        {OwnerType.OWNER: 1, OwnerType.DEALER: 1},
    )

    options = chart_options(SEARCH, result)

    owner = series_named(options, "Owner")
    dealer = series_named(options, "Dealer")
    assert owner["type"] == dealer["type"] == "scatter"
    assert owner["data"] == [[50_000, 12_000]]
    assert dealer["data"] == [[80_000, 9_000]]
    assert owner["itemStyle"]["color"] == OWNER_COLOR
    assert dealer["itemStyle"]["color"] == "transparent"
    assert dealer["itemStyle"]["borderColor"] == DEALER_COLOR
    owner_curve = series_named(options, "Owner curve")
    dealer_curve = series_named(options, "Dealer curve")
    assert owner_curve["type"] == dealer_curve["type"] == "line"
    assert owner_curve["data"] == [[0, 20_000], [100_000, 8_000]]
    assert owner_curve["lineStyle"]["color"] == OWNER_COLOR
    assert dealer_curve["lineStyle"]["color"] == DEALER_COLOR


def test_listings_without_mileage_are_left_off_the_chart():
    result = SearchResult(
        [listing(1, OwnerType.OWNER, None), listing(2, OwnerType.OWNER, 10_000)],
        {OwnerType.OWNER: NotEnoughData("too few")},
        {OwnerType.OWNER: 2},
    )

    options = chart_options(Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,)), result)

    assert series_named(options, "Owner")["data"] == [[10_000, 10_000]]


def test_owner_types_not_searched_and_unfitted_curves_are_not_drawn():
    result = SearchResult([listing(1, OwnerType.OWNER, 10_000)], {OwnerType.OWNER: NotEnoughData("too few")}, {})

    options = chart_options(Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,)), result)

    assert [series["name"] for series in options["series"]] == ["Owner"]


def test_zero_results_give_a_message_naming_the_search():
    result = SearchResult([], {OwnerType.OWNER: NotEnoughData("none"), OwnerType.DEALER: NotEnoughData("none")}, {})

    assert empty_message(SEARCH, result) == "No Honda Civic listings in Orange County."


def test_listings_that_all_lack_mileage_give_a_message_too():
    result = SearchResult([listing(1, OwnerType.OWNER, None)], {OwnerType.OWNER: NotEnoughData("none")}, {})

    assert empty_message(SEARCH, result) == "None of the 1 Honda Civic listings in Orange County have mileage."


def test_plottable_results_give_no_message():
    result = SearchResult([listing(1, OwnerType.OWNER, 1_000)], {OwnerType.OWNER: NotEnoughData("none")}, {})

    assert empty_message(SEARCH, result) is None


def test_status_counts_listings_per_owner_type():
    result = SearchResult(
        [listing(1, OwnerType.OWNER, 1), listing(2, OwnerType.DEALER, 1), listing(3, OwnerType.DEALER, None)], {}, {}
    )

    assert status_text(SEARCH, result) == "3 listings: 1 owner, 2 dealer"


def test_failure_banner_names_the_requests_and_listings():
    result = SearchResult([listing(1, OwnerType.OWNER, 1_000)] * 3, {}, {}, requests=4, error=ListingSourceError("HTTP 429"))

    assert failure_banner(result) == (
        "Craigslist stopped answering after 4 requests. Showing 3 listings; there may be more."
    )


def test_failure_banner_is_absent_without_an_error():
    assert failure_banner(SearchResult([], {}, {}, requests=2)) is None


def test_cancelled_search_says_so_in_the_status_line():
    search = Search("CA", "Orange County", "honda", "civic", (OwnerType.OWNER,))
    result = SearchResult([listing(1, OwnerType.OWNER, 1_000)], {}, {}, cancelled=True)

    assert status_text(search, result) == "Cancelled. 1 listings: 1 owner"
    assert progress_text(142) == "142 listings so far"


def test_a_stopped_search_with_no_listings_is_not_reported_as_empty():
    search = Search("CA", "Orange County", "honda", "civic")

    assert empty_message(search, SearchResult([], {}, {}, cancelled=True)) == "No listings arrived before the Search stopped."
