"""The Search page: toolbar of Search controls, price vs. mileage chart, status line.

The page may serve several people from one process, so every piece of Search state
lives inside `search_page`, one copy per browser tab. Nothing here is module-level state.
"""
import os
import queue
import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from loguru import logger
from nicegui import app, run, ui
from nicegui.events import EChartPointClickEventArguments, GenericEventArguments
from starlette.requests import Request

from craigslist import lookup
from craigslist.chart import (
    chart_options,
    curve_notes,
    empty_message,
    failure_banner,
    plotted_listings,
    progress_text,
    status_text,
    unfetched_message,
)
from craigslist.favorites import (
    EMPTY_TEXT as NO_FAVORITES_TEXT,
    FAVORITES_KEY,
    SavedListing,
    SavedSearch,
    add_saved,
    button_text,
    favorite_row,
    read_saved,
    remove_saved,
    saved_ids,
    write_saved,
)
from craigslist.filters import Filters, trim_options, year_bounds, year_options
from craigslist.listings import Listing, OwnerType, Source
from craigslist.preview import (
    IDLE_TEXT,
    detail_lines,
    load_details,
    no_mileage_listings,
    no_mileage_note,
    preview_content,
    save_label,
)
from craigslist.search import Search, SearchError, SearchResult, run_live_search
from craigslist.sources import SOURCES, choices_text

HOST = "127.0.0.1"
"""Local only until the Linode ticket adds a --host flag."""
PORT = 8080
POLL_SECONDS = 0.25
"""How often the page draws the Listings that arrived since the last draw."""
TITLE = "Craigslist car prices"
STORAGE_DIR = Path(".nicegui")
"""NiceGUI's per-browser storage files, and the generated secret that signs the browser cookie."""
FLAG_FILTERS = (("one_owner", "One owner"), ("no_accidents", "No accidents"), ("price_dropped", "Price dropped"))
"""Each yes/no display filter: its `Filters` field and its switch's label."""
SEARCH_KEYS = ("state", "city", "make", "model")
FLAG_KEYS = ("owner", "dealer", *(info.query_key for info in SOURCES.values()))
FALSE_WORDS = {"0", "false", "no", "off"}
TAB_PICKS_TOP = """(event) => {{
  const select = getElement({id});
  if (event.key === "ArrowUp" || event.key === "ArrowDown") {{ select.arrowed = true; return; }}
  if (event.key !== "Tab") {{ select.arrowed = false; return; }}
  if (event.shiftKey || select.arrowed) return;  // an arrowed-to option: Quasar picks it
  const typed = event.target.value?.trim().toLocaleLowerCase();
  if (!typed) return;
  const label = (option) => String(option.label).toLocaleLowerCase();
  const top = select.initialOptions.find((option) => label(option) === typed)
    ?? select.initialOptions.find((option) => label(option).includes(typed));
  if (top === undefined) return;
  const q = select.$refs.qRef;
  q.setOptionIndex(-1);  // so Quasar's own Tab handling does not pick a stale highlight
  q.toggleOption(top);
}}"""
"""Tab in a select's search box picks the top option matching the typed text, as the
filtered dropdown lists it, instead of leaving the box empty."""
DEFAULT_SEARCH = {"state": "CA", "city": "Sf Bay Area", "make": "Honda", "model": "Civic"}
"""What a browser with no link and no remembered Search starts from, so Search is one click."""


