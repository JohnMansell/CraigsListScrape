"""ECharts options for the Search page chart, built from a SearchResult.

Plain dictionaries only, so the chart can be tested without a browser.
"""
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from craigslist.curve import NotEnoughData, PriceCurve
from craigslist.listings import Listing, OwnerType, Source
from craigslist.search import Search, SearchResult

OWNER_COLOR = "#2f7ed8"
DEALER_COLOR = "#e8743b"
CARFAX_COLOR = "#2ca02c"
AXIS_COLOR = "#8a8a8a"
"""Mid grey, readable in light and dark mode."""

PADDING = 0.05
"""Share of the kept range added on each side of the default view."""
POINT_SIZE = 12
"""Big enough to hover and click easily; the Preview panel shows the details, so no tooltip."""
ARROW_SIZE = 14
PIN_COLOR = "#d62728"
PIN_SIZE = 24
PIN_NAME = "Pinned listing"
CARFAX_NAME = "Carfax"
"""Its own series: a Carfax Listing always has OwnerType.DEALER, so it is told apart from
a Craigslist Dealer Listing by Source, not by owner type."""

COLORS = {OwnerType.OWNER: OWNER_COLOR, OwnerType.DEALER: DEALER_COLOR}
NAMES = {OwnerType.OWNER: "Owner", OwnerType.DEALER: "Dealer"}


@dataclass(frozen=True)
class ChartRange:
    """The axis limits of the default view."""

    min_miles: float
    max_miles: float
    min_price: float
    max_price: float


def chart_options(search: Search, result: SearchResult, pinned_id: str | None = None) -> dict[str, Any]:
    """A scatter per searched owner type, owner filled and dealer hollow, plus each fitted curve.

    Listings without mileage are left off. The axes fit the points the curves kept, so a
    price outlier does not squash the rest; points outside are drawn as arrows at the edge.
    Dragging on the chart zooms, and the toolbox restores the default view. The Pinned
    Listing, when it is on the chart, is ringed by a last series that is always present
    (empty when nothing is pinned), so pinning never changes the series count.
    """
    view = default_range(search, result)
    series: list[dict[str, Any]] = []
    for owner_type in search.owner_types:
        series.append(_points(owner_type, result, view))
    if search.carfax:
        series.append(_carfax_points(result, view))
    for owner_type in search.owner_types:
        curve = result.curves.get(owner_type)
        if isinstance(curve, PriceCurve):
            series.append(_curve(owner_type, curve))
    if search.carfax and isinstance(result.carfax_curve, PriceCurve):
        series.append(_carfax_curve(result.carfax_curve))
    legend = [str(item["name"]) for item in series]
    series.append(_pin_ring(search, result, view, pinned_id))
    return {
        "animation": False,
        "backgroundColor": "transparent",
        "textStyle": {"color": AXIS_COLOR},
        "grid": {"left": 70, "right": 30, "top": 40, "bottom": 50},
        "legend": {"top": 0, "data": legend, "textStyle": {"color": AXIS_COLOR}},
        "toolbox": {"right": 10, "feature": {"dataZoom": {"filterMode": "none"}, "restore": {}}},
        "xAxis": _axis("Mileage", name_gap=35, limits=(view.min_miles, view.max_miles) if view else None),
        "yAxis": _axis("Price ($)", name_gap=55, limits=(view.min_price, view.max_price) if view else None),
        "series": series,
    }


def plotted_listings(search: Search, result: SearchResult) -> dict[str, list[Listing]]:
    """For each point series name, the Listings behind its points in data order.

    A chart event gives a series name and a data index; this maps them back to a Listing.
    """
    mapping = {
        NAMES[owner_type]: [
            listing
            for listing in result.listings
            if listing.source == Source.CRAIGSLIST and listing.owner_type == owner_type and listing.mileage is not None
        ]
        for owner_type in search.owner_types
    }
    if search.carfax:
        mapping[CARFAX_NAME] = [
            listing for listing in result.listings if listing.source == Source.CARFAX and listing.mileage is not None
        ]
    return mapping


