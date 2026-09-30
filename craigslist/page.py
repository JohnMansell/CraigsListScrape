"""The Search page: toolbar of Search controls, price vs. mileage chart, status line.

The page may serve several people from one process, so every piece of Search state
lives inside `search_page`, one copy per browser tab. Nothing here is module-level state.
"""
import queue
import threading
from dataclasses import dataclass

from loguru import logger
from nicegui import run, ui

from craigslist import lookup
from craigslist.chart import chart_options, curve_notes, empty_message, failure_banner, progress_text, status_text
from craigslist.listings import Listing, OwnerType
from craigslist.search import Search, SearchError, SearchResult, run_live_search

HOST = "127.0.0.1"
"""Local only until the Linode ticket adds a --host flag."""
PORT = 8080
POLL_SECONDS = 0.25
"""How often the page draws the Listings that arrived since the last draw."""
TITLE = "Craigslist car prices"


@dataclass
class SearchForm:
    """What the toolbar currently holds, and whether it makes a Search."""

    state: str | None = None
    city: str | None = None
    make: str | None = None
    model: str | None = None
    owner: bool = True
    dealer: bool = True

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


def search_page() -> None:
    """Build one Search page for one browser tab."""
    form = SearchForm()
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

    def state_changed(state: str | None) -> None:
        form.choose_state(state)
        city_select.set_options(form.city_options(), value=None)
        refresh_search_button()

    def city_changed(city: str | None) -> None:
        form.city = city
        refresh_search_button()

    def make_changed(make: str | None) -> None:
        form.choose_make(make)
        model_select.set_options(form.model_options(), value=None)
        refresh_search_button()

    def model_changed(model: str | None) -> None:
        form.model = model
        refresh_search_button()

    def owner_changed(checked: bool) -> None:
        form.owner = checked
        refresh_search_button()

    def dealer_changed(checked: bool) -> None:
        form.dealer = checked
        refresh_search_button()

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
        nonlocal running, cancelling, stop, live_search
        if running:
            cancelling = True
            stop.set()
            refresh_search_button()
            return
        search = form.search()
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
        show(search, result, final=True)

    def arm_drag_zoom() -> None:
        """Make a plain drag on the chart select a region to zoom into."""
        chart.run_chart_method(
            "dispatchAction", {"type": "takeGlobalCursor", "key": "dataZoomSelect", "dataZoomSelectActive": True}
        )

    def reset_zoom() -> None:
        chart.run_chart_method("dispatchAction", {"type": "restore"})
        arm_drag_zoom()

    def show(search: Search, result: SearchResult, final: bool) -> None:
        message = empty_message(search, result) if final else None
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
        curve_note.set_visibility(bool(notes))
        curve_note.set_text(". ".join(notes))
        text = failure_banner(result)
        banner.set_visibility(text is not None)
        banner.set_text(text or "")
        status.set_text(status_text(search, result) if final else progress_text(len(result.listings)))

    # NiceGUI pads the page by 1rem on each side, so fill the rest of the window.
    with ui.column().classes("w-full h-[calc(100vh-2rem)] gap-2 no-wrap"):
        with ui.row().classes("w-full items-center gap-3"):
            ui.select(lookup.states(), label="State", with_input=True, on_change=lambda e: state_changed(e.value)).classes("w-24")
            city_select = ui.select([], label="City", with_input=True, on_change=lambda e: city_changed(e.value)).classes("w-56")
            ui.select(lookup.makes(), label="Make", with_input=True, on_change=lambda e: make_changed(e.value)).classes("w-44")
            model_select = ui.select([], label="Model", with_input=True, on_change=lambda e: model_changed(e.value)).classes("w-44")
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


def serve(port: int = PORT) -> None:
    """Serve the Search page until interrupted. Light or dark follows the browser."""
    logger.info("Search page on http://{}:{}", HOST, port)
    ui.run(search_page, host=HOST, port=port, title=TITLE, dark=None, reload=False)
