from dataclasses import replace

from craigslist.chart import (
    plotted_listings,
    DEALER_COLOR,
    FADED_COLOR,
    FADED_SIZE,
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
from craigslist.filters import Filters, Flag
from craigslist.curve import CurvePoint, NotEnoughData, PriceCurve
from craigslist.listings import Listing, ListingSourceError, OwnerType, Source
from craigslist.search import Search, SearchResult
from craigslist.sources import SOURCES

CARFAX = SOURCES[Source.CARFAX]
CARMAX = SOURCES[Source.CARMAX]


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


SEARCH = Search("CA", "Orange County", "Honda", "Civic", sources=())


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

    options = chart_options(Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,), sources=()), result)

    assert series_named(options, "Owner")["data"] == [[10_000, 10_000]]


def test_owner_types_not_searched_and_unfitted_curves_are_not_drawn():
    result = SearchResult([listing(1, OwnerType.OWNER, 10_000)], {OwnerType.OWNER: NotEnoughData("too few")}, {})

    options = chart_options(Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,), sources=()), result)

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
    search = Search("CA", "Orange County", "honda", "civic", (OwnerType.OWNER,), sources=())
    result = SearchResult([listing(1, OwnerType.OWNER, 1_000)], {}, {}, cancelled=True)

    assert status_text(search, result) == "Cancelled. 1 listings: 1 owner"
    assert progress_text(142) == "142 listings so far"


def test_a_stopped_search_with_no_listings_is_not_reported_as_empty():
    search = Search("CA", "Orange County", "honda", "civic", sources=())

    assert empty_message(search, SearchResult([], {}, {}, cancelled=True)) == "No listings arrived before the Search stopped."


OWNER_ONLY = Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,), sources=())


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
    fetched = Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,), sources=())

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

    options = chart_options(Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER,), sources=()), result)

    assert "tooltip" not in options
    assert all("tooltip" not in series for series in options["series"])
    assert series_named(options, "Owner")["symbolSize"] >= 12
    for axis in (options["xAxis"], options["yAxis"]):
        assert axis["axisPointer"]["show"] is True
        assert axis["axisPointer"]["label"]["show"] is True


# Carfax


CARFAX_SEARCH_WITH_OWNERS = Search("CA", "Orange County", "Honda", "Civic", sources=(Source.CARFAX,))
CARFAX_SEARCH = Search("CA", "Orange County", "Honda", "Civic", owner_types=(OwnerType.DEALER,), sources=(Source.CARFAX,))


def test_carfax_series_is_hollow_and_told_apart_from_dealer_by_source():
    result = SearchResult(
        [listing(1, OwnerType.DEALER, 80_000, 9_000), carfax_listing(2, 60_000, 11_000)], {}, {}
    )

    options = chart_options(CARFAX_SEARCH, result)

    dealer, carfax = series_named(options, "Dealer"), series_named(options, CARFAX.name)
    assert dealer["data"] == [[80_000, 9_000]]
    assert carfax["data"] == [[60_000, 11_000]]
    assert carfax["itemStyle"]["color"] == "transparent"
    assert carfax["itemStyle"]["borderColor"] == CARFAX.color
    assert CARFAX.color not in (OWNER_COLOR, DEALER_COLOR)


def test_carfax_curve_is_drawn_when_fitted():
    result = SearchResult(
        [carfax_listing(1, 10_000, 20_000)], {}, {}, source_curves={Source.CARFAX: curve((0, 25_000), (100_000, 10_000))}
    )

    options = chart_options(CARFAX_SEARCH, result)

    carfax_curve_series = series_named(options, f"{CARFAX.name} curve")
    assert carfax_curve_series["type"] == "line"
    assert carfax_curve_series["data"] == [[0, 25_000], [100_000, 10_000]]
    assert carfax_curve_series["lineStyle"]["color"] == CARFAX.color


def test_carfax_series_and_legend_are_absent_when_the_search_excludes_it():
    result = SearchResult([carfax_listing(1, 10_000)], {}, {})

    options = chart_options(Search("CA", "Orange County", "Honda", "Civic", owner_types=(), sources=()), result)

    assert all(series["name"] != CARFAX.name for series in options["series"])
    assert CARFAX.name not in options["legend"]["data"]


def test_status_text_includes_the_carfax_count():
    result = SearchResult([listing(1, OwnerType.DEALER, 1), carfax_listing(2, 1), carfax_listing(3, 1)], {}, {})

    assert status_text(CARFAX_SEARCH, result) == "3 listings: 1 dealer, 2 Carfax"


def test_curve_notes_includes_carfax_when_it_has_too_few_points():
    result = SearchResult([], {}, {}, source_curves={Source.CARFAX: NotEnoughData("too few")})

    assert curve_notes(CARFAX_SEARCH, result) == ["Too few Carfax listings for a curve"]