def default_range(search: Search, result: SearchResult) -> ChartRange | None:
    """The default view: the points every shown curve kept, padded, or None with no points.

    An owner type with no fitted curve has no kept points, so all its plottable points count.
    """
    miles: list[float] = []
    prices: list[float] = []
    for owner_type in search.owner_types:
        curve = result.curves.get(owner_type)
        if isinstance(curve, PriceCurve):
            miles += [curve.min_miles, curve.max_miles]
            prices += [curve.min_price, curve.max_price]
            continue
        for listing in result.listings:
            if listing.source == Source.CRAIGSLIST and listing.owner_type == owner_type and listing.mileage is not None:
                miles.append(listing.mileage)
                prices.append(listing.price)
    if search.carfax:
        if isinstance(result.carfax_curve, PriceCurve):
            miles += [result.carfax_curve.min_miles, result.carfax_curve.max_miles]
            prices += [result.carfax_curve.min_price, result.carfax_curve.max_price]
        else:
            for listing in result.listings:
                if listing.source == Source.CARFAX and listing.mileage is not None:
                    miles.append(listing.mileage)
                    prices.append(listing.price)
    if not miles:
        return None
    return ChartRange(*_padded(miles), *_padded(prices))


def curve_notes(search: Search, result: SearchResult) -> list[str]:
    """One note for each searched owner type, and Carfax, whose points were too few for a curve."""
    notes = [
        f"Too few {owner_type} listings for a curve"
        for owner_type in search.owner_types
        if isinstance(result.curves.get(owner_type), NotEnoughData)
    ]
    if search.carfax and isinstance(result.carfax_curve, NotEnoughData):
        notes.append("Too few Carfax listings for a curve")
    return notes


def empty_message(search: Search, result: SearchResult) -> str | None:
    """What to show in place of the chart when there is nothing to plot, else None."""
    car = f"{search.make} {search.model}"
    if not result.listings and (result.error or result.cancelled):
        return "No listings arrived before the Search stopped."
    if not result.listings:
        return f"No {car} listings in {search.city}."
    if all(listing.mileage is None for listing in result.listings):
        return f"None of the {len(result.listings)} {car} listings in {search.city} have mileage."
    return None


def unfetched_message(fetched: Search, wanted: Collection[OwnerType], wanted_carfax: bool = False) -> str | None:
    """"Search again to load dealer listings" when a wanted owner type, or Carfax, was
    not fetched, else None."""
    missing = [NAMES[t].lower() for t in wanted if t not in fetched.owner_types]
    if wanted_carfax and not fetched.carfax:
        missing.append("carfax")
    return f"Search again to load {' and '.join(missing)} listings" if missing else None


def status_text(search: Search, result: SearchResult) -> str:
    parts = [
        f"{sum(listing.source == Source.CRAIGSLIST and listing.owner_type == owner_type for listing in result.listings)} "
        f"{owner_type}"
        for owner_type in search.owner_types
    ]
    if search.carfax:
        parts.append(f"{sum(listing.source == Source.CARFAX for listing in result.listings)} Carfax")
    text = f"{len(result.listings)} listings: {', '.join(parts)}"
    return f"Cancelled. {text}" if result.cancelled else text


def progress_text(count: int) -> str:
    """The running count while a Search is still fetching."""
    return f"{count} listings so far"


def failure_banner(result: SearchResult) -> str | None:
    """The banner for a Search a Source failed partway through, else None. A Craigslist
    failure does not hide Carfax's Listings, and the other way around."""
    failures = []
    if result.error is not None:
        requests = "1 request" if result.requests == 1 else f"{result.requests} requests"
        failures.append(f"Craigslist stopped answering after {requests}.")
    if result.carfax_error is not None:
        failures.append("Carfax stopped answering.")
    if not failures:
        return None
    return " ".join(failures) + f" Showing {len(result.listings)} listings; there may be more."


def _padded(values: list[float]) -> tuple[float, float]:
    low, high = min(values), max(values)
    pad = (high - low) * PADDING or max(abs(high) * PADDING, 1.0)
    return max(0.0, low - pad), high + pad


