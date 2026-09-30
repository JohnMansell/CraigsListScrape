"""The Search page: toolbar of Search controls, price vs. mileage chart, status line.

The page may serve several people from one process, so every piece of Search state
lives inside `search_page`, one copy per browser tab. Nothing here is module-level state.
"""
import os
import queue
import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlencode

from loguru import logger
from nicegui import app, run, ui
from starlette.requests import Request

from craigslist import lookup
from craigslist.chart import (
    chart_options,
    curve_notes,
    empty_message,
    failure_banner,
    progress_text,
    status_text,
    unfetched_message,
)
from craigslist.listings import Listing, OwnerType
from craigslist.search import Search, SearchError, SearchResult, run_live_search

HOST = "127.0.0.1"
"""Local only until the Linode ticket adds a --host flag."""
PORT = 8080
POLL_SECONDS = 0.25
"""How often the page draws the Listings that arrived since the last draw."""
TITLE = "Craigslist car prices"
STORAGE_DIR = Path(".nicegui")
"""NiceGUI's per-browser storage files, and the generated secret that signs the browser cookie."""
SEARCH_KEYS = ("state", "city", "make", "model")
FLAG_KEYS = {"owner": OwnerType.OWNER, "dealer": OwnerType.DEALER}
FALSE_WORDS = {"0", "false", "no", "off"}


@dataclass
class SearchForm:
    """What the toolbar currently holds, and whether it makes a Search."""

    state: str | None = None
    city: str | None = None
    make: str | None = None
    model: str | None = None
    owner: bool = True
    dealer: bool = True

    @classmethod
    def from_query(cls, params: Mapping[str, str]) -> "SearchForm":
        """A form filled from URL query parameters, keeping only values the lookup tables know.

        Matching ignores case and takes the lookup spelling. A city is kept only under a known
        state, a model only under a known make. A missing or unreadable checkbox is checked.
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
        return form

    def to_query(self) -> dict[str, str]:
        """The chosen values and both checkboxes as URL query parameters, the inverse of `from_query`."""
        chosen = {key: value for key in SEARCH_KEYS if (value := getattr(self, key))}
        return {**chosen, "owner": "1" if self.owner else "0", "dealer": "1" if self.dealer else "0"}

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

    def problem(self) -> str | None:
        """Why Search is disabled, or None when it can run."""
        if not (self.state and self.city and self.make and self.model):
            return "Pick a state, city, make, and model"
        if not (self.owner or self.dealer):
            return "Pick owner, dealer, or both"
        return None

    def search(self) -> Search:
        assert self.state and self.city and self.make and self.model, self.problem()
        owner_types = tuple(
            owner_type
            for owner_type, checked in ((OwnerType.OWNER, self.owner), (OwnerType.DEALER, self.dealer))
            if checked
        )
        return Search(self.state, self.city, self.make, self.model, owner_types)


def has_search_params(params: Mapping[str, str]) -> bool:
    """Whether a URL names any part of a Search, so it should win over the browser's memory."""
    return any(key in params for key in (*SEARCH_KEYS, *FLAG_KEYS))


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


def search_page(request: Request) -> None:
    """Build one Search page for one browser tab.

    A URL naming a Search fills the controls, and runs it once complete. Otherwise the
    controls come from what this browser last held.
    """
    params: Mapping[str, str] = request.query_params
    from_link = has_search_params(params)
    remembered: Mapping[str, str] = app.storage.user.get("search", {})
    form = SearchForm.from_query(params if from_link else remembered)
    current: tuple[Search, SearchResult] | None = None
    """The last finished Search and its result. Its owner types are the ones fetched."""
    running = False
    cancelling = False
    stop = threading.Event()
    arrived: queue.Queue[list[Listing]] = queue.Queue()
    """Batches the worker thread hands to the page. Only the timer touches the UI."""
    live: list[Listing] = []
    live_search: Search | None = None

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

    async def search_clicked() -> None:
        nonlocal running, cancelling, stop, live_search, current
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
        while not arrived.empty():
            arrived.get_nowait()
        running, cancelling = True, False
        refresh_search_button()
        banner.set_visibility(False)
        chart.set_visibility(False)
        reset_button.set_visibility(False)
        curve_note.set_visibility(False)
        empty_label.set_visibility(False)
        status.set_text(f"Searching Craigslist for {search.make} {search.model} in {search.city}...")
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
        """Draw `result`, limited to the fetched owner types that are checked now."""
        wanted = {OwnerType.OWNER: form.owner, OwnerType.DEALER: form.dealer}
        search = replace(fetched, owner_types=tuple(t for t in fetched.owner_types if wanted[t]))
        missing = unfetched_message(fetched, [t for t, checked in wanted.items() if checked])
        message = empty_message(search, result) if final else None
        if not search.owner_types:
            message = missing or "Pick owner, dealer, or both"
            missing = None
        chart.set_visibility(message is None and bool(result.listings))
        empty_label.set_visibility(message is not None)
        if message is not None:
            empty_label.set_text(message)
        elif result.listings:
            chart.options.clear()
            chart.options.update(chart_options(search, result))
            chart.update()
            arm_drag_zoom()
        reset_button.set_visibility(chart.visible)
        notes = curve_notes(search, result) if final else []
        if missing and final:
            notes.append(missing)
        curve_note.set_visibility(bool(notes))
        curve_note.set_text(". ".join(notes))
        text = failure_banner(result)
        banner.set_visibility(text is not None)
        banner.set_text(text or "")
        if search.owner_types:
            status.set_text(status_text(search, result) if final else progress_text(len(result.listings)))

    # NiceGUI pads the page by 1rem on each side, so fill the rest of the window.
    with ui.column().classes("w-full h-[calc(100vh-2rem)] gap-2 no-wrap"):
        with ui.row().classes("w-full items-center gap-3"):
            ui.select(lookup.states(), value=form.state, label="State", with_input=True, on_change=lambda e: state_changed(e.value)).classes("w-24")
            city_select = ui.select(form.city_options(), value=form.city, label="City", with_input=True, on_change=lambda e: city_changed(e.value)).classes("w-56")
            ui.select(lookup.makes(), value=form.make, label="Make", with_input=True, on_change=lambda e: make_changed(e.value)).classes("w-44")
            model_select = ui.select(form.model_options(), value=form.model, label="Model", with_input=True, on_change=lambda e: model_changed(e.value)).classes("w-44")
            ui.checkbox("Owner", value=form.owner, on_change=lambda e: owner_changed(e.value))
            ui.checkbox("Dealer", value=form.dealer, on_change=lambda e: dealer_changed(e.value))
            search_button = ui.button("Search", on_click=search_clicked)
            hint = ui.label().classes("text-sm opacity-70")
        banner = ui.label().classes("w-full p-2 rounded bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100")
        banner.set_visibility(False)
        with ui.row().classes("w-full grow gap-4 no-wrap"):
            with ui.column().classes("grow h-full items-center justify-center"):
                chart = ui.echart({}).classes("w-full h-full")
                chart.set_visibility(False)
                with ui.row().classes("items-center gap-3"):
                    reset_button = ui.button("Reset zoom", on_click=reset_zoom).props("flat dense")
                    reset_button.set_visibility(False)
                    curve_note = ui.label().classes("text-sm opacity-70")
                    curve_note.set_visibility(False)
                empty_label = ui.label().classes("text-lg opacity-70")
                empty_label.set_visibility(False)
            ui.column().classes("w-80 h-full border rounded")  # Preview panel, a later ticket
        status = ui.label("Choose a car and press Search.").classes("text-sm opacity-70")
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
