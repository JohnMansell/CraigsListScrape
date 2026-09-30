"""ECharts options for the Search page chart, built from a SearchResult.

Plain dictionaries only, so the chart can be tested without a browser.
"""
from typing import Any

from craigslist.curve import PriceCurve
from craigslist.listings import OwnerType
from craigslist.search import Search, SearchResult

OWNER_COLOR = "#2f7ed8"
DEALER_COLOR = "#e8743b"
AXIS_COLOR = "#8a8a8a"
"""Mid grey, readable in light and dark mode."""

COLORS = {OwnerType.OWNER: OWNER_COLOR, OwnerType.DEALER: DEALER_COLOR}
NAMES = {OwnerType.OWNER: "Owner", OwnerType.DEALER: "Dealer"}


def chart_options(search: Search, result: SearchResult) -> dict[str, Any]:
    """A scatter per searched owner type, owner filled and dealer hollow, plus each fitted curve.

    Listings without mileage are left off.
    """
    series: list[dict[str, Any]] = []
    for owner_type in search.owner_types:
        series.append(_points(owner_type, result))
    for owner_type in search.owner_types:
        curve = result.curves.get(owner_type)
        if isinstance(curve, PriceCurve):
            series.append(_curve(owner_type, curve))
    return {
        "animation": False,
        "backgroundColor": "transparent",
        "textStyle": {"color": AXIS_COLOR},
        "grid": {"left": 70, "right": 30, "top": 40, "bottom": 50},
        "legend": {"top": 0, "textStyle": {"color": AXIS_COLOR}},
        "xAxis": _axis("Mileage", name_gap=35),
        "yAxis": _axis("Price ($)", name_gap=55),
        "series": series,
    }


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


def status_text(search: Search, result: SearchResult) -> str:
    counts = ", ".join(
        f"{sum(listing.owner_type == owner_type for listing in result.listings)} {owner_type}"
        for owner_type in search.owner_types
    )
    text = f"{len(result.listings)} listings: {counts}"
    return f"Cancelled. {text}" if result.cancelled else text


def progress_text(count: int) -> str:
    """The running count while a Search is still fetching."""
    return f"{count} listings so far"


def failure_banner(result: SearchResult) -> str | None:
    """The banner for a Search Craigslist failed partway through, else None."""
    if result.error is None:
        return None
    requests = "1 request" if result.requests == 1 else f"{result.requests} requests"
    return (
        f"Craigslist stopped answering after {requests}. "
        f"Showing {len(result.listings)} listings; there may be more."
    )


def _points(owner_type: OwnerType, result: SearchResult) -> dict[str, Any]:
    color = COLORS[owner_type]
    item_style: dict[str, Any]
    if owner_type == OwnerType.OWNER:
        item_style = {"color": color}
    else:
        item_style = {"color": "transparent", "borderColor": color, "borderWidth": 1.5}
    return {
        "name": NAMES[owner_type],
        "type": "scatter",
        "symbolSize": 7,
        "itemStyle": item_style,
        "data": [
            [listing.mileage, listing.price]
            for listing in result.listings
            if listing.owner_type == owner_type and listing.mileage is not None
        ],
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


def _axis(name: str, name_gap: int) -> dict[str, Any]:
    return {
        "type": "value",
        "name": name,
        "nameLocation": "middle",
        "nameGap": name_gap,
        "scale": True,
        "axisLine": {"lineStyle": {"color": AXIS_COLOR}},
        "splitLine": {"lineStyle": {"color": AXIS_COLOR, "opacity": 0.2}},
    }