def test_default_range_includes_carfax_points_without_a_curve():
    result = SearchResult([carfax_listing(1, 0, 1_000), carfax_listing(2, 100, 2_000)], {}, {})

    view = default_range(Search("CA", "Orange County", "Honda", "Civic", owner_types=(), sources=(Source.CARFAX,)), result)

    assert view is not None
    assert view.max_price > 2_000 and view.min_price < 1_000


def test_default_range_uses_the_carfax_curve_when_fitted():
    result = SearchResult([], {}, {}, source_curves={Source.CARFAX: curve((10_000, 20_000), (110_000, 8_000))})

    view = default_range(Search("CA", "Orange County", "Honda", "Civic", owner_types=(), sources=(Source.CARFAX,)), result)

    assert view is not None
    assert (view.min_miles, view.max_miles) == (5_000, 115_000)


def test_failure_banner_reports_carfax_and_craigslist_failures_independently():
    craigslist_only = SearchResult([], {}, {}, requests=2, error=ListingSourceError("HTTP 429"))
    assert failure_banner(craigslist_only) == "Craigslist stopped answering after 2 requests. Showing 0 listings; there may be more."

    carfax_only = SearchResult([], {}, {}, source_errors={Source.CARFAX: ListingSourceError("HTTP 500")})
    assert failure_banner(carfax_only) == "Carfax stopped answering. Showing 0 listings; there may be more."

    both = SearchResult([], {}, {}, requests=1, error=ListingSourceError("HTTP 429"), source_errors={Source.CARFAX: ListingSourceError("HTTP 500")})
    assert both is not None and "Craigslist" in failure_banner(both) and "Carfax" in failure_banner(both)


def test_plotted_listings_includes_a_carfax_bucket():
    dealer, found = listing(1, OwnerType.DEALER, 80_000), carfax_listing(2, 60_000)
    result = SearchResult([dealer, found], {}, {})

    plotted = plotted_listings(CARFAX_SEARCH, result)

    assert plotted == {"Dealer": [dealer], CARFAX.name: [found]}


def test_pin_ring_matches_a_carfax_listing():
    found = carfax_listing(1, 60_000, price=15_000)
    result = SearchResult([found], {}, {})

    options = chart_options(CARFAX_SEARCH, result, pinned_id=found.id)

    assert options["series"][-1]["data"] == [[60_000, 15_000]]


def test_unfetched_message_names_carfax():
    fetched = Search("CA", "Orange County", "Honda", "Civic", owner_types=(), sources=())

    assert unfetched_message(fetched, [], [Source.CARFAX]) == "Search again to load carfax listings"
    assert unfetched_message(fetched, [], []) is None


# CarMax


def carmax_listing(post_id: int, mileage: int | None, price: int = 10_000) -> Listing:
    return Listing(
        f"carmax:{post_id}", Source.CARMAX, f"carmax car {post_id}", price, mileage,
        f"https://www.carmax.com/car/{post_id}", (), OwnerType.DEALER,
    )


CARMAX_SEARCH = Search("CA", "Orange County", "Honda", "Civic", owner_types=(OwnerType.DEALER,), sources=(Source.CARFAX, Source.CARMAX))


def test_carmax_series_is_hollow_with_its_own_colour_legend_entry_and_curve():
    result = SearchResult(
        [carfax_listing(1, 50_000, 9_000), carmax_listing(2, 60_000, 11_000)], {}, {},
        source_curves={Source.CARMAX: curve((0, 25_000), (100_000, 10_000))},
    )

    options = chart_options(CARMAX_SEARCH, result)

    carmax = series_named(options, CARMAX.name)
    assert carmax["data"] == [[60_000, 11_000]]
    assert carmax["itemStyle"]["color"] == "transparent"
    assert carmax["itemStyle"]["borderColor"] == CARMAX.color
    assert CARMAX.color not in (OWNER_COLOR, DEALER_COLOR, CARFAX.color)
    assert series_named(options, f"{CARMAX.name} curve")["lineStyle"]["color"] == CARMAX.color
    assert CARMAX.name in options["legend"]["data"]
    assert series_named(options, CARFAX.name)["data"] == [[50_000, 9_000]]


def test_carmax_series_is_absent_when_the_search_excludes_it():
    result = SearchResult([carmax_listing(1, 10_000)], {}, {})

    options = chart_options(CARFAX_SEARCH, result)

    assert all(series["name"] != CARMAX.name for series in options["series"])


def test_status_text_counts_carmax_listings_apart_from_carfax():
    result = SearchResult([carfax_listing(1, 1), carmax_listing(2, 1), carmax_listing(3, 1)], {}, {})

    assert status_text(CARMAX_SEARCH, result) == "3 listings: 0 dealer, 1 Carfax, 2 CarMax"