@dataclass
class SearchForm:
    """What the toolbar currently holds, and whether it makes a Search."""

    state: str | None = None
    city: str | None = None
    make: str | None = None
    model: str | None = None
    owner: bool = True
    dealer: bool = True
    sources: dict[Source, bool] = field(default_factory=lambda: {source: info.default for source, info in SOURCES.items()})
    """Whether each other source's checkbox is ticked."""

    @classmethod
    def from_query(cls, params: Mapping[str, str]) -> "SearchForm":
        """A form filled from URL query parameters, keeping only values the lookup tables know.

        Matching ignores case and takes the lookup spelling. A city is kept only under a known
        state, a model only under a known make. A missing or unreadable checkbox takes its default
        (checked, for every source so far).
        """
        form = cls()
        state = _known(params.get("state"), lookup.states())
        if state:
            form.state = state
            form.city = _known(params.get("city"), form.city_options())
        make = _known(params.get("make"), lookup.makes())
        if make:
            form.make = make
            form.model = _known(params.get("model"), form.model_options())
        form.owner = params.get("owner", "1").strip().casefold() not in FALSE_WORDS
        form.dealer = params.get("dealer", "1").strip().casefold() not in FALSE_WORDS
        form.sources = {
            source: params.get(info.query_key, "1" if info.default else "0").strip().casefold() not in FALSE_WORDS
            for source, info in SOURCES.items()
        }
        return form

    def to_query(self) -> dict[str, str]:
        """The chosen values and every checkbox as URL query parameters, the inverse of `from_query`."""
        chosen = {key: value for key in SEARCH_KEYS if (value := getattr(self, key))}
        return {
            **chosen,
            "owner": "1" if self.owner else "0",
            "dealer": "1" if self.dealer else "0",
            **{SOURCES[source].query_key: "1" if checked else "0" for source, checked in self.sources.items()},
        }

    def choose_state(self, state: str | None) -> None:
        self.state = state
        self.city = None

    def choose_make(self, make: str | None) -> None:
        self.make = make
        self.model = None

    def city_options(self) -> list[str]:
        return [city.name for city in lookup.cities(self.state)] if self.state else []

    def model_options(self) -> list[str]:
        return lookup.models(self.make) if self.make else []

    def chosen_sources(self) -> tuple[Source, ...]:
        return tuple(source for source, checked in self.sources.items() if checked)

    def problem(self) -> str | None:
        """Why Search is disabled, or None when it can run."""
        if not (self.state and self.city and self.make and self.model):
            return "Pick a state, city, make, and model"
        if not (self.owner or self.dealer or any(self.sources.values())):
            return _pick_message()
        return None

    def search(self) -> Search:
        assert self.state and self.city and self.make and self.model, self.problem()
        owner_types = tuple(
            owner_type
            for owner_type, checked in ((OwnerType.OWNER, self.owner), (OwnerType.DEALER, self.dealer))
            if checked
        )
        return Search(self.state, self.city, self.make, self.model, owner_types, self.chosen_sources())


def _pick_message() -> str:
    return "Pick " + choices_text(["owner", "dealer", *(info.name.casefold() for info in SOURCES.values())])


def has_search_params(params: Mapping[str, str]) -> bool:
    """Whether a URL names any part of a Search, so it should win over the browser's memory."""
    return any(key in params for key in (*SEARCH_KEYS, *FLAG_KEYS))


def starting_query(params: Mapping[str, str], remembered: Mapping[str, str]) -> Mapping[str, str]:
    """Where the form starts: a link naming a Search, else what this browser last held,
    else DEFAULT_SEARCH."""
    if has_search_params(params):
        return params
    return remembered or DEFAULT_SEARCH


def storage_secret(directory: Path = STORAGE_DIR) -> str:
    """The secret that signs the browser cookie, made on first use and kept out of the repo."""
    path = directory / "storage_secret"
    if path.exists():
        return path.read_text().strip()
    directory.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(secret)
    return secret


def _known(value: str | None, options: list[str]) -> str | None:
    """The option matching `value` ignoring case, else None."""
    if value is None:
        return None
    return next((option for option in options if option.casefold() == value.strip().casefold()), None)


def _tab_picks_top(select: ui.select) -> ui.select:
    return select.on("keydown.capture", js_handler=TAB_PICKS_TOP.format(id=select.id))


