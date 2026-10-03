"""PROTOTYPE, throw away: three ways to save a car as a favorite and view it again later.

Three variants on the real Search page, switchable via `?variant=A|B|C` and the floating bar
at the bottom (or the left/right arrow keys):

- A, Drawer: "Save" star in Preview; a Favorites (n) button opens a right-hand drawer list.
- B, Tray: heart in Preview; an always-visible strip of photo cards under the chart.
- C, Page: "Bookmark" in Preview; a Favorites (n) link opens a full /favorites comparison page.

Every variant marks favorites in the current results with a gold pin on the chart, and clicking
a favorite shows it in the Preview panel. Favorites live in memory per browser, lost on restart:
persistence is not the question here.

Run: uv run python -m craigslist.prototype_favorites   (http://127.0.0.1:8080/?variant=A)
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from nicegui import app, ui
from starlette.requests import Request

from craigslist import page
from craigslist.listings import Listing
from craigslist.search import Search
from craigslist.sources import SOURCES

VARIANTS = {"A": "Drawer", "B": "Tray", "C": "Page"}
_FAVORITES: dict[str, list["Favorite"]] = {}
"""PROTOTYPE, in memory: browser id -> favorites, newest first."""


@dataclass
class Favorite:
    listing: Listing
    search: Search | None
    saved: datetime = field(default_factory=datetime.now)


def _favorites() -> list[Favorite]:
    return _FAVORITES.setdefault(app.storage.browser["id"], [])


def _source_name(listing: Listing) -> str:
    info = SOURCES.get(listing.source)  # type: ignore[call-overload]
    return info.name if info else f"Craigslist {listing.owner_type}"


def _miles(listing: Listing) -> str:
    return f"{listing.mileage:,} mi" if listing.mileage is not None else "no mileage"


def _search_link(search: Search | None) -> str | None:
    if search is None:
        return None
    return "/?" + urlencode({"state": search.state, "city": search.city, "make": search.make, "model": search.model})


class FavoritesPrototype:
    """The favorites UI for one browser tab, in whichever variant the URL asks for."""

    def __init__(self, request: Request) -> None:
        self.variant = request.query_params.get("variant", "A").upper()
        if self.variant not in VARIANTS:
            self.variant = "A"
        self.pin: Callable[[Listing], Any] = lambda _: None
        self.refresh_page: Callable[[], None] = lambda: None
        self.current_search: Callable[[], Search | None] = lambda: None

    # --- Hooks Called From search_page

    def mount(self, toolbar: ui.row, under_chart: ui.column, pin: Callable[[Listing], Any],
              refresh_page: Callable[[], None], current_search: Callable[[], Search | None]) -> None:
        self.pin, self.refresh_page, self.current_search = pin, refresh_page, current_search
        with toolbar:
            self.toolbar_slot = ui.row().classes("items-center")
        with under_chart:
            self.tray_slot = ui.row().classes("w-full")
        self.drawer = ui.right_drawer(value=False, bordered=True).classes("p-2").props("width=340")
        self._switcher()
        self.render()

    def favorite_button(self, listing: Listing) -> None:
        saved = self._is_saved(listing)
        label = {
            "A": ("★ Saved" if saved else "☆ Save"),
            "B": ("♥ Favorited" if saved else "♡ Favorite"),
            "C": ("Bookmarked" if saved else "Bookmark"),
        }[self.variant]
        button = ui.button(label, on_click=lambda: self.toggle(listing))
        button.props("unelevated color=amber-8" if saved else "outline color=amber-8")

    def mark_chart(self, options: dict[str, Any], listings: list[Listing]) -> None:
        shown = {listing.id for listing in listings}
        points = [
            [f.listing.mileage, f.listing.price]
            for f in _favorites()
            if f.listing.id in shown and f.listing.mileage is not None
        ]
        options.setdefault("series", []).append({
            "name": "Favorites", "type": "scatter", "symbol": "pin", "symbolSize": 26, "z": 10,
            "silent": True, "itemStyle": {"color": "#f5b301", "borderColor": "#7a5900"}, "data": points,
        })

    # --- Favorites State

    def _is_saved(self, listing: Listing) -> bool:
        return any(f.listing.id == listing.id for f in _favorites())

    def toggle(self, listing: Listing) -> None:
        favorites = _favorites()
        if self._is_saved(listing):
            favorites[:] = [f for f in favorites if f.listing.id != listing.id]
        else:
            favorites.insert(0, Favorite(listing, self.current_search()))
        self.render()
        self.refresh_page()

    # --- Variant Rendering

    def render(self) -> None:
        self.toolbar_slot.clear()
        self.tray_slot.clear()
        self.drawer.clear()
        count = len(_favorites())
        with self.toolbar_slot:
            if self.variant == "A":
                ui.button(f"★ Favorites ({count})", on_click=self.drawer.toggle).props("flat color=amber-9")
            elif self.variant == "C":
                ui.button(f"Favorites ({count}) ↗").props('flat color=amber-9 href="/favorites" target="_blank"')
        if self.variant == "A":
            with self.drawer:
                self._drawer_list()
        else:
            self.drawer.set_value(False)
        if self.variant == "B":
            with self.tray_slot:
                self._tray()

    def _drawer_list(self) -> None:
        ui.label("Favorites").classes("text-lg font-bold")
        if not _favorites():
            ui.label("Nothing saved yet. Hover or click a point, then ☆ Save in the Preview panel.").classes("text-sm opacity-70")
        for f in _favorites():
            listing = f.listing
            with ui.row().classes("w-full no-wrap items-start gap-2 p-1 rounded hover:bg-gray-500/10 cursor-pointer") as row:
                if listing.images:
                    ui.image(listing.images[0]).classes("w-20 h-14 rounded shrink-0")
                with ui.column().classes("gap-0 grow min-w-0"):
                    ui.label(listing.title).classes("text-sm font-bold truncate w-full")
                    ui.label(f"${listing.price:,}  |  {_miles(listing)}").classes("text-sm")
                    ui.label(f"{_source_name(listing)}  ·  saved {f.saved:%b %d %H:%M}").classes("text-xs opacity-70")
                ui.button("✕", on_click=lambda _, listing=listing: self.toggle(listing)).props("flat dense size=sm")
            row.on("click", lambda _, listing=listing: self.pin(listing))

    def _tray(self) -> None:
        with ui.scroll_area().classes("w-full h-36 border rounded"):
            with ui.row().classes("no-wrap gap-2 p-1"):
                if not _favorites():
                    ui.label("♡ Favorites appear here. Heart a car in the Preview panel.").classes("text-sm opacity-70 p-4")
                for f in _favorites():
                    listing = f.listing
                    with ui.card().tight().classes("w-36 shrink-0 cursor-pointer") as card:
                        if listing.images:
                            ui.image(listing.images[0]).classes("w-36 h-20")
                        with ui.column().classes("gap-0 px-1 pb-1"):
                            ui.label(f"${listing.price:,}").classes("text-sm font-bold")
                            ui.label(f"{listing.year or ''} {_miles(listing)}").classes("text-xs opacity-70")
                    card.on("click", lambda _, listing=listing: self.pin(listing))

    def _switcher(self) -> None:
        keys = list(VARIANTS)

        def go(step: int) -> None:
            self.variant = keys[(keys.index(self.variant) + step) % len(keys)]
            label.set_text(f"{self.variant} ({VARIANTS[self.variant]})")
            ui.run_javascript(
                "const u = new URL(location); u.searchParams.set('variant', %r); history.replaceState(null, '', u);"
                % self.variant
            )
            self.render()
            self.refresh_page()

        with ui.row().classes(
            "fixed bottom-4 left-1/2 -translate-x-1/2 z-[9999] items-center gap-2 px-3 py-1 rounded-full "
            "bg-fuchsia-700 text-white shadow-xl"
        ):
            ui.label("PROTOTYPE").classes("text-xs font-bold opacity-80")
            ui.button("←", on_click=lambda: go(-1)).props("flat dense color=white")
            label = ui.label(f"{self.variant} ({VARIANTS[self.variant]})").classes("font-mono")
            ui.button("→", on_click=lambda: go(1)).props("flat dense color=white")
        ui.keyboard(
            lambda e: go(-1 if e.key.arrow_left else 1)
            if e.action.keydown and (e.key.arrow_left or e.key.arrow_right) else None,
            ignore=["input", "select", "button", "textarea"],
        )


def favorites_page() -> None:
    """Variant C's separate page: every favorite side by side, newest first."""
    ui.label("Favorites").classes("text-2xl font-bold")
    ui.label("PROTOTYPE: kept in memory for this browser until the server restarts.").classes("text-sm opacity-70")
    grid = ui.column().classes("w-full gap-0")

    def draw() -> None:
        grid.clear()
        with grid:
            if not _favorites():
                ui.label("Nothing bookmarked yet.").classes("opacity-70 p-4")
            for f in _favorites():
                listing = f.listing
                with ui.row().classes("w-full items-center gap-4 py-2 border-b no-wrap"):
                    if listing.images:
                        ui.image(listing.images[0]).classes("w-40 h-28 rounded shrink-0")
                    else:
                        ui.label("no photo").classes("w-40 h-28 shrink-0 opacity-50 text-center")
                    with ui.column().classes("gap-0 grow"):
                        ui.label(listing.title).classes("font-bold")
                        ui.label(" · ".join(filter(None, [
                            f"{listing.year}" if listing.year else None, listing.trim, _source_name(listing),
                            listing.dealer, listing.location,
                        ]))).classes("text-sm opacity-70")
                        ui.label(f"Saved {f.saved:%Y-%m-%d %H:%M}").classes("text-xs opacity-60")
                    ui.label(f"${listing.price:,}").classes("text-xl font-bold w-28 text-right")
                    ui.label(_miles(listing)).classes("w-28 text-right")
                    with ui.column().classes("gap-1 w-44"):
                        ui.button("Open listing ↗").props(f'flat dense href="{listing.url}" target="_blank"')
                        if link := _search_link(f.search):
                            ui.button("Run its Search ↗").props(f'flat dense href="{link}&variant=C" target="_blank"')
                        ui.button("Remove", on_click=lambda _, listing=listing: remove(listing)).props("flat dense color=negative")

    def remove(listing: Listing) -> None:
        favorites = _favorites()
        favorites[:] = [f for f in favorites if f.listing.id != listing.id]
        draw()

    draw()


def root(request: Request) -> None:
    page.search_page(request, FavoritesPrototype(request))


def main() -> None:
    ui.page("/favorites")(favorites_page)
    ui.run(root, host=page.HOST, port=page.PORT, title="PROTOTYPE favorites", dark=None, reload=False,
           storage_secret=page.storage_secret())


if __name__ in {"__main__", "__mp_main__"}:
    main()
