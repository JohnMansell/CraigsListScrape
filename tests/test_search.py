import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from craigslist.curve import NotEnoughData, PriceCurve
from craigslist import listings
from craigslist.listings import OwnerType
from craigslist.search import Search, SearchError, run_search


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def empty_response() -> str:
    response = json.loads(fixture("owner_full.json"))
    response["data"]["items"] = []
    return json.dumps(response)


def test_run_search_returns_listings_and_a_curve_per_owner_type():
    responses = {
        OwnerType.OWNER: fixture("owner_full.json"),
        OwnerType.DEALER: fixture("dealer_full.json"),
    }

    def fetch(url: str) -> str:
        return responses[OwnerType.DEALER if "purveyor=dealer" in url else OwnerType.OWNER]

    result = run_search(Search("CA", "Orange County", "honda", "civic"), fetch)

    assert {listing.owner_type for listing in result.listings} == {OwnerType.OWNER, OwnerType.DEALER}
    assert set(result.curves) == {OwnerType.OWNER, OwnerType.DEALER}
    assert all(isinstance(curve, PriceCurve) for curve in result.curves.values())


def test_run_search_returns_empty_listings_and_not_enough_data_per_owner_type():
    empty = empty_response()

    result = run_search(Search("CA", "Orange County", "honda", "civic"), lambda url: empty)

    assert result.listings == []
    assert all(isinstance(curve, NotEnoughData) for curve in result.curves.values())


@pytest.mark.parametrize(
    ("search", "message"),
    [
        (Search("XX", "Orange County", "honda", "civic"), "unknown state 'XX'"),
        (Search("CA", "Nowhere", "honda", "civic"), "unknown city 'Nowhere' in state 'CA'"),
        (Search("CA", "Orange County", "not-a-make", "civic"), "unknown make 'not-a-make'"),
        (Search("CA", "Orange County", "honda", "not-a-model"), "unknown model 'not-a-model' for make 'honda'"),
    ],
)
def test_run_search_rejects_unknown_lookup_values(search, message):
    with pytest.raises(SearchError, match=message):
        run_search(search, lambda url: pytest.fail("lookup validation should run before fetching"))


def test_run_search_reports_progress_once_per_api_request():
    progress: list[None] = []

    result = run_search(
        Search("CA", "Orange County", "honda", "civic", owner_types=(OwnerType.OWNER,)),
        lambda url: fixture("owner_full.json"),
        progress=lambda: progress.append(None),
    )

    assert len(result.listings) == 20
    assert progress == [None]


def test_run_search_reports_every_paged_api_request(monkeypatch):
    monkeypatch.setattr(listings, "FULL_PAGE_SIZE", 20)
    monkeypatch.setattr(listings, "BATCH_PAGE_SIZE", 20)
    responses = {
        "owner_full": fixture("owner_full.json"),
        "owner_cache": fixture("owner_cache.json"),
        "batch_0": fixture("owner_batch_0.json"),
        "batch_20": fixture("owner_batch_20.json"),
    }
    progress: list[None] = []

    def fetch(url: str) -> str:
        query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        step = query["batch"].split("-")
        if urlsplit(url).path.endswith("/batch"):
            response = f"batch_{step[1]}"
        elif step[1] == "0":
            response = "owner_full"
        else:
            response = "owner_cache"
        return responses[response]

    run_search(
        Search("CA", "Orange County", "honda", "civic", owner_types=(OwnerType.OWNER,)),
        fetch,
        progress=lambda: progress.append(None),
    )

    assert progress == [None, None, None, None]
