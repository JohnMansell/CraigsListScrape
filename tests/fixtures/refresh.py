"""Re-fetch the saved search API responses in this directory and trim them.

    uv run python tests/fixtures/refresh.py

Run it on purpose, when you want to check the fixtures against today's API, then
run the tests and read the diff. Each response keeps its real metadata, but its
results are cut down to PAGE_SIZE, picked so every layout variant the tests need
is present. The tests shrink the page sizes to PAGE_SIZE to exercise paging.

- owner_full.json: step 1, Orange County owner. Has results with no photos and
  with the extra integer after the image suffix.
- owner_cache.json: step 2 for the same search (cache id and max posted time).
- owner_batch_0.json: a full batch page. Has results with no price, no mileage,
  no photos, and duplicate image codes.
- owner_batch_20.json: a short batch page, which ends paging.
- dealer_full.json: step 1, Orange County honda civic dealer. The API reports a
  total below the number of results it returns.
- carfax_page_1.json: Honda Civic, zip 94103, radius 50 - first page, full. One
  listing has its price and mileage removed, to give the tests a listing with
  neither (not seen missing live).
- carfax_page_2.json: the same search, page 2 - a later full page.
- carfax_last_page.json: Honda Fit, same zip/radius - the last, short page.
- carfax_empty.json: an unknown model - a search with no results (totalListingCount,
  totalPageCount and listings all absent, not zero or empty).
- carmax_page_1.json: Honda Civic, zip 94103, radius-50, shipping=0 - first page, full.
  One listing has its price and mileage removed, to give the tests a listing with
  neither (not seen missing live).
- carmax_page_2.json: the same search, skip 20 - a later full page.
- carmax_last_page.json: the same search, skip 40 - the last, short page.
- carmax_empty.json: Honda Prelude, same zip/radius - a real model with no stock in
  range (totalCount 0, items empty).
- carmax_unknown_model.json: an unknown model slug - CarMax ignores it and returns the
  whole make, and selectedFacets has no model entry.
Each CarMax response keeps selectedFacets as (category, value) pairs, the check for an
ignored slug.
"""
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from craigslist import listings  # noqa: E402
from craigslist.listings import HttpFetcher, OwnerType, Search  # noqa: E402
from craigslist.lookup import City  # noqa: E402

FIXTURES = Path(__file__).resolve().parent
PAGE_SIZE = 20
SHORT_PAGE_SIZE = 7
PER_VARIANT = 2
ORANGE_COUNTY = City("Orange County", "https://orangecounty.craigslist.org")

CARFAX_API = "https://helix.carfax.com/search/v2/vehicles"
CARFAX_ZIP = "94103"
CARFAX_RADIUS = 50
CARFAX_LISTING_FIELDS = (
    "id", "vin", "year", "make", "model", "trim", "mileage", "currentPrice",
    "images", "dealer", "firstSeen", "oneOwner", "noAccidents", "accidentHistory",
    "priceHistory", "vdpUrl",
)
CARFAX_DEALER_FIELDS = ("name", "city", "state")

CARMAX_API = "https://www.carmax.com/cars/api/search/run"
CARMAX_PAGE = "https://www.carmax.com/cars/honda/civic"
CARMAX_ZIP = "94103"
CARMAX_RADIUS = 50
CARMAX_PAUSE = 1.0
CARMAX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Referer": CARMAX_PAGE,
}
CARMAX_RESPONSE_FIELDS = ("totalCount", "take", "searchFailed", "hasSearchError")
CARMAX_LISTING_FIELDS = (
    "stockNumber", "vin", "year", "make", "model", "trim", "body", "basePrice", "originalPrice",
    "hasPriceDrop", "mileage", "storeName", "storeCity", "stateAbbreviation", "distance",
    "lastMadeSaleableDate", "highlights", "heroImageUrl", "isSaleable", "exteriorColor", "transmission",
)

Item = list[Any]


def tags(item: Item) -> set[int]:
    return set(listings._tagged(item))


def image_codes(item: Item) -> list[str]:
    return [code for field in item if isinstance(field, list) for code in field if str(code).startswith("3:")]


def pick(items: list[Item], variants: list[Callable[[Item], bool]], size: int) -> list[Item]:
    """PER_VARIANT results of each variant, then the earliest others, in API order."""
    chosen: set[int] = set()
    for is_variant in variants:
        chosen.update([index for index, item in enumerate(items) if is_variant(item)][:PER_VARIANT])
    for index in range(len(items)):
        if len(chosen) >= size:
            break
        chosen.add(index)
    return [items[index] for index in sorted(chosen)]


