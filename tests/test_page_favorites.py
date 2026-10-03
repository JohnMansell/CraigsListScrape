"""The Favorites drawer and hidden Listings on the real Search page, driven by NiceGUI's simulated user."""
import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from nicegui import app, ui
from nicegui.storage import Storage
from nicegui.testing import user_simulation

from craigslist import page
from craigslist.chart import FAVORITES_NAME, PIN_NAME
from craigslist.curve import NotEnoughData
from craigslist.favorites import EMPTY_TEXT, FAVORITES_KEY, HIDDEN_KEY
from craigslist.listings import Listing, OwnerType, Source
from craigslist.preview import IDLE_TEXT
from craigslist.search import Search, SearchResult
from craigslist.sources import SOURCES

LINK = "/?state=CA&city=Sf%20Bay%20Area&make=Honda&model=Civic&carfax=0"
OWNER_CAR = Listing(
    "craigslist:1", Source.CRAIGSLIST, "2014 Honda Civic owner car", 9_000, 120_000,
    "https://sfbay.craigslist.org/view/d/1", (), OwnerType.OWNER, year=2014,
)
CARMAX_CAR = Listing(
    "carmax:2", Source.CARMAX, "2019 Honda Civic EX", 19_998, 41_000, "https://www.carmax.com/car/2",
    ("https://img2.carmax.com/img/vehicles/2/1.jpg",), OwnerType.DEALER,
    datetime(2026, 9, 1, tzinfo=UTC), "Pleasanton, CA", "CarMax Pleasanton", year=2019, trim="EX",
)


def series_data(chart: ui.echart, name: str) -> list:
    return next(series["data"] for series in chart.options["series"] if series["name"] == name)


def favorite_pins(chart: ui.echart) -> list:
    return series_data(chart, FAVORITES_NAME)


def fake_search(search: Search, fetch=None, on_batch=None, should_stop=None) -> SearchResult:
    few = NotEnoughData("too few points")
    return SearchResult(
        [OWNER_CAR, CARMAX_CAR],
        {owner_type: few for owner_type in search.owner_types},
        {owner_type: 1 for owner_type in search.owner_types},
        {source: few for source in search.sources},
        {source: 1 for source in search.sources},
    )


async def save_open_and_remove_a_favorite(searches: list[Search]) -> None:
    async with user_simulation(root=page.search_page) as user:
        # --- Search and Save
        await user.open(LINK)
        await user.should_see("★ Favorites (0)")
        await user.should_see(EMPTY_TEXT)
        await user.should_see(SOURCES[Source.CARMAX].name)
        await user.should_see(ui.echart, retries=20)  # the link's Search starts on a 0.1 s timer
        user.find(ui.echart).trigger(
            "chart:mouseover", {"seriesType": "scatter", "seriesName": "CarMax", "dataIndex": 0}
        )
        await user.should_see("Open on CarMax")
        user.find(kind=ui.button, content="☆ Save").click()
        await user.should_see("★ Saved")
        await user.should_see("★ Favorites (1)")
        await user.should_see("CarMax  ·  saved")
        with user:
            stored = app.storage.user[FAVORITES_KEY]
        assert [entry["listing"]["id"] for entry in stored] == [CARMAX_CAR.id]
        assert stored[0]["search"] == {"state": "CA", "city": "Sf Bay Area", "make": "Honda", "model": "Civic"}
        await user.should_not_see(EMPTY_TEXT)

        # --- Pins Follow Save And Remove Without A Search
        chart = user.find(ui.echart).elements.pop()
        assert favorite_pins(chart) == [[41_000, 19_998]]
        user.find(kind=ui.button, content="★ Saved").click()
        await user.should_see("★ Favorites (0)")
        assert favorite_pins(chart) == []
        user.find(kind=ui.button, content="☆ Save").click()
        await user.should_see("★ Favorites (1)")
        assert favorite_pins(chart) == [[41_000, 19_998]]
        assert len(searches) == 1

        # --- Reload Without A Search, Pin From The Drawer
        await user.open("/")
        await user.should_see("★ Favorites (1)")
        await user.should_not_see("Open on CarMax")
        user.find(marker="favorite").click()
        await user.should_see("Open on CarMax")
        await user.should_see("★ Saved")
        await user.should_see("On sale since 2026-09-01 00:00 UTC")

        # --- Remove With The Cross
        user.find("✕").click()
        await user.should_see("★ Favorites (0)")
        await user.should_see(EMPTY_TEXT)
        await user.should_see(kind=ui.button, content="☆ Save")


