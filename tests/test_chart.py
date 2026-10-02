from craigslist.chart import (
    plotted_listings,
    CARFAX_COLOR,
    CARFAX_NAME,
    DEALER_COLOR,
    OWNER_COLOR,
    chart_options,
    curve_notes,
    default_range,
    empty_message,
    failure_banner,
    progress_text,
    status_text,
    unfetched_message,
)
from craigslist.curve import CurvePoint, NotEnoughData, PriceCurve
from craigslist.listings import Listing, ListingSourceError, OwnerType, Source
from craigslist.search import Search, SearchResult


def listing(post_id: int, owner_type: OwnerType, mileage: int | None, price: int = 10_000) -> Listing:
    return Listing(
        str(post_id), Source.CRAIGSLIST, f"car {post_id}", price, mileage, f"https://example.org/{post_id}", (), owner_type
    )


def carfax_listing(post_id: int, mileage: int | None, price: int = 10_000) -> Listing:
    return Listing(
        f"carfax:{post_id}", Source.CARFAX, f"carfax car {post_id}", price, mileage,
        f"https://www.carfax.com/vehicle/{post_id}", (), OwnerType.DEALER,
    )


def curve(*points: tuple[float, float]) -> PriceCurve:
    miles = [point[0] for point in points]
    prices = [point[1] for point in points]
    return PriceCurve(
        tuple(CurvePoint(m, p) for m, p in points), 1.0, 1.0, 1.0, min(miles), max(miles), min(prices), max(prices)
    )


SEARCH = Search("CA", "Orange County", "Honda", "Civic", carfax=False)


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

    options = chart_options(Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,), carfax=False), result)

    assert series_named(options, "Owner")["data"] == [[10_000, 10_000]]


def test_owner_types_not_searched_and_unfitted_curves_are_not_drawn():
    result = SearchResult([listing(1, OwnerType.OWNER, 10_000)], {OwnerType.OWNER: NotEnoughData("too few")}, {})

    options = chart_options(Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,), carfax=False), result)

    assert [series["name"] for series in options["series"]] == ["Owner", "Pinned listing"]


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
    search = Search("CA", "Orange County", "honda", "civic", (OwnerType.OWNER,), carfax=False)
    result = SearchResult([listing(1, OwnerType.OWNER, 1_000)], {}, {}, cancelled=True)

    assert status_text(search, result) == "Cancelled. 1 listings: 1 owner"
    assert progress_text(142) == "142 listings so far"


def test_a_stopped_search_with_no_listings_is_not_reported_as_empty():
    search = Search("CA", "Orange County", "honda", "civic", carfax=False)

    assert empty_message(search, SearchResult([], {}, {}, cancelled=True)) == "No listings arrived before the Search stopped."


OWNER_ONLY = Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,), carfax=False)


def test_default_range_comes_from_the_kept_points_with_padding():
    result = SearchResult(
        [listing(1, OwnerType.OWNER, 50_000, 12_000), listing(2, OwnerType.OWNER, 60_000, 95_000)],
        {OwnerType.OWNER: curve((10_000, 20_000), (110_000, 8_000))},
        {},
    )

    view = default_range(OWNER_ONLY, result)

    assert view is not None
    assert (view.min_miles, view.max_miles) == (5_000, 115_000)
    assert (view.min_price, view.max_price) == (7_400, 20_600)


def test_default_range_uses_every_point_of_an_owner_type_without_a_curve():
    result = SearchResult(
        [listing(1, OwnerType.OWNER, 0, 1_000), listing(2, OwnerType.OWNER, 100, 2_000)],
        {OwnerType.OWNER: NotEnoughData("too few")},
        {},
    )

    view = default_range(OWNER_ONLY, result)

    assert view is not None
    assert view.max_price > 2_000 and view.min_price < 1_000


def test_default_range_is_absent_with_nothing_to_plot():
    assert default_range(OWNER_ONLY, SearchResult([listing(1, OwnerType.OWNER, None)], {}, {})) is None