def save(name: str, response: dict[str, Any]) -> None:
    path = FIXTURES / name
    path.write_text(json.dumps(response, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {path.name}")


def refresh_owner(fetch: listings.HttpFetcher) -> None:
    search = Search(ORANGE_COUNTY, owner_types=(OwnerType.OWNER,))
    full = json.loads(fetch(listings.full_url(search, OwnerType.OWNER)))
    items = full["data"]["items"]
    if len(items) < listings.FULL_PAGE_SIZE:
        sys.exit(f"owner search returned {len(items)} results, need {listings.FULL_PAGE_SIZE} to page")
    full["data"]["items"] = pick(
        items, [lambda item: listings.TAG_IMAGES not in tags(item), lambda item: isinstance(item[6], int)], PAGE_SIZE
    )
    save("owner_full.json", full)

    cache_ts = full["data"]["cacheTs"]
    cache = json.loads(fetch(listings.cache_url(search, OwnerType.OWNER, cache_ts)))
    cache["data"]["items"] = cache["data"]["items"][:PAGE_SIZE]
    save("owner_cache.json", cache)

    # Every result from every batch, with post id offsets moved onto the first batch's minPostingId.
    batch_0: dict[str, Any] | None = None
    pool: list[Item] = []
    for offset in range(0, listings.MAX_BATCH_REQUESTS * listings.BATCH_PAGE_SIZE, listings.BATCH_PAGE_SIZE):
        url = listings.batch_url(offset, cache["data"]["cacheId"], cache["data"]["maxPostedTs"], cache_ts)
        batch = json.loads(fetch(url))
        batch_0 = batch_0 or batch
        shift = batch["data"]["minPostingId"] - batch_0["data"]["minPostingId"]
        pool += [[item[0] + shift, *item[1:]] for item in batch["data"]["batch"]]
        if len(batch["data"]["batch"]) < listings.BATCH_PAGE_SIZE:
            break
    assert batch_0 is not None

    first = pick(
        pool,
        [
            lambda item: listings.TAG_PRICE not in tags(item),
            lambda item: listings.TAG_ODOMETER not in tags(item),
            lambda item: item[2] == [],
            lambda item: len(image_codes(item)) != len(set(image_codes(item))),
        ],
        PAGE_SIZE,
    )
    batch_0["data"]["batch"] = first
    save("owner_batch_0.json", batch_0)
    batch_0["data"]["batch"] = [item for item in pool if item not in first][-SHORT_PAGE_SIZE:]
    save("owner_batch_20.json", batch_0)


def refresh_dealer(fetch: listings.HttpFetcher) -> None:
    search = Search(ORANGE_COUNTY, "honda", "civic", owner_types=(OwnerType.DEALER,))
    full = json.loads(fetch(listings.full_url(search, OwnerType.DEALER)))
    data = full["data"]
    print(f"dealer search: {len(data['items'])} results, API reported {data['totalResultCount']}")
    data["items"] = data["items"][:PAGE_SIZE]
    if len(data["items"]) <= data["totalResultCount"]:
        print("warning: the trimmed dealer results no longer outnumber the reported total")
    save("dealer_full.json", full)


def carfax_url(make: str, model: str, page: int, rows: int = PAGE_SIZE) -> str:
    params = {"zip": CARFAX_ZIP, "radius": CARFAX_RADIUS, "make": make, "model": model,
              "vehicleCondition": "USED", "rows": rows, "page": page}
    return f"{CARFAX_API}?{'&'.join(f'{key}={value}' for key, value in params.items())}"


def trim_carfax_listing(item: dict[str, Any]) -> dict[str, Any]:
    trimmed = {key: item[key] for key in CARFAX_LISTING_FIELDS if key in item}
    trimmed["dealer"] = {key: trimmed["dealer"][key] for key in CARFAX_DEALER_FIELDS}
    return trimmed


def trim_carfax_response(response: dict[str, Any], count: int) -> dict[str, Any]:
    listings_ = [trim_carfax_listing(item) for item in response["listings"][:count]]
    return {key: response[key] for key in ("totalListingCount", "page", "pageSize", "totalPageCount")} | {
        "listings": listings_
    }


def refresh_carfax(fetch: HttpFetcher) -> None:
    page_1 = json.loads(fetch(carfax_url("Honda", "Civic", page=1)))
    if len(page_1["listings"]) < PAGE_SIZE:
        sys.exit(f"carfax civic page 1 returned {len(page_1['listings'])} results, need {PAGE_SIZE} to page")
    trimmed_1 = trim_carfax_response(page_1, PAGE_SIZE)
    trimmed_1["listings"][0].pop("currentPrice", None)
    trimmed_1["listings"][0].pop("mileage", None)
    save("carfax_page_1.json", trimmed_1)

    page_2 = json.loads(fetch(carfax_url("Honda", "Civic", page=2)))
    save("carfax_page_2.json", trim_carfax_response(page_2, PAGE_SIZE))

    last_page = json.loads(fetch(carfax_url("Honda", "Fit", page=2)))
    if len(last_page["listings"]) >= PAGE_SIZE:
        sys.exit("carfax fit page 2 is no longer short; pick a rarer model to refresh the last-page fixture")
    save("carfax_last_page.json", trim_carfax_response(last_page, len(last_page["listings"])))

    empty = json.loads(fetch(carfax_url("Honda", "Zzznotreal", page=1)))
    if "listings" in empty or "totalListingCount" in empty:
        sys.exit("carfax empty-search response now has results; pick another nonsense model")
    save("carfax_empty.json", {key: empty.get(key) for key in ("page", "pageSize", "totalPageCount")})


class CarmaxFetcher:
    """HTTP/2 client with browser headers, warmed up once. CarMax's Akamai 403s the first request."""

    def __init__(self) -> None:
        self.client = httpx.Client(headers=CARMAX_HEADERS, timeout=30, http2=True)
        self.client.get(CARMAX_PAGE)
        time.sleep(CARMAX_PAUSE)

    def __call__(self, uri: str, skip: int, take: int = PAGE_SIZE) -> dict[str, Any]:
        params = {"uri": uri, "zipCode": CARMAX_ZIP, "radius": f"radius-{CARMAX_RADIUS}",
                  "shipping": 0, "sort": "price-asc", "skip": skip, "take": take}
        response = self.client.get(f"{CARMAX_API}?{urlencode(params, safe='/')}")
        response.raise_for_status()
        time.sleep(CARMAX_PAUSE)
        return response.json()

    def close(self) -> None:
        self.client.close()


def trim_carmax_response(response: dict[str, Any], count: int) -> dict[str, Any]:
    items = [{key: item[key] for key in CARMAX_LISTING_FIELDS if key in item} for item in response["items"][:count]]
    facets = [{key: facet[key] for key in ("category", "value")} for facet in response["selectedFacets"]]
    return {key: response[key] for key in CARMAX_RESPONSE_FIELDS} | {"selectedFacets": facets, "items": items}


def refresh_carmax(fetch: CarmaxFetcher) -> None:
    page_1 = fetch("/cars/honda/civic", 0)
    if len(page_1["items"]) < PAGE_SIZE:
        sys.exit(f"carmax civic page 1 returned {len(page_1['items'])} results, need {PAGE_SIZE} to page")
    trimmed_1 = trim_carmax_response(page_1, PAGE_SIZE)
    trimmed_1["items"][0].pop("basePrice", None)
    trimmed_1["items"][0].pop("mileage", None)
    save("carmax_page_1.json", trimmed_1)

    page_2 = fetch("/cars/honda/civic", PAGE_SIZE)
    if len(page_2["items"]) < PAGE_SIZE:
        sys.exit("carmax civic page 2 is short; the later-page fixture needs a full page")
    save("carmax_page_2.json", trim_carmax_response(page_2, PAGE_SIZE))

    last_page = fetch("/cars/honda/civic", 2 * PAGE_SIZE)
    if not 0 < len(last_page["items"]) < PAGE_SIZE:
        sys.exit("carmax civic page 3 is no longer short and non-empty; pick another model for the last-page fixture")
    save("carmax_last_page.json", trim_carmax_response(last_page, len(last_page["items"])))

    empty = fetch("/cars/honda/prelude", 0)
    if empty["items"] or empty["totalCount"]:
        sys.exit("carmax prelude search now has results; pick another model with no stock near the zip")
    save("carmax_empty.json", trim_carmax_response(empty, 0))

    unknown = fetch("/cars/honda/zzznotreal", 0)
    if any(facet["category"] in ("model", "series") for facet in unknown["selectedFacets"]):
        sys.exit("carmax now recognises the nonsense model; pick another")
    save("carmax_unknown_model.json", trim_carmax_response(unknown, PAGE_SIZE))


def main() -> None:
    fetch = listings.HttpFetcher()
    try:
        refresh_owner(fetch)
        refresh_dealer(fetch)
        refresh_carfax(fetch)
    finally:
        fetch.close()
    carmax = CarmaxFetcher()
    try:
        refresh_carmax(carmax)
    finally:
        carmax.close()


if __name__ == "__main__":
    main()
