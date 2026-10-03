"""ECharts options for the Search page chart, built from a SearchResult.

Plain dictionaries only, so the chart can be tested without a browser.
"""
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from craigslist.curve import NotEnoughData, PriceCurve
from craigslist.filters import Filters, hidden_count, match_counts, unhidden
from craigslist.listings import Listing, OwnerType, Source
from craigslist.search import Search, SearchResult
from craigslist.sources import SOURCES

OWNER_COLOR = "#2f7ed8"
DEALER_COLOR = "#e8743b"
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
FAVORITE_COLOR = "#f5b301"
FAVORITE_BORDER = "#7a5900"
FAVORITE_SIZE = 26
FAVORITES_NAME = "Favorites"
FADED_COLOR = "#c8c8c8"
"""A Listing failing a display filter: light grey, the same for every Source and Owner type."""
FADED_SIZE = 7

COLORS = {OwnerType.OWNER: OWNER_COLOR, OwnerType.DEALER: DEALER_COLOR}
NAMES = {OwnerType.OWNER: "Owner", OwnerType.DEALER: "Dealer"}


@dataclass(frozen=True)
class ChartRange:
    """The axis limits of the default view."""

    min_miles: float
    max_miles: float
    min_price: float
    max_price: float


def chart_options(
    search: Search,
    result: SearchResult,
    pinned_id: str | None = None,
    filters: Filters = Filters(),
    curve_only: Collection[Source] = frozenset(),
    favorite_ids: Collection[str] = frozenset(),
    hidden_ids: Collection[str] = frozenset(),
) -> dict[str, Any]:
    """A scatter per searched owner type, owner filled and dealer hollow, plus each fitted curve.

    Listings without mileage are left off. The axes fit the points the curves kept, so a
    price outlier does not squash the rest; points outside are drawn as arrows at the edge.
    A Listing failing `filters` is a small light-grey dot; curves and axes ignore `filters`.
    A Source in `curve_only` keeps an empty points series, so its legend entry stays beside
    its curve. A Listing whose id is in `hidden_ids` is not drawn at all; like `filters`, that
    leaves curves and axes alone. Dragging on the chart zooms, and the toolbox restores the default view. The
    Pinned Listing, when it is on the chart, is ringed by a last series that is always present
    (empty when nothing is pinned), so pinning never changes the series count. Before it, a
    gold pin marks each drawn, unfaded point whose id is in `favorite_ids`; also always present.
    """
    view = default_range(search, result)
    plotted = plotted_listings(search, result, filters, curve_only, hidden_ids)
    series: list[dict[str, Any]] = []
    for owner_type in search.owner_types:
        series.append(_points(owner_type, plotted[NAMES[owner_type]], view, filters))
    for source in search.sources:
        series.append(_source_points(source, plotted[SOURCES[source].name], view, filters))
    for owner_type in search.owner_types:
        curve = result.curves.get(owner_type)
        if isinstance(curve, PriceCurve):
            series.append(_curve(owner_type, curve))
    for source in search.sources:
        source_curve = result.source_curves.get(source)
        if isinstance(source_curve, PriceCurve):
            series.append(_source_curve(source, source_curve))
    legend = [str(item["name"]) for item in series]
    series.append(_favorite_pins(plotted, view, filters, favorite_ids))
    series.append(_pin_ring(plotted, view, pinned_id))
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


def plotted_listings(
    search: Search,
    result: SearchResult,
    filters: Filters = Filters(),
    curve_only: Collection[Source] = frozenset(),
    hidden_ids: Collection[str] = frozenset(),
) -> dict[str, list[Listing]]:
    """For each point series name, the Listings behind its points in data order.

    A chart event gives a series name and a data index; this maps them back to a Listing.
    Listings failing `filters` come first in each series, so the full points draw over them.
    A Source in `curve_only` draws no points, so its list is empty. Hidden Listings are left out.
    """
    mapping = {
        NAMES[owner_type]: [
            listing
            for listing in result.listings
            if listing.source == Source.CRAIGSLIST and listing.owner_type == owner_type and listing.mileage is not None
        ]
        for owner_type in search.owner_types
    }
    for source in search.sources:
        mapping[SOURCES[source].name] = [] if source in curve_only else _plottable(source, result)
    return {name: sorted(unhidden(listings, hidden_ids), key=filters.passes) for name, listings in mapping.items()}


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
    for source in search.sources:
        source_curve = result.source_curves.get(source)
        if isinstance(source_curve, PriceCurve):
            miles += [source_curve.min_miles, source_curve.max_miles]
            prices += [source_curve.min_price, source_curve.max_price]
        else:
            for listing in _plottable(source, result):
                assert listing.mileage is not None
                miles.append(listing.mileage)
                prices.append(listing.price)
    if not miles:
        return None
    return ChartRange(*_padded(miles), *_padded(prices))


def curve_notes(search: Search, result: SearchResult) -> list[str]:
    """One note for each searched owner type and source whose points were too few for a curve."""
    notes = [
        f"Too few {owner_type} listings for a curve"
        for owner_type in search.owner_types
        if isinstance(result.curves.get(owner_type), NotEnoughData)
    ]
    notes += [
        f"Too few {SOURCES[source].name} listings for a curve"
        for source in search.sources
        if isinstance(result.source_curves.get(source), NotEnoughData)
    ]
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


def unfetched_message(
    fetched: Search, wanted: Collection[OwnerType], wanted_sources: Collection[Source] = ()
) -> str | None:
    """"Search again to load dealer listings" when a wanted owner type or source was
    not fetched, else None."""
    missing = [NAMES[t].lower() for t in wanted if t not in fetched.owner_types]
    missing += [SOURCES[source].name.lower() for source in wanted_sources if source not in fetched.sources]
    return f"Search again to load {' and '.join(missing)} listings" if missing else None