def test_a_favorite_is_saved_kept_over_a_reload_pinned_and_removed(tmp_path, monkeypatch):
    # NiceGUI's reset deletes every storage file under Storage.path, so point it at a scratch dir.
    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    searches: list[Search] = []

    def counted_search(search: Search, *args) -> SearchResult:
        searches.append(search)
        return fake_search(search, *args)

    monkeypatch.setattr(page, "run_live_search", counted_search)
    monkeypatch.setattr(page, "load_details", lambda listing: {})

    asyncio.run(save_open_and_remove_a_favorite(searches))


async def later_searches_update_a_favorite(results: list[list[Listing]]) -> None:
    async with user_simulation(root=page.search_page) as user:
        # --- Save From The First Search
        await user.open(LINK)
        await user.should_see(ui.echart, retries=20)
        user.find(ui.echart).trigger(
            "chart:mouseover", {"seriesType": "scatter", "seriesName": "CarMax", "dataIndex": 0}
        )
        user.find(kind=ui.button, content="☆ Save").click()
        await user.should_see("★ Favorites (1)")

        # --- A Cheaper Return Shows The Price Change
        results.append([replace(CARMAX_CAR, price=17_500)])
        user.find(kind=ui.button, content="Search").click()
        await user.should_see("$17,500, was $19,998 when saved  |  41,000 mi", retries=20)
        user.find(ui.echart).trigger(
            "chart:mouseover", {"seriesType": "scatter", "seriesName": "CarMax", "dataIndex": 0}
        )
        await user.should_see("$17,500, was $19,998 when saved  |  41,000 mi")

        # --- A Covering Search Without It Marks It Missing
        results.append([OWNER_CAR])
        user.find(kind=ui.button, content="Search").click()
        await user.should_see("Not in latest Search", retries=20)
        with user:
            stored = app.storage.user[FAVORITES_KEY]
        assert stored[0]["saved_price"] == 19_998
        assert stored[0]["listing"]["price"] == 17_500
        assert stored[0]["missing_since"] is not None


def test_later_searches_update_a_favorites_price_and_mark_it_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    results: list[list[Listing]] = [[OWNER_CAR, CARMAX_CAR]]

    def latest_search(search: Search, *args) -> SearchResult:
        return replace(fake_search(search, *args), listings=list(results[-1]))

    monkeypatch.setattr(page, "run_live_search", latest_search)
    monkeypatch.setattr(page, "load_details", lambda listing: {})

    asyncio.run(later_searches_update_a_favorite(results))


