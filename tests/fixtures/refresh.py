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
"""
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from craigslist import listings  # noqa: E402
from craigslist.listings import OwnerType, Search  # noqa: E402
from craigslist.lookup import City  # noqa: E402

FIXTURES = Path(__file__).resolve().parent
PAGE_SIZE = 20
SHORT_PAGE_SIZE = 7
PER_VARIANT = 2
ORANGE_COUNTY = City("Orange County", "https://orangecounty.craigslist.org")

Item = list[Any]


def tags(item: Item) -> set[int]:
    return {field[0] for field in item if isinstance(field, list) and field and isinstance(field[0], int)}


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


def main() -> None:
    fetch = listings.HttpFetcher()
    try:
        refresh_owner(fetch)
        refresh_dealer(fetch)
    finally:
        fetch.close()


if __name__ == "__main__":
    main()
