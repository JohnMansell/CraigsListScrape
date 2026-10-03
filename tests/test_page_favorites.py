"""The Favorites drawer on the real Search page, driven by NiceGUI's simulated user."""
import asyncio
from datetime import UTC, datetime

from nicegui import app, ui
from nicegui.storage import Storage
from nicegui.testing import user_simulation

from craigslist import page
from craigslist.curve import NotEnoughData
from craigslist.favorites import EMPTY_TEXT, FAVORITES_KEY
from craigslist.listings import Listing, OwnerType, Source
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


def fake_search(search: Search, fetch=None, on_batch=None, should_stop=None) -> SearchResult:
    few = NotEnoughData("too few points")
    return SearchResult(
        [OWNER_CAR, CARMAX_CAR],
        {owner_type: few for owner_type in search.owner_types},
        {owner_type: 1 for owner_type in search.owner_types},
        {source: few for source in search.sources},
        {source: 1 for source in search.sources},
    )


async def save_open_and_remove_a_favorite() -> None:
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
    monkeypatch.setattr(page, "run_live_search", fake_search)
    monkeypatch.setattr(page, "load_details", lambda listing: {})

    asyncio.run(save_open_and_remove_a_favorite())