async def hide_and_unhide_a_car(searches: list[Search]) -> None:
    async with user_simulation(root=page.search_page) as user:
        # --- Save, Then Hide: The Point Goes Without A Search
        await user.open(LINK)
        await user.should_see(ui.echart, retries=20)
        await user.should_see("Hidden (0)")
        user.find(ui.echart).trigger(
            "chart:mouseover", {"seriesType": "scatter", "seriesName": "CarMax", "dataIndex": 0}
        )
        user.find(kind=ui.button, content="☆ Save").click()
        await user.should_see("★ Favorites (1)")
        user.find(marker="hide-toggle").click()
        await user.should_see("Hidden (1)")
        await user.should_see("★ Favorites (0)")
        await user.should_see("CarMax  ·  hidden")
        chart = user.find(ui.echart).elements.pop()
        assert series_data(chart, "CarMax") == [] and favorite_pins(chart) == []
        assert series_data(chart, "Owner") == [[120_000, 9_000]]
        await user.should_see("2 listings: 1 owner, 0 dealer, 1 CarMax. 1 hidden")
        with user:
            assert [entry["listing"]["id"] for entry in app.storage.user[HIDDEN_KEY]] == [CARMAX_CAR.id]
            assert app.storage.user[FAVORITES_KEY] == []
        assert len(searches) == 1

        # --- Kept Over A Reload And A Later Search
        await user.open("/")
        await user.should_see("Hidden (1)")
        user.find(kind=ui.button, content="Search").click()
        await user.should_see("1 hidden", retries=20)
        chart = user.find(ui.echart).elements.pop()
        assert series_data(chart, "CarMax") == []
        assert len(searches) == 2

        # --- Pin From The Hidden Tab, Then Unhide From Preview
        user.find(marker="hidden").click()
        await user.should_see("Open on CarMax")
        await user.should_see(kind=ui.button, content="Unhide")
        assert series_data(chart, PIN_NAME) == []
        user.find(marker="hide-toggle").click()
        await user.should_see("Hidden (0)")
        assert series_data(chart, "CarMax") == [[41_000, 19_998]]
        assert series_data(chart, PIN_NAME) == [[41_000, 19_998]]
        await user.should_not_see("1 hidden")

        # --- Hiding The Pinned Listing Clears The Pin
        user.find(marker="hide-toggle").click()
        await user.should_see("Hidden (1)")
        await user.should_see(IDLE_TEXT)
        assert series_data(chart, PIN_NAME) == [] and series_data(chart, "CarMax") == []

        # --- Saving A Hidden Car Unhides It
        user.find(marker="hidden").click()
        await user.should_see("Open on CarMax")
        user.find(kind=ui.button, content="☆ Save").click()
        await user.should_see("★ Favorites (1)")
        await user.should_see("Hidden (0)")
        assert favorite_pins(chart) == [[41_000, 19_998]]

        # --- Unhide From The Drawer
        user.find(marker="hide-toggle").click()
        await user.should_see("Hidden (1)")
        await user.should_see("★ Favorites (0)")
        user.find(marker="unhide").click()
        await user.should_see("Hidden (0)")
        assert series_data(chart, "CarMax") == [[41_000, 19_998]]
        assert len(searches) == 2


def test_a_hidden_car_is_not_drawn_kept_over_a_reload_and_unhidden(tmp_path, monkeypatch):
    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    searches: list[Search] = []

    def counted_search(search: Search, *args) -> SearchResult:
        searches.append(search)
        return fake_search(search, *args)

    monkeypatch.setattr(page, "run_live_search", counted_search)
    monkeypatch.setattr(page, "load_details", lambda listing: {})

    asyncio.run(hide_and_unhide_a_car(searches))


async def open_a_favorite_from_another_search() -> None:
    async with user_simulation(root=page.search_page) as user:
        await user.open(LINK)
        await user.should_see(ui.echart, retries=20)
        user.find(ui.echart).trigger(
            "chart:mouseover", {"seriesType": "scatter", "seriesName": "Owner", "dataIndex": 0}
        )
        user.find(kind=ui.button, content="☆ Save").click()
        await user.should_see("★ Favorites (1)")

        await user.open("/")  # no Search, so the favorite is outside the shown results
        user.find(marker="favorite").click()
        await user.should_see(OWNER_CAR.title)
        await user.should_see("No details available")


def test_a_favorite_opened_from_the_drawer_outside_the_results_fetches_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    fetched: list[Listing] = []
    monkeypatch.setattr(page, "run_live_search", fake_search)
    monkeypatch.setattr(page, "load_details", lambda listing: fetched.append(listing) or {})

    asyncio.run(open_a_favorite_from_another_search())

    assert fetched == []


def key(name: str, action: str = "keydown", ctrl: bool = False) -> dict:
    """The arguments ui.keyboard's browser side sends for one key event."""
    return {
        "action": action, "repeat": False, "altKey": False, "ctrlKey": ctrl, "metaKey": False,
        "shiftKey": False, "key": name, "code": f"Key{name.upper()}", "location": 0,
    }


def menu_text(user, marker: str) -> str:
    """The label of the point menu's item with this marker."""
    item = user.find(marker=marker).elements.pop()
    return item.default_slot.children[0].text


def stored_ids(user, key_name: str) -> list[str]:
    with user:
        return [entry["listing"]["id"] for entry in app.storage.user[key_name]]