def test_outliers_are_drawn_as_arrows_at_the_chart_edge_and_keep_their_real_values():
    result = SearchResult(
        [
            listing(1, OwnerType.OWNER, 50_000, 12_000),
            listing(2, OwnerType.OWNER, 60_000, 95_000),
            listing(3, OwnerType.OWNER, 60_000, 100),
            listing(4, OwnerType.OWNER, 500_000, 12_000),
        ],
        {OwnerType.OWNER: curve((10_000, 20_000), (110_000, 8_000))},
        {},
    )

    options = chart_options(OWNER_ONLY, result)

    assert options["yAxis"]["max"] == 20_600 and options["yAxis"]["min"] == 7_400
    assert options["xAxis"]["max"] == 115_000
    data = series_named(options, "Owner")["data"]
    assert data[0] == [50_000, 12_000]
    assert data[1]["value"] == [60_000, 20_600] and data[1]["actual"] == [60_000, 95_000]
    assert data[1]["symbol"] == "arrow" and data[1]["symbolRotate"] == 0
    assert data[2]["value"] == [60_000, 7_400] and data[2]["symbolRotate"] == 180
    assert data[3]["value"] == [115_000, 12_000] and data[3]["symbolRotate"] == -90


def test_axes_are_left_to_the_chart_when_there_is_nothing_to_fit():
    options = chart_options(OWNER_ONLY, SearchResult([], {}, {}))

    assert "min" not in options["xAxis"] and "max" not in options["yAxis"]


def test_too_few_points_for_a_curve_gets_a_note_per_owner_type():
    result = SearchResult(
        [listing(1, OwnerType.OWNER, 1_000)],
        {OwnerType.OWNER: NotEnoughData("too few"), OwnerType.DEALER: curve((0, 1), (1, 1))},
        {},
    )

    assert curve_notes(SEARCH, result) == ["Too few owner listings for a curve"]
    assert curve_notes(SEARCH, SearchResult([], {}, {})) == []


def test_a_type_that_was_not_fetched_gets_a_search_again_message():
    fetched = Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,), carfax=False)

    assert unfetched_message(fetched, [OwnerType.OWNER, OwnerType.DEALER]) == "Search again to load dealer listings"
    assert unfetched_message(fetched, [OwnerType.OWNER]) is None
    assert unfetched_message(fetched, []) is None


def test_plotted_listings_map_each_series_index_back_to_its_listing():
    first, second, no_miles, dealer = (
        listing(1, OwnerType.OWNER, 50_000),
        listing(2, OwnerType.OWNER, 60_000),
        listing(3, OwnerType.OWNER, None),
        listing(4, OwnerType.DEALER, 80_000),
    )
    result = SearchResult([first, no_miles, second, dealer], {}, {})

    plotted = plotted_listings(SEARCH, result)

    assert plotted == {"Owner": [first, second], "Dealer": [dealer]}
    assert series_named(chart_options(SEARCH, result), "Owner")["data"] == [[50_000, 10_000], [60_000, 10_000]]


def test_the_pinned_listing_is_ringed_by_a_last_series_that_is_always_present():
    pinned = listing(2, OwnerType.OWNER, 60_000, price=12_000)
    result = SearchResult([listing(1, OwnerType.OWNER, 50_000), pinned], {}, {})

    ringed = chart_options(SEARCH, result, pinned_id="2")
    plain = chart_options(SEARCH, result)

    assert ringed["series"][-1]["data"] == [[60_000, 12_000]]
    assert plain["series"][-1]["data"] == []
    assert len(ringed["series"]) == len(plain["series"])
    assert "Pinned listing" not in ringed["legend"]["data"]


def test_a_pinned_listing_without_mileage_gets_no_ring():
    result = SearchResult([listing(1, OwnerType.OWNER, None)], {}, {})

    assert chart_options(SEARCH, result, pinned_id="1")["series"][-1]["data"] == []


def test_points_have_no_tooltip_and_the_cursor_draws_a_line_to_each_axis():
    result = SearchResult([listing(1, OwnerType.OWNER, 50_000, 12_000)], {}, {OwnerType.OWNER: 1})

    options = chart_options(Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,), carfax=False), result)

    assert "tooltip" not in options
    assert all("tooltip" not in series for series in options["series"])
    assert series_named(options, "Owner")["symbolSize"] >= 12
    for axis in (options["xAxis"], options["yAxis"]):
        assert axis["axisPointer"]["show"] is True
        assert axis["axisPointer"]["label"]["show"] is True


# Carfax


CARFAX_SEARCH = Search("CA", "Orange County", "Honda", "Civic", owner_types=(OwnerType.DEALER,), carfax=True)


def test_carfax_series_is_hollow_and_told_apart_from_dealer_by_source():
    result = SearchResult(
        [listing(1, OwnerType.DEALER, 80_000, 9_000), carfax_listing(2, 60_000, 11_000)], {}, {}
    )

    options = chart_options(CARFAX_SEARCH, result)

    dealer, carfax = series_named(options, "Dealer"), series_named(options, CARFAX_NAME)
    assert dealer["data"] == [[80_000, 9_000]]
    assert carfax["data"] == [[60_000, 11_000]]
    assert carfax["itemStyle"]["color"] == "transparent"
    assert carfax["itemStyle"]["borderColor"] == CARFAX_COLOR
    assert CARFAX_COLOR not in (OWNER_COLOR, DEALER_COLOR)