def test_failure_banner_names_carmax_and_keeps_the_others_listings():
    result = SearchResult([carfax_listing(1, 1)], {}, {}, source_errors={Source.CARMAX: ListingSourceError("HTTP 500")})

    assert failure_banner(result) == "CarMax stopped answering. Showing 1 listings; there may be more."


def test_curve_notes_names_carmax_when_it_has_too_few_points():
    result = SearchResult([], {}, {}, source_curves={Source.CARMAX: NotEnoughData("too few")})

    assert "Too few CarMax listings for a curve" in curve_notes(CARMAX_SEARCH, result)


def test_pin_ring_matches_a_carmax_listing():
    found = carmax_listing(1, 60_000, price=15_000)
    result = SearchResult([carfax_listing(1, 10_000, 5_000), found], {}, {})

    options = chart_options(CARMAX_SEARCH, result, pinned_id=found.id)

    assert options["series"][-1]["data"] == [[60_000, 15_000]]


# Display filters


ONE_OWNER = Filters(one_owner=Flag(on=True, include_unknown=False))


def filtered_result() -> SearchResult:
    return SearchResult(
        [
            replace(listing(1, OwnerType.OWNER, 50_000, 12_000), one_owner=True),
            listing(2, OwnerType.OWNER, 60_000, 11_000),
            replace(carfax_listing(3, 40_000, 15_000), one_owner=False),
            replace(carfax_listing(4, 70_000, 9_000), one_owner=True),
        ],
        {OwnerType.OWNER: curve((10_000, 20_000), (110_000, 8_000))},
        {},
        source_curves={Source.CARFAX: curve((0, 25_000), (100_000, 10_000))},
    )


def test_a_listing_failing_a_filter_is_a_small_solid_light_grey_dot():
    options = chart_options(CARFAX_SEARCH_WITH_OWNERS, filtered_result(), filters=ONE_OWNER)

    owner = series_named(options, "Owner")["data"]
    carfax = series_named(options, CARFAX.name)["data"]
    faded = [point for point in owner + carfax if isinstance(point, dict) and point.get("itemStyle")]
    assert len(faded) == 2
    for point in faded:
        assert point["symbol"] == "circle"
        assert point["symbolSize"] == FADED_SIZE < series_named(options, "Owner")["symbolSize"]
        assert point["itemStyle"] == {"color": FADED_COLOR, "borderWidth": 0}
    assert [70_000, 9_000] in carfax and [50_000, 12_000] in owner


def test_faded_points_are_drawn_first_and_still_map_back_to_their_listings():
    result = filtered_result()

    plotted = plotted_listings(CARFAX_SEARCH_WITH_OWNERS, result, ONE_OWNER)
    options = chart_options(CARFAX_SEARCH_WITH_OWNERS, result, filters=ONE_OWNER)

    assert [item.id for item in plotted[CARFAX.name]] == ["carfax:3", "carfax:4"]
    assert [item.id for item in plotted["Owner"]] == ["2", "1"]
    for name, rows in plotted.items():
        data = series_named(options, name)["data"]
        for row, point in zip(rows, data, strict=True):
            value = point["value"] if isinstance(point, dict) else point
            assert value == [row.mileage, row.price]


def test_curves_and_default_axes_are_the_same_with_or_without_filters():
    result = filtered_result()

    plain = chart_options(CARFAX_SEARCH_WITH_OWNERS, result)
    filtered = chart_options(CARFAX_SEARCH_WITH_OWNERS, result, filters=ONE_OWNER)

    for name in ("Owner curve", f"{CARFAX.name} curve"):
        assert series_named(plain, name) == series_named(filtered, name)
    assert plain["xAxis"] == filtered["xAxis"] and plain["yAxis"] == filtered["yAxis"]


def test_a_faded_outlier_keeps_its_edge_arrow_and_real_values():
    result = SearchResult(
        [replace(listing(1, OwnerType.OWNER, 60_000, 95_000), one_owner=False)],
        {OwnerType.OWNER: curve((10_000, 20_000), (110_000, 8_000))},
        {},
    )

    point = series_named(chart_options(OWNER_ONLY, result, filters=ONE_OWNER), "Owner")["data"][0]

    assert point["symbol"] == "arrow" and point["actual"] == [60_000, 95_000]
    assert point["itemStyle"]["color"] == FADED_COLOR


def test_a_pinned_faded_listing_is_still_ringed():
    result = filtered_result()

    options = chart_options(CARFAX_SEARCH_WITH_OWNERS, result, pinned_id="carfax:3", filters=ONE_OWNER)

    assert options["series"][-1]["data"] == [[40_000, 15_000]]