def status_text(
    search: Search,
    result: SearchResult,
    filters: Filters = Filters(),
    curve_only: Collection[Source] = frozenset(),
    hidden_ids: Collection[str] = frozenset(),
) -> str:
    """The count per owner type and source, how many of the results are hidden, and, while a
    filter is active, how many drawn points match it and how many are faded."""
    parts = [
        f"{sum(listing.source == Source.CRAIGSLIST and listing.owner_type == owner_type for listing in result.listings)} "
        f"{owner_type}"
        for owner_type in search.owner_types
    ]
    for source in search.sources:
        parts.append(f"{sum(listing.source == source for listing in result.listings)} {SOURCES[source].name}")
    text = f"{len(result.listings)} listings: {', '.join(parts)}"
    hidden = hidden_count(result.listings, hidden_ids)
    if hidden:
        text += f". {hidden} hidden"
    if filters.active():
        plotted = plotted_listings(search, result, curve_only=curve_only, hidden_ids=hidden_ids)
        points = [listing for listings in plotted.values() for listing in listings]
        matched, faded = match_counts(points, filters)
        text += f". Points on the chart: {matched} match filters, {faded} faded"
    return f"Cancelled. {text}" if result.cancelled else text


def progress_text(count: int) -> str:
    """The running count while a Search is still fetching."""
    return f"{count} listings so far"


def failure_banner(result: SearchResult) -> str | None:
    """The banner for a Search a Source failed partway through, else None. A Craigslist
    failure does not hide another Source's Listings, and the other way around."""
    failures = []
    if result.error is not None:
        requests = "1 request" if result.requests == 1 else f"{result.requests} requests"
        failures.append(f"Craigslist stopped answering after {requests}.")
    for source in result.source_errors:
        failures.append(f"{SOURCES[source].name} stopped answering.")
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


def _drawn_at(listing: Listing, view: ChartRange | None) -> list[float]:
    """Where `listing`'s point is drawn: its own place, or its arrow's place at the edge."""
    assert listing.mileage is not None
    edge = view and _edge_point(listing.mileage, listing.price, view)
    return edge["value"] if edge else [listing.mileage, listing.price]


def _point(listing: Listing, view: ChartRange | None, filters: Filters) -> list[int] | dict[str, Any]:
    """One data item: the point, an arrow at the edge for an outlier, and faded when it
    fails `filters` (an arrow stays an arrow)."""
    assert listing.mileage is not None
    point = (view and _edge_point(listing.mileage, listing.price, view)) or [listing.mileage, listing.price]
    if filters.passes(listing):
        return point
    faded = {"symbolSize": FADED_SIZE, "itemStyle": {"color": FADED_COLOR, "borderWidth": 0}}
    if isinstance(point, dict):
        return {**point, **faded}
    return {"value": point, "symbol": "circle", **faded}


def _points(owner_type: OwnerType, listings: list[Listing], view: ChartRange | None, filters: Filters) -> dict[str, Any]:
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
        "data": [_point(listing, view, filters) for listing in listings],
    }


def _plottable(source: Source, result: SearchResult) -> list[Listing]:
    """The Listings of `source` with a mileage, in data order."""
    return [listing for listing in result.listings if listing.source == source and listing.mileage is not None]


def _source_points(source: Source, listings: list[Listing], view: ChartRange | None, filters: Filters) -> dict[str, Any]:
    """Hollow like a Dealer series, in the source's own colour and marker: told apart from
    Craigslist's by Source rather than owner type."""
    info = SOURCES[source]
    return {
        "name": info.name,
        "type": "scatter",
        "symbol": info.marker,
        "symbolSize": POINT_SIZE,
        "itemStyle": {"color": "transparent", "borderColor": info.color, "borderWidth": 1.5},
        "data": [_point(listing, view, filters) for listing in listings],
    }


def _pin_ring(plotted: dict[str, list[Listing]], view: ChartRange | None, pinned_id: str | None) -> dict[str, Any]:
    """A hollow ring around the Pinned Listing's point, or no data when it is not plotted."""
    data = [_drawn_at(listing, view) for listings in plotted.values() for listing in listings if listing.id == pinned_id]
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


def _favorite_pins(
    plotted: dict[str, list[Listing]], view: ChartRange | None, filters: Filters, favorite_ids: Collection[str]
) -> dict[str, Any]:
    """A gold pin over each favorite's point, its tip on the point. None for a faded point, and
    none for one not drawn. Silent, so hover and click reach the point beneath."""
    data = [
        _drawn_at(listing, view)
        for listings in plotted.values()
        for listing in listings
        if listing.id in favorite_ids and filters.passes(listing)
    ]
    return {
        "name": FAVORITES_NAME,
        "type": "scatter",
        "silent": True,
        "z": 9,
        "symbol": "pin",
        "symbolSize": FAVORITE_SIZE,
        "symbolOffset": [0, "-50%"],
        "itemStyle": {"color": FAVORITE_COLOR, "borderColor": FAVORITE_BORDER, "borderWidth": 1},
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


def _source_curve(source: Source, curve: PriceCurve) -> dict[str, Any]:
    info = SOURCES[source]
    return {
        "name": f"{info.name} curve",
        "type": "line",
        "showSymbol": False,
        "itemStyle": {"color": info.color},
        "lineStyle": {"color": info.color, "width": 2},
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