def _edge_point(miles: float, price: float, view: ChartRange) -> dict[str, Any] | None:
    """An arrow at the chart edge for a point outside `view`, else None."""
    x = min(max(miles, view.min_miles), view.max_miles)
    y = min(max(price, view.min_price), view.max_price)
    if (x, y) == (miles, price):
        return None
    if price > view.max_price:
        rotation = 0
    elif price < view.min_price:
        rotation = 180
    elif miles > view.max_miles:
        rotation = -90
    else:
        rotation = 90
    return {
        "value": [x, y],
        "actual": [miles, price],
        "symbol": "arrow",
        "symbolSize": ARROW_SIZE,
        "symbolRotate": rotation,
    }


def _points(owner_type: OwnerType, result: SearchResult, view: ChartRange | None) -> dict[str, Any]:
    color = COLORS[owner_type]
    item_style: dict[str, Any]
    if owner_type == OwnerType.OWNER:
        item_style = {"color": color}
    else:
        item_style = {"color": "transparent", "borderColor": color, "borderWidth": 1.5}
    return {
        "name": NAMES[owner_type],
        "type": "scatter",
        "symbolSize": POINT_SIZE,
        "itemStyle": item_style,
        "data": [
            (view and _edge_point(listing.mileage, listing.price, view)) or [listing.mileage, listing.price]
            for listing in result.listings
            if listing.source == Source.CRAIGSLIST and listing.owner_type == owner_type and listing.mileage is not None
        ],
    }


def _carfax_points(result: SearchResult, view: ChartRange | None) -> dict[str, Any]:
    """Hollow like a Dealer series, its own colour: Carfax's own series, told apart from
    Craigslist's by Source rather than owner type."""
    return {
        "name": CARFAX_NAME,
        "type": "scatter",
        "symbolSize": POINT_SIZE,
        "itemStyle": {"color": "transparent", "borderColor": CARFAX_COLOR, "borderWidth": 1.5},
        "data": [
            (view and _edge_point(listing.mileage, listing.price, view)) or [listing.mileage, listing.price]
            for listing in result.listings
            if listing.source == Source.CARFAX and listing.mileage is not None
        ],
    }


def _pin_ring(search: Search, result: SearchResult, view: ChartRange | None, pinned_id: str | None) -> dict[str, Any]:
    """A hollow ring around the Pinned Listing's point, or no data when it is not plotted."""
    data: list[list[float]] = []
    for listings in plotted_listings(search, result).values():
        for listing in listings:
            if listing.id == pinned_id and listing.mileage is not None:
                edge = view and _edge_point(listing.mileage, listing.price, view)
                data.append(edge["value"] if edge else [listing.mileage, listing.price])
    return {
        "name": PIN_NAME,
        "type": "scatter",
        "silent": True,
        "z": 10,
        "symbol": "circle",
        "symbolSize": PIN_SIZE,
        "itemStyle": {"color": "transparent", "borderColor": PIN_COLOR, "borderWidth": 2.5},
        "data": data,
    }


def _curve(owner_type: OwnerType, curve: PriceCurve) -> dict[str, Any]:
    color = COLORS[owner_type]
    return {
        "name": f"{NAMES[owner_type]} curve",
        "type": "line",
        "showSymbol": False,
        "itemStyle": {"color": color},
        "lineStyle": {"color": color, "width": 2},
        "data": [[point.miles, point.price] for point in curve.points],
    }


def _carfax_curve(curve: PriceCurve) -> dict[str, Any]:
    return {
        "name": f"{CARFAX_NAME} curve",
        "type": "line",
        "showSymbol": False,
        "itemStyle": {"color": CARFAX_COLOR},
        "lineStyle": {"color": CARFAX_COLOR, "width": 2},
        "data": [[point.miles, point.price] for point in curve.points],
    }


def _axis(name: str, name_gap: int, limits: tuple[float, float] | None) -> dict[str, Any]:
    fixed = {} if limits is None else {"min": limits[0], "max": limits[1]}
    return {
        **fixed,
        "type": "value",
        "name": name,
        "nameLocation": "middle",
        "nameGap": name_gap,
        "scale": True,
        "axisLine": {"lineStyle": {"color": AXIS_COLOR}},
        "splitLine": {"lineStyle": {"color": AXIS_COLOR, "opacity": 0.2}},
        # A line from the cursor to this axis, labelled with the value there.
        "axisPointer": {
            "show": True,
            "snap": False,
            "lineStyle": {"color": AXIS_COLOR, "type": "dashed"},
            "label": {"show": True, "precision": 0},
        },
    }