def test_the_status_line_counts_matching_and_faded_listings_only_while_filtering():
    result = filtered_result()

    assert status_text(CARFAX_SEARCH_WITH_OWNERS, result, ONE_OWNER) == (
        "4 listings: 2 owner, 0 dealer, 2 Carfax. Points on the chart: 2 match filters, 2 faded"
    )
    assert status_text(CARFAX_SEARCH_WITH_OWNERS, result) == "4 listings: 2 owner, 0 dealer, 2 Carfax"


def test_a_year_range_fades_other_years_and_leaves_curves_and_axes_alone():
    result = filtered_result()
    result = replace(result, listings=[replace(item, year=2015 + index) for index, item in enumerate(result.listings)])
    years = Filters(min_year=2016, max_year=2017)

    plain = chart_options(CARFAX_SEARCH_WITH_OWNERS, result)
    filtered = chart_options(CARFAX_SEARCH_WITH_OWNERS, result, filters=years)

    for name in ("Owner curve", f"{CARFAX.name} curve"):
        assert series_named(plain, name) == series_named(filtered, name)
    assert plain["xAxis"] == filtered["xAxis"] and plain["yAxis"] == filtered["yAxis"]
    faded = [point for name in ("Owner", CARFAX.name) for point in series_named(filtered, name)["data"] if isinstance(point, dict)]
    assert len(faded) == 2
    assert status_text(CARFAX_SEARCH_WITH_OWNERS, result, years).endswith("2 match filters, 2 faded")


def test_hiding_a_trim_fades_its_listings_and_leaves_curves_and_axes_alone():
    result = filtered_result()
    result = replace(result, listings=[replace(item, trim="Sport" if index % 2 else None) for index, item in enumerate(result.listings)])
    no_sport = Filters(hidden_trims=frozenset({"Sport"}))

    plain = chart_options(CARFAX_SEARCH_WITH_OWNERS, result)
    filtered = chart_options(CARFAX_SEARCH_WITH_OWNERS, result, filters=no_sport)

    for name in ("Owner curve", f"{CARFAX.name} curve"):
        assert series_named(plain, name) == series_named(filtered, name)
    assert plain["xAxis"] == filtered["xAxis"] and plain["yAxis"] == filtered["yAxis"]
    assert status_text(CARFAX_SEARCH_WITH_OWNERS, result, no_sport).endswith("2 match filters, 2 faded")


# Curve only


def test_curve_only_hides_a_sources_points_and_keeps_its_curve_and_legend_entry():
    result = filtered_result()
    hidden = frozenset({Source.CARFAX})

    plain = chart_options(CARFAX_SEARCH_WITH_OWNERS, result)
    options = chart_options(CARFAX_SEARCH_WITH_OWNERS, result, pinned_id="carfax:3", curve_only=hidden)

    assert series_named(options, CARFAX.name)["data"] == []
    assert CARFAX.name in options["legend"]["data"]
    assert series_named(options, f"{CARFAX.name} curve") == series_named(plain, f"{CARFAX.name} curve")
    assert f"{CARFAX.name} curve" in options["legend"]["data"]
    assert series_named(options, "Owner") == series_named(plain, "Owner")
    assert options["xAxis"] == plain["xAxis"] and options["yAxis"] == plain["yAxis"]
    assert options["series"][-1]["data"] == []  # a hidden point gets no ring
    assert plotted_listings(CARFAX_SEARCH_WITH_OWNERS, result, curve_only=hidden)[CARFAX.name] == []


def test_curve_only_hides_edge_arrows_too():
    result = SearchResult(
        [carfax_listing(1, 50_000, 12_000), carfax_listing(2, 60_000, 95_000)], {}, {},
        source_curves={Source.CARFAX: curve((10_000, 20_000), (110_000, 8_000))},
    )

    options = chart_options(CARFAX_SEARCH, result, curve_only=frozenset({Source.CARFAX}))

    assert not any(series["type"] == "scatter" and series["data"] for series in options["series"])


def test_curve_only_works_for_every_source():
    result = SearchResult([carfax_listing(1, 1_000), carmax_listing(2, 2_000)], {}, {})

    for source in SOURCES:
        options = chart_options(CARMAX_SEARCH, result, curve_only=frozenset({source}))
        drawn = {series["name"] for series in options["series"] if series["data"]}
        assert SOURCES[source].name not in drawn
        assert {info.name for other, info in SOURCES.items() if other != source} <= drawn
        assert SOURCES[source].name in options["legend"]["data"]


def test_curve_only_points_are_left_out_of_the_match_counts():
    result = filtered_result()

    text = status_text(CARFAX_SEARCH_WITH_OWNERS, result, ONE_OWNER, curve_only=frozenset({Source.CARFAX}))

    assert text.endswith("1 match filters, 1 faded")