def test_carfax_curve_is_drawn_when_fitted():
    result = SearchResult(
        [carfax_listing(1, 10_000, 20_000)], {}, {}, carfax_curve=curve((0, 25_000), (100_000, 10_000))
    )

    options = chart_options(CARFAX_SEARCH, result)

    carfax_curve_series = series_named(options, f"{CARFAX_NAME} curve")
    assert carfax_curve_series["type"] == "line"
    assert carfax_curve_series["data"] == [[0, 25_000], [100_000, 10_000]]
    assert carfax_curve_series["lineStyle"]["color"] == CARFAX_COLOR


def test_carfax_series_and_legend_are_absent_when_the_search_excludes_it():
    result = SearchResult([carfax_listing(1, 10_000)], {}, {})

    options = chart_options(Search("CA", "Orange County", "Honda", "Civic", owner_types=(), carfax=False), result)

    assert all(series["name"] != CARFAX_NAME for series in options["series"])
    assert CARFAX_NAME not in options["legend"]["data"]


def test_status_text_includes_the_carfax_count():
    result = SearchResult([listing(1, OwnerType.DEALER, 1), carfax_listing(2, 1), carfax_listing(3, 1)], {}, {})

    assert status_text(CARFAX_SEARCH, result) == "3 listings: 1 dealer, 2 Carfax"


def test_curve_notes_includes_carfax_when_it_has_too_few_points():
    result = SearchResult([], {}, {}, carfax_curve=NotEnoughData("too few"))

    assert curve_notes(CARFAX_SEARCH, result) == ["Too few Carfax listings for a curve"]


def test_default_range_includes_carfax_points_without_a_curve():
    result = SearchResult([carfax_listing(1, 0, 1_000), carfax_listing(2, 100, 2_000)], {}, {})

    view = default_range(Search("CA", "Orange County", "Honda", "Civic", owner_types=(), carfax=True), result)

    assert view is not None
    assert view.max_price > 2_000 and view.min_price < 1_000


def test_default_range_uses_the_carfax_curve_when_fitted():
    result = SearchResult([], {}, {}, carfax_curve=curve((10_000, 20_000), (110_000, 8_000)))

    view = default_range(Search("CA", "Orange County", "Honda", "Civic", owner_types=(), carfax=True), result)

    assert view is not None
    assert (view.min_miles, view.max_miles) == (5_000, 115_000)


def test_failure_banner_reports_carfax_and_craigslist_failures_independently():
    craigslist_only = SearchResult([], {}, {}, requests=2, error=ListingSourceError("HTTP 429"))
    assert failure_banner(craigslist_only) == "Craigslist stopped answering after 2 requests. Showing 0 listings; there may be more."

    carfax_only = SearchResult([], {}, {}, carfax_error=ListingSourceError("HTTP 500"))
    assert failure_banner(carfax_only) == "Carfax stopped answering. Showing 0 listings; there may be more."

    both = SearchResult([], {}, {}, requests=1, error=ListingSourceError("HTTP 429"), carfax_error=ListingSourceError("HTTP 500"))
    assert both is not None and "Craigslist" in failure_banner(both) and "Carfax" in failure_banner(both)


def test_plotted_listings_includes_a_carfax_bucket():
    dealer, found = listing(1, OwnerType.DEALER, 80_000), carfax_listing(2, 60_000)
    result = SearchResult([dealer, found], {}, {})

    plotted = plotted_listings(CARFAX_SEARCH, result)

    assert plotted == {"Dealer": [dealer], CARFAX_NAME: [found]}


def test_pin_ring_matches_a_carfax_listing():
    found = carfax_listing(1, 60_000, price=15_000)
    result = SearchResult([found], {}, {})

    options = chart_options(CARFAX_SEARCH, result, pinned_id=found.id)

    assert options["series"][-1]["data"] == [[60_000, 15_000]]


def test_unfetched_message_names_carfax():
    fetched = Search("CA", "Orange County", "Honda", "Civic", owner_types=(), carfax=False)

    assert unfetched_message(fetched, [], wanted_carfax=True) == "Search again to load carfax listings"
    assert unfetched_message(fetched, [], wanted_carfax=False) is None