async def save_and_hide_with_hotkeys(searches: list[Search]) -> None:
    async with user_simulation(root=page.search_page) as user:
        # --- F Saves The Hovered Car, Modified Or Released Keys Do Nothing
        await user.open(LINK)
        await user.should_see(ui.echart, retries=20)
        keyboard = user.find(ui.keyboard)
        keyboard.trigger("key", key("f"))  # no car in Preview yet
        await user.should_see("★ Favorites (0)")
        user.find(ui.echart).trigger(
            "chart:mouseover", {"seriesType": "scatter", "seriesName": "CarMax", "dataIndex": 0}
        )
        keyboard.trigger("key", key("f", ctrl=True)).trigger("key", key("f", action="keyup"))
        await user.should_see("★ Favorites (0)")
        keyboard.trigger("key", key("F"))
        await user.should_see("★ Favorites (1)")
        await user.should_see(kind=ui.button, content="★ Saved")
        assert stored_ids(user, FAVORITES_KEY) == [CARMAX_CAR.id]

        # --- H Hides It Without A Search
        keyboard.trigger("key", key("h"))
        await user.should_see("Hidden (1)")
        await user.should_see("★ Favorites (0)")
        chart = user.find(ui.echart).elements.pop()
        assert series_data(chart, "CarMax") == []
        keyboard.trigger("key", key("h"))  # Preview shows no car now
        await user.should_see("Hidden (1)")

        # --- The Pinned Listing Wins Over The Hovered One
        user.find(marker="hidden").click()
        await user.should_see("Open on CarMax")
        user.find(ui.echart).trigger(
            "chart:mouseover", {"seriesType": "scatter", "seriesName": "Owner", "dataIndex": 0}
        )
        keyboard.trigger("key", key("h"))
        await user.should_see("Hidden (0)")
        assert series_data(chart, "CarMax") == [[41_000, 19_998]]
        keyboard.trigger("key", key("f"))
        await user.should_see("★ Favorites (1)")
        assert stored_ids(user, FAVORITES_KEY) == [CARMAX_CAR.id]
        assert len(searches) == 1


def test_f_and_h_save_and_hide_the_car_in_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    searches: list[Search] = []

    def counted_search(search: Search, *args) -> SearchResult:
        searches.append(search)
        return fake_search(search, *args)

    monkeypatch.setattr(page, "run_live_search", counted_search)
    monkeypatch.setattr(page, "load_details", lambda listing: {})

    asyncio.run(save_and_hide_with_hotkeys(searches))


async def save_and_hide_from_the_point_menu(searches: list[Search]) -> None:
    async with user_simulation(root=page.search_page) as user:
        # --- Empty Space Opens Nothing
        await user.open(LINK)
        await user.should_see(ui.echart, retries=20)
        menu = user.find(ui.menu).elements.pop()
        user.find(ui.echart).trigger("chart:contextmenu", {"x": 5, "y": 5})
        assert not menu.value

        # --- Save From The Menu
        point = {"seriesType": "scatter", "seriesName": "CarMax", "dataIndex": 0, "x": 120, "y": 80}
        user.find(ui.echart).trigger("chart:contextmenu", point)
        assert menu.value
        assert menu.parent_slot is not None and menu.parent_slot.parent._style["left"] == "120px"
        assert (menu_text(user, "menu-save"), menu_text(user, "menu-hide")) == ("☆ Save", "Hide")
        user.find(marker="menu-save").click()
        await user.should_see("★ Favorites (1)")
        assert not menu.value
        assert stored_ids(user, FAVORITES_KEY) == [CARMAX_CAR.id]

        # --- Hide From The Menu Without A Search
        user.find(ui.echart).trigger("chart:contextmenu", point)
        assert menu_text(user, "menu-save") == "★ Saved"
        user.find(marker="menu-hide").click()
        await user.should_see("Hidden (1)")
        await user.should_see("★ Favorites (0)")
        chart = user.find(ui.echart).elements.pop()
        assert series_data(chart, "CarMax") == []
        assert stored_ids(user, HIDDEN_KEY) == [CARMAX_CAR.id]
        assert len(searches) == 1


def test_right_clicking_a_point_offers_save_and_hide(tmp_path, monkeypatch):
    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    searches: list[Search] = []

    def counted_search(search: Search, *args) -> SearchResult:
        searches.append(search)
        return fake_search(search, *args)

    monkeypatch.setattr(page, "run_live_search", counted_search)
    monkeypatch.setattr(page, "load_details", lambda listing: {})

    asyncio.run(save_and_hide_from_the_point_menu(searches))