def search_page(request: Request) -> None:
    """Build one Search page for one browser tab.

    A URL naming a Search fills the controls, and runs it once complete. Otherwise the
    controls come from what this browser last held.
    """
    params: Mapping[str, str] = request.query_params
    from_link = has_search_params(params)
    remembered: Mapping[str, str] = app.storage.user.get("search", {})
    form = SearchForm.from_query(starting_query(params, remembered))
    current: tuple[Search, SearchResult] | None = None
    """The last finished Search and its result. Its owner types are the ones fetched."""
    running = False
    cancelling = False
    stop = threading.Event()
    arrived: queue.Queue[list[Listing]] = queue.Queue()
    """Batches the worker thread hands to the page. Only the timer touches the UI."""
    live: list[Listing] = []
    live_search: Search | None = None
    shown_search: Search | None = None
    shown_result: SearchResult | None = None
    """What the chart currently draws, for mapping chart events back to Listings."""
    hovered: Listing | None = None
    pinned: Listing | None = None
    pinned_details: dict[str, str] | None = None
    """None while the Pinned Listing's details load."""
    list_mode = False
    """The panel lists the Listings with no mileage, until one is pinned."""
    filters = Filters()
    """The display filters: they fade points, never refit a curve or refetch."""
    curve_only: frozenset[Source] = frozenset()
    """Sources drawn as their Price curve alone, points hidden."""
    removed_origins: dict[str, SavedSearch | None] = {}
    """The Search a favorite removed in this tab came from, so saving it again keeps it."""

    def refresh_search_button() -> None:
        problem = form.problem()
        if running:
            search_button.set_text("Cancelling..." if cancelling else "Cancel")
            search_button.set_enabled(not cancelling)
            hint.set_text("")
            return
        search_button.set_text("Search")
        search_button.set_enabled(problem is None)
        hint.set_text(problem or "")

    def remember() -> None:
        app.storage.user["search"] = form.to_query()

    def state_changed(state: str | None) -> None:
        form.choose_state(state)
        city_select.set_options(form.city_options(), value=None)
        remember()
        refresh_search_button()

    def city_changed(city: str | None) -> None:
        form.city = city
        remember()
        refresh_search_button()

    def make_changed(make: str | None) -> None:
        form.choose_make(make)
        model_select.set_options(form.model_options(), value=None)
        remember()
        refresh_search_button()

    def model_changed(model: str | None) -> None:
        form.model = model
        remember()
        refresh_search_button()

    def owner_changed(checked: bool) -> None:
        form.owner = checked
        remember()
        refresh_search_button()
        redraw()

    def dealer_changed(checked: bool) -> None:
        form.dealer = checked
        remember()
        refresh_search_button()
        redraw()

    def source_changed(source: Source, checked: bool) -> None:
        form.sources[source] = checked
        remember()
        refresh_search_button()
        redraw()

    def set_filters(new: Filters) -> None:
        nonlocal filters
        if new != filters:
            filters = new
            redraw()

    def flag_changed(name: str, **changes: bool) -> None:
        set_filters(replace(filters, **{name: replace(getattr(filters, name), **changes)}))

    def years_changed() -> None:
        low, high = year_bounds(min_year_select.value, max_year_select.value, list(min_year_select.options))
        set_filters(replace(filters, min_year=low, max_year=high))

    def curve_only_changed(source: Source, on: bool) -> None:
        nonlocal curve_only
        curve_only = curve_only | {source} if on else curve_only - {source}
        redraw()

    def trim_toggled(trim: str | None, selected: bool) -> None:
        hidden = filters.hidden_trims - {trim} if selected else filters.hidden_trims | {trim}
        set_filters(replace(filters, hidden_trims=hidden))

    def fill_filter_options(listings: list[Listing]) -> None:
        """Offer the years and trims in a finished Search's results, all of them chosen."""
        nonlocal filters
        years = year_options(listings)
        filters = replace(filters, min_year=None, max_year=None, hidden_trims=frozenset())
        min_year_select.set_options(years, value=years[0] if years else None)
        max_year_select.set_options(years, value=years[-1] if years else None)
        trim_row.clear()
        with trim_row:
            ui.label("Trim").classes("text-sm opacity-70")
            for trim in (*trim_options(listings), None):
                ui.chip(
                    trim or "Unknown", selectable=True, selected=True,
                    on_selection_change=lambda e, trim=trim: trim_toggled(trim, e.value),
                ).props("dense outline")

    def redraw() -> None:
        """Apply the checkboxes to the finished Search at once, without fetching."""
        if current is not None and not running:
            show(*current, final=True)

    def draw_arrivals() -> None:
        """Add the batches that arrived since the last draw, and the running count."""
        if not running:
            return
        new = False
        while True:
            try:
                live.extend(arrived.get_nowait())
            except queue.Empty:
                break
            new = True
        if new and live_search is not None:
            show(live_search, SearchResult(list(live), {}, {}), final=False)

    def draw_preview() -> None:
        """Show the hovered Listing, else the no-mileage list, else the Pinned Listing."""
        preview.clear()
        with preview:
            if hovered is not None:
                draw_listing(hovered)
            elif list_mode and shown_search is not None and shown_result is not None:
                draw_no_mileage_list(no_mileage_listings(shown_search, shown_result))
            elif pinned is not None:
                draw_listing(pinned)
            else:
                ui.label(IDLE_TEXT).classes("text-sm opacity-70")

    def draw_listing(listing: Listing) -> None:
        content = preview_content(listing)
        if content.image:
            ui.image(content.image).classes("w-full rounded")
        ui.label(content.title).classes("font-bold")
        ui.label(f"{content.price}  |  {content.mileage}").classes("text-lg")
        ui.label(content.owner)
        for line in (content.year, content.trim, content.posted, content.location, content.dealer, content.owners, content.accidents, content.price_drop):
            if line:
                ui.label(line).classes("text-sm opacity-70")
        with ui.row().classes("items-center gap-1"):
            ui.button(content.link_label).props(f'href="{content.url}" target="_blank" rel="noopener" flat')
            saved = listing.id in saved_ids(favorites())
            ui.button(save_label(saved), on_click=lambda: favorite_toggled(listing)).props(
                "unelevated color=amber-8" if saved else "outline color=amber-8"
            )
        if listing is pinned and listing.source == Source.CRAIGSLIST:
            lines = detail_lines(pinned_details)
            if isinstance(lines, str):
                ui.label(lines).classes("text-sm opacity-70")
            else:
                for line in lines:
                    ui.label(line).classes("text-sm")

    def draw_no_mileage_list(listings: list[Listing]) -> None:
        ui.label(no_mileage_note(len(listings)) or "").classes("font-bold")
        with ui.scroll_area().classes("w-full grow"):
            for listing in listings:
                ui.item(f"${listing.price:,}  {listing.title}", on_click=lambda _, item=listing: pin(item)).classes("text-sm")

    def point_listing(args: Mapping[str, object]) -> Listing | None:
        """The Listing behind a chart event on a point, or None for a curve, ring, or stale point."""
        if shown_search is None or shown_result is None or args.get("seriesType") != "scatter":
            return None
        rows = plotted_listings(shown_search, shown_result, filters, curve_only).get(str(args.get("seriesName")))
        index = args.get("dataIndex")
        if rows is None or not isinstance(index, int) or not 0 <= index < len(rows):
            return None
        return rows[index]

    def point_hovered(event: GenericEventArguments) -> None:
        nonlocal hovered
        listing = point_listing(event.args)
        if listing is not None and listing is not hovered:
            hovered = listing
            draw_preview()

    def hover_ended(_: GenericEventArguments) -> None:
        nonlocal hovered
        if hovered is not None:
            hovered = None
            draw_preview()

    async def point_clicked(event: EChartPointClickEventArguments) -> None:
        listing = point_listing(
            {"seriesType": event.series_type, "seriesName": event.series_name, "dataIndex": event.data_index}
        )
        if listing is not None:
            await pin(listing)

    async def pin(listing: Listing) -> None:
        """Make `listing` the Pinned Listing, ring it, and load its details off the UI thread."""
        nonlocal pinned, pinned_details, list_mode
        pinned, pinned_details, list_mode = listing, None, False
        draw_preview()
        redraw_pin()
        try:
            details = await run.io_bound(load_details, listing)
        except Exception as error:  # a failed detail fetch must not break the page
            logger.warning("Details for {} failed: {}", listing.url, error)
            details = {}
        if pinned is listing:  # not replaced while the fetch ran
            pinned_details = details
            draw_preview()

    def redraw_pin() -> None:
        """Move the ring to the Pinned Listing and the gold pins to the favorites, without searching."""
        if shown_search is not None and shown_result is not None and chart.visible:
            chart.options.clear()
            chart.options.update(chart_options(
                shown_search, shown_result, pinned.id if pinned else None, filters, curve_only, saved_ids(favorites())
            ))
            chart.update()

    def favorites() -> list[SavedListing]:
        """This browser's favorites, newest first, read fresh so every tab agrees."""
        return read_saved(app.storage.user, FAVORITES_KEY)

    def shown_listing(listing_id: str) -> Listing | None:
        """The current results' Listing with this id, or None when no shown Search found it."""
        if shown_result is None:
            return None
        return next((listing for listing in shown_result.listings if listing.id == listing_id), None)

    def favorite_toggled(listing: Listing) -> None:
        """Save `listing` as a favorite, or remove it when it already is one."""
        entries = favorites()
        if listing.id in saved_ids(entries):
            removed_origins.update((entry.listing.id, entry.search) for entry in entries if entry.listing.id == listing.id)
            entries = remove_saved(entries, listing.id)
        else:
            found = shown_search is not None and shown_listing(listing.id) is not None
            origin = SavedSearch.of(shown_search) if shown_search is not None and found else removed_origins.get(listing.id)
            entries = add_saved(entries, listing, origin, datetime.now(UTC))
        write_saved(app.storage.user, FAVORITES_KEY, entries)
        draw_favorites()
        draw_preview()
        redraw_pin()

    async def favorite_clicked(entry: SavedListing) -> None:
        """Pin a favorite, as the current results' Listing when this Search found it too."""
        await pin(shown_listing(entry.listing.id) or entry.listing)

    def draw_favorites() -> None:
        """The toolbar count and the drawer's rows, newest first."""
        entries = favorites()
        favorites_button.set_text(button_text(len(entries)))
        drawer.clear()
        with drawer:
            ui.label("Favorites").classes("text-lg font-bold")
            if not entries:
                ui.label(NO_FAVORITES_TEXT).classes("text-sm opacity-70")
            for entry in entries:
                row = favorite_row(entry)
                with ui.row().classes("w-full no-wrap items-start gap-1"):
                    with ui.row().classes("grow min-w-0 no-wrap items-start gap-2 p-1 rounded hover:bg-gray-500/10 cursor-pointer") as item:
                        if row.image:
                            ui.image(row.image).classes("w-20 h-14 rounded shrink-0")
                        with ui.column().classes("gap-0 grow min-w-0"):
                            ui.label(row.title).classes("text-sm font-bold truncate w-full")
                            ui.label(row.price_mileage).classes("text-sm")
                            ui.label(row.source).classes("text-xs opacity-70")
                    item.mark("favorite").on("click", lambda _, entry=entry: favorite_clicked(entry))
                    ui.button("✕", on_click=lambda _, listing=entry.listing: favorite_toggled(listing)).props("flat dense size=sm")

    def no_mileage_clicked() -> None:
        nonlocal list_mode
        list_mode = True
        draw_preview()

    async def search_clicked() -> None:
        nonlocal running, cancelling, stop, live_search, current, hovered, pinned, pinned_details, list_mode
        if running:
            cancelling = True
            stop.set()
            refresh_search_button()
            return
        search = form.search()
        remember()
        ui.navigate.history.replace("/?" + urlencode(form.to_query()))
        stop = threading.Event()
        live.clear()
        live_search = search
        hovered = pinned = pinned_details = None
        list_mode = False
        draw_preview()
        while not arrived.empty():
            arrived.get_nowait()
        running, cancelling = True, False
        refresh_search_button()
        banner.set_visibility(False)
        chart.set_visibility(False)
        reset_button.set_visibility(False)
        curve_note.set_visibility(False)
        empty_label.set_visibility(False)
        names = ["Craigslist"] if search.owner_types else []
        names += [SOURCES[source].name for source in search.sources]
        status.set_text(f"Searching {' and '.join(names)} for {search.make} {search.model} in {search.city}...")
        timer.activate()
        try:
            result = await run.io_bound(run_live_search, search, None, arrived.put, stop.is_set)
        except SearchError as error:
            logger.warning("Search {} failed: {}", search, error)
            status.set_text(f"Search failed: {error}")
            return
        finally:
            timer.deactivate()
            running = cancelling = False
            refresh_search_button()
        if result is None:  # the app is shutting down
            return
        current = (search, result)
        fill_filter_options(result.listings)
        show(search, result, final=True)

    def arm_drag_zoom() -> None:
        """Make a plain drag on the chart select a region to zoom into."""
        chart.run_chart_method(
            "dispatchAction", {"type": "takeGlobalCursor", "key": "dataZoomSelect", "dataZoomSelectActive": True}
        )

    def reset_zoom() -> None:
        chart.run_chart_method("dispatchAction", {"type": "restore"})
        arm_drag_zoom()

    def show(fetched: Search, result: SearchResult, final: bool) -> None:
        """Draw `result`, limited to the fetched Owner types and Sources checked now."""
        nonlocal shown_search, shown_result
        wanted = {OwnerType.OWNER: form.owner, OwnerType.DEALER: form.dealer}
        search = replace(
            fetched,
            owner_types=tuple(t for t in fetched.owner_types if wanted[t]),
            sources=tuple(s for s in fetched.sources if form.sources[s]),
        )
        shown_search, shown_result = search, result
        missing = unfetched_message(fetched, [t for t, checked in wanted.items() if checked], form.chosen_sources())
        message = empty_message(search, result) if final else None
        if not search.owner_types and not search.sources:
            message = missing or _pick_message()
            missing = None
        chart.set_visibility(message is None and bool(result.listings))
        empty_label.set_visibility(message is not None)
        if message is not None:
            empty_label.set_text(message)
        elif result.listings:
            chart.options.clear()
            chart.options.update(chart_options(search, result, pinned.id if pinned else None, filters, curve_only, saved_ids(favorites())))
            chart.update()
            arm_drag_zoom()
        reset_button.set_visibility(chart.visible)
        no_mileage = no_mileage_note(len(no_mileage_listings(search, result)))
        no_mileage_label.set_visibility(no_mileage is not None)
        no_mileage_label.set_text(no_mileage or "")
        if list_mode:
            draw_preview()
        notes = curve_notes(search, result) if final else []
        if missing and final:
            notes.append(missing)
        curve_note.set_visibility(bool(notes))
        curve_note.set_text(". ".join(notes))
        text = failure_banner(result)
        banner.set_visibility(text is not None)
        banner.set_text(text or "")
        if search.owner_types or search.sources:
            status.set_text(status_text(search, result, filters, curve_only) if final else progress_text(len(result.listings)))

    drawer = ui.right_drawer(value=False, bordered=True).classes("p-2").props("width=340")
    # NiceGUI pads the page by 1rem on each side, so fill the rest of the window.
    with ui.column().classes("w-full h-[calc(100vh-2rem)] gap-2 no-wrap"):
        with ui.row().classes("w-full items-center gap-3"):
            _tab_picks_top(ui.select(lookup.states(), value=form.state, label="State", with_input=True, on_change=lambda e: state_changed(e.value))).classes("w-24")
            city_select = _tab_picks_top(ui.select(form.city_options(), value=form.city, label="City", with_input=True, on_change=lambda e: city_changed(e.value))).classes("w-56")
            _tab_picks_top(ui.select(lookup.makes(), value=form.make, label="Make", with_input=True, on_change=lambda e: make_changed(e.value))).classes("w-44")
            model_select = _tab_picks_top(ui.select(form.model_options(), value=form.model, label="Model", with_input=True, on_change=lambda e: model_changed(e.value))).classes("w-44")
            ui.checkbox("Owner", value=form.owner, on_change=lambda e: owner_changed(e.value))
            ui.checkbox("Dealer", value=form.dealer, on_change=lambda e: dealer_changed(e.value))
            for source, info in SOURCES.items():
                with ui.row().classes("items-center gap-0 no-wrap"):
                    ui.checkbox(info.name, value=form.sources[source], on_change=lambda e, source=source: source_changed(source, e.value))
                    ui.switch("curve only", on_change=lambda e, source=source: curve_only_changed(source, e.value)).props("dense size=xs").classes("text-xs opacity-70")
            search_button = ui.button("Search", on_click=search_clicked)
            hint = ui.label().classes("text-sm opacity-70")
            ui.space()
            favorites_button = ui.button(on_click=drawer.toggle).props("flat color=amber-9")
        with ui.row().classes("w-full items-center gap-4"):
            for name, label in FLAG_FILTERS:
                with ui.row().classes("items-center gap-0 no-wrap"):
                    ui.switch(label, on_change=lambda e, name=name: flag_changed(name, on=e.value))
                    ui.checkbox("include unknown", value=True, on_change=lambda e, name=name: flag_changed(name, include_unknown=e.value)).props("dense size=xs").classes("text-xs opacity-70")
            with ui.row().classes("items-center gap-1 no-wrap"):
                min_year_select = ui.select([], label="Min year", on_change=years_changed).props("dense").classes("w-24")
                max_year_select = ui.select([], label="Max year", on_change=years_changed).props("dense").classes("w-24")
                ui.checkbox("include unknown year", value=True, on_change=lambda e: set_filters(replace(filters, include_unknown_year=e.value))).props("dense size=xs").classes("text-xs opacity-70")
        trim_row = ui.row().classes("w-full items-center gap-1")
        banner = ui.label().classes("w-full p-2 rounded bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100")
        banner.set_visibility(False)
        with ui.row().classes("w-full grow gap-4 no-wrap"):
            with ui.column().classes("grow h-full items-center justify-center"):
                chart = ui.echart({}, on_point_click=point_clicked).classes("w-full h-full")
                chart.set_visibility(False)
                with ui.row().classes("items-center gap-3"):
                    reset_button = ui.button("Reset zoom", on_click=reset_zoom).props("flat dense")
                    reset_button.set_visibility(False)
                    curve_note = ui.label().classes("text-sm opacity-70")
                    curve_note.set_visibility(False)
                    no_mileage_label = ui.label().classes("text-sm underline cursor-pointer")
                    no_mileage_label.on("click", no_mileage_clicked)
                    no_mileage_label.set_visibility(False)
                empty_label = ui.label().classes("text-lg opacity-70")
                empty_label.set_visibility(False)
            preview = ui.column().classes("w-80 h-full border rounded p-2 gap-1 overflow-auto")
        status = ui.label("Choose a car and press Search.").classes("text-sm opacity-70")
    chart.on("chart:mouseover", point_hovered, ["seriesType", "seriesName", "dataIndex"])
    chart.on("chart:globalout", hover_ended, [])
    draw_preview()
    draw_favorites()
    timer = ui.timer(POLL_SECONDS, draw_arrivals, active=False)
    refresh_search_button()
    if from_link and form.problem() is None:
        ui.timer(0.1, search_clicked, once=True)


def serve(port: int = PORT) -> None:
    """Serve the Search page until interrupted. Light or dark follows the browser."""
    logger.info("Search page on http://{}:{}", HOST, port)
    ui.run(
        search_page, host=HOST, port=port, title=TITLE, dark=None, reload=False, storage_secret=storage_secret()
    )
