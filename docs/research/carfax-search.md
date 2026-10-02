# Carfax search: the helix API

Research for issue #26, part of #24. Run 2026-10-02 from one IP with plain `httpx`
and a desktop Firefox User-Agent, no cookies or key. Carfax can change any of this
without notice; the API is undocumented. Builds on the findings already recorded
on #24 from `prototypes/carfax_probe.py` (branch `prototype/carfax`).

## The endpoint

`GET https://helix.carfax.com/search/v2/vehicles`

| Parameter | Notes |
| --- | --- |
| `zip` | required. A bad or unknown zip gives **400**: `rpc error: code = InvalidArgument desc = Invalid Zip <zip>` |
| `radius` | miles |
| `make`, `model` | Carfax's own spelling (see below); omit `model` to search the whole make |
| `vehicleCondition` | `USED` for this app |
| `rows` | page size, **capped at 25**; `rows=26` silently serves 25 |
| `page` | **1-based**, capped at 50 (`page=51` gives 400 `Page must be <= 50`); a page past `totalPageCount` (computed from `rows`) returns 200 with an empty `listings` list, not an error |
| `priceMin`, `priceMax` | filter server-side, so they get past the 1250-listing cap (50 pages x 25 rows). `priceMax=0` is ignored (treated as no max), so only pass a real positive bound |
| `sort` | `PRICE_ASC` seen working; not needed if paging by price band already orders bands |

Response fields used: `totalListingCount`, `page`, `pageSize`, `totalPageCount`, `listings`. The rest (`facetCountMap`, `relatedLinks`, `breadCrumbs`, `searchRequest`, `seoUrl`, `sortTpType`) is page-building cruft the app doesn't need.

### A search with no results

`totalListingCount`, `totalPageCount` and `listings` are **all absent from the response**, not zero or empty — the same shape Craigslist's `"decode": 0` quirk has. Seen for an unknown make, an unknown model, and a real make/model with nothing within radius. Read all three with `.get(..., default)`, never by indexing.

### Make and model spelling

Carfax matches its own spelling exactly, case-insensitively for the value given but not forgivingly for the value itself:

| Query | Result |
| --- | --- |
| `make=honda&model=civic` (lowercase) | 443 results, same as `Honda`/`Civic` |
| `make=Ford&model=F-150` | 304 results |
| `make=Ford&model=F150` (no hyphen) | 0 results (empty-search shape above) |
| `make=Mercedes-Benz` | 1539 results |
| `make=Mercedes Benz` (space, no hyphen) | 0 results |

So the app must store Carfax's exact make/model strings (issue #28) rather than reusing Craigslist's or guessing a normalization; case can be left alone, punctuation can't.

`facetCountMap.make.facets` and `facetCountMap.model.facets` in a response list Carfax's own names and result counts for the current make (seen: Civic 443, CR-V 408, Accord 385, ... down to S2000 1), which is how #28 can check the CSV against Carfax's live spelling.

### Paging

25 rows/page, up to page 50, so 1250 listings is the hard ceiling per `zip`+`radius`+`make`+`model`+price-band combination. Page the normal way (page 1, 2, 3, ... until a short page), the same rule Craigslist's `batch` paging uses: don't trust the reported total to decide when to stop, because:

- A page past the last one is 200 with an empty list, not 400 — so paging can also stop on an empty page, not only a short one.
- `totalListingCount` was accurate in every search tried here (unlike Craigslist's local-only count), but nothing guarantees that holds for every zip/radius, so treat it as a hint, not a stop condition.

When `totalListingCount` is over 1250, split by `priceMin`/`priceMax` bands and page each band the same way; a listing's price can't move between the fetch of one band and the next, so no de-dup logic is needed across bands in principle, but dealers editing a price mid-search is possible, so issue #30 dedupes by `id` anyway.

## Listing fields

One `Honda Civic` listing, fields relevant to this app (there are ~70 fields total; the rest is dealer-page styling and financing estimates):

| App field | Carfax field | Notes |
| --- | --- | --- |
| id | `id` | string: VIN + dealer id + first-seen date, e.g. `19XFL2H85SE026451MTNZY6EJL620260805` |
| vin | `vin` | |
| year/make/model/trim | `year`, `make`, `model`, `trim` | `trim` can be `"Unspecified"` |
| mileage | `mileage` | int; not confirmed missing on any listing seen (75+ checked across #24's prototype and this session) |
| price | `currentPrice` | int; `listPrice` is the same value before the day's drop, use `currentPrice` |
| images | `images.large` / `images.medium` / `images.small` | each a list of full URLs (CDN `carfax-img.vast.com`), not codes to template; `images.firstPhoto.*` is the same as index 0; a listing can have an empty list but the key itself was always present |
| dealer | `dealer.name`, `dealer.city`, `dealer.state` | always present (dealers only, no private sellers) |
| first seen | `firstSeen` | `"YYYY-MM-DD"` string |
| one owner | `oneOwner` | bool |
| no accidents | `noAccidents` | bool; `accidentHistory.accidentSummary` has the human text when accidents are reported |
| price history | `priceHistory` | list of `{listPrice, date, difference}`, newest first, `difference` omitted on the oldest entry; a drop is any entry with a negative `difference` |
| link | `vdpUrl` | `https://www.carfax.com/vehicle/<vin>` |

## `www.carfax.com` vs `helix.carfax.com`

- `www.carfax.com/robots.txt` disallows `/search`, `/api/`, and `/vehicle/` (the `vdpUrl` path), among others. This governs crawling `www.carfax.com`, not a person clicking a `vdpUrl` link the app shows them.
- `helix.carfax.com/robots.txt` is **404** (no robots file at all).
- A plain `httpx` GET on a `www.carfax.com/search` URL returns Cloudflare/DataDome's 403 "Please enable JS and disable any ad blocker" page (confirmed on #24's prototype run); `helix.carfax.com` answers every request tried here with 200 and no JS challenge.
- Carfax's consumer terms of use (carfax.com/company/terms-of-use) ban extraction tools and scraping vehicle lists, and limit use to personal, non-commercial use. Decision on #24/#25: build it, keep it local-use only, no on/off flag yet; separating it from anything deployed to friends/family is a later ticket.

## Fixtures

Saved in `tests/fixtures/`, refreshable with `uv run python tests/fixtures/refresh.py`:

- `carfax_page_1.json`: Honda Civic, zip 94103, radius 50 (443 results that day) — first page, full.
- `carfax_page_2.json`: same search, page 2 — a later full page, to exercise paging continuing.
- `carfax_last_page.json`: Honda Fit, same zip/radius (29 results that day) — the last, short page.
- `carfax_empty.json`: an unknown model — a search with no results (the all-fields-absent shape above).

Each is trimmed to a handful of listings (`PAGE_SIZE` in `refresh.py`), the same way `tests/fixtures/refresh.py` trims the Craigslist fixtures; a real listing's price and mileage are edited out of one trimmed entry in `carfax_page_1.json` to give the tests a missing-price and a missing-mileage case, since neither was seen missing live.
