# CarMax search: the cars/api/search API

Research for issue #43, part of #41. Run 2026-10-02 from one IP with `httpx` over
HTTP/2, a desktop Firefox User-Agent and no login, about 60 requests at least 1 s
apart. CarMax can change any of this without notice; the API is undocumented. Builds
on `prototypes/carmax_probe.py` (branch `prototype/carmax`) and the decisions on #41
(from #42: local personal use only, `shipping=0`, fixed 50 miles, at most 10 pages,
one warm-up request, no retry after a 403).

## The endpoint

`GET https://www.carmax.com/cars/api/search/run`

| Parameter | Notes |
| --- | --- |
| `uri` | the search page path, `/cars/<make>/<model>`, `/cars/<make>` or `/cars`. **Keep the slashes raw** (`urlencode(params, safe="/")`); `%2F` happened to work in one probe on 2026-10-02 but the prototype saw a 403, so do not rely on it |
| `zipCode` | a US zip. A malformed or unknown zip (`abc`, `00000`) is **200**, silently replaced by some other location (`00000` became 66204, Kansas), so validate zips ourselves |
| `radius` | `radius-<miles>`. The response always echoes `"radius": "radius-nationwide"` and `radiusChanged: false`, whatever was sent, so the echo tells nothing. Each item's `distance` (miles to its store) is the check: at 94103 with `radius-50` the farthest was 44.1 |
| `shipping` | `0` keeps cars at stores in range with no transfer; `-1` (the search page default) adds cars that need a paid transfer (63 vs 52 Civics at 94103). `shipping=0` combined with `radius-nationwide` returned only 2 Civics at 94103, so it is not a "show everything" setting |
| `skip`, `take` | offset paging, see below |
| `sort` | `price-asc` works; the page lists `bestmatch`, `distance-asc`, `price-desc`, `mileage-asc`, `mileage-desc`, `year-desc`, `year-asc`, `newarrival`. An unknown value is silently ignored (200) |

The same route with a `skip` below 0 is **500** (`application/problem+json`, no detail).

Observed distances can exceed the radius at remote zips: zip 99950 (Ketchikan, AK) with `radius-50` and with `radius-5` both returned Civics up to 190.4 miles away. Cities in `cities.csv` are not remote, but a source can drop any item whose `distance` is over the radius if that matters.

### Akamai Bot Manager

`www.carmax.com` sits behind Akamai. All of this is needed:

- **HTTP/2.** `httpx` over HTTP/1.1 is 403 on every request, with browser headers, a Referer and cookies all set. `httpx.Client(http2=True)` needs the `h2` package.
- **Browser-like headers**: a Firefox/Chrome `User-Agent`, `Accept`, `Accept-Language`, `Sec-Fetch-Dest: empty`, `Sec-Fetch-Mode: cors`, `Sec-Fetch-Site: same-origin`. The prototype also sends `Referer: https://www.carmax.com/cars/<make>/<model>`. In this session HTTP/2 requests with the same headers and **no** Referer also reached 200, so the Referer looks optional, but it costs nothing; keep it.
- **A warm-up request on the same client.** The first request on a fresh client is usually 403 and sets `akBMG`, `bm_s` and `bm_so` cookies; later requests on the same client (same cookie jar) are 200. A warm-up GET of the search page (`/cars/<make>/<model>`) returned 403 once and 200 another time, but either way the cookies were set and the next call was 200. The 403 is not retried (#42 decision), so a Search that gets a 403 after the warm-up becomes a `ListingSourceError`.

What a 403 looks like: status 403, `text/html`, a 402-byte body:

```
<HTML><HEAD>
<TITLE>Access Denied</TITLE>
</HEAD><BODY>
<H1>Access Denied</H1>
You don't have permission to access "http://www.carmax.com/cars/api/search/run?" on this server.<P>
Reference #18.971ca17.1790983301.32cd578c
...
```

A bad `take` gives a different failure: `take=101` is **400** with a ~10 KB HTML page (not JSON). Both mean "not JSON", so check the status before calling `.json()`.

## Paging

- `take` is capped at **100**; `take=101` is 400 as above. `take=0` is 200 but returns a short first page (48 items), so never send it.
- `skip` pages with no cap seen (the prototype fetched 14 pages, 1354 nationwide Civics). `skip` past the end is 200 with an empty `items` list.
- **`totalCount` is unreliable.** `/cars/honda` at 94103 reported 196 on the `skip=0` page and 239 on `skip=100` and `skip=200`, then 238 on `skip=300`; the pages held 100 + 100 + 39 = 239 distinct `stockNumber`s. So page until a **short page** (fewer than `take` items), like Craigslist, and treat the total as a hint.
- Items were unique across pages (no repeats, unlike Craigslist's `batch`), but dedupe by `stockNumber` anyway.
- #42 caps a Search at 10 pages (1000 Listings); a sorted `price-asc` search is stable between pages.

## Response layout

A big object (500 to 700 KB at `take=100`; most of it is `filterCategories`). Fields the app uses:

| Field | Notes |
| --- | --- |
| `items` | the Listings, see below |
| `totalCount` | see Paging; `0` when empty |
| `take` | echoes the request |
| `searchFailed`, `hasSearchError` | `false` in every search seen, including empty ones and unknown slugs |
| `selectedFacets` | what the server understood from `uri`, see Make and model slugs |
| `filterCategories` | list of facet groups; the group named `Make` holds the valid makes and models |
| `expandedSearches` | empty list, or suggestions such as `"Adjust to 250 miles"` when a search is empty |

The rest (`seo`, `location`, `popularCars`, `transferEtas`, `testsGroups`, ...) is page-building cruft.

### A search with no results

`totalCount: 0`, `items: []`, every other key present, `searchFailed: false`. Seen for a valid model with no stock in range (`/cars/honda/prelude`, `/cars/honda/clarity`, `/cars/porsche/911` at some zips). Unlike Carfax, no key goes missing. `expandedSearches` may hold radius suggestions (Clarity did); ignore them.

### Make and model slugs

The slug is the lowercase facet name with spaces turned into hyphens. It is **CarMax's own spelling** and differs from Craigslist's and Carfax's.

**An unknown slug is not an error.** The API drops what it does not recognise and answers 200 with a broader search:

| `uri` (zip 94103, `radius-50`) | Result |
| --- | --- |
| `/cars/honda/civic` | 52 items, `selectedFacets`: make `honda`, model `civic` |
| `/cars/honda/zzz` | **196 items: every Honda**; `selectedFacets` has only make `honda` |
| `/cars/zzz/civic` | 52 items: the model `civic` of any make, `selectedFacets` has only model `civic` |
| `/cars/zzz` | 1434 items: all cars |
| `/cars/ford/f150` | 11 items; `selectedFacets`: make `ford`, model `f150` |
| `/cars/ford/f-150` | **75 items: every Ford**; the hyphenated Craigslist/Carfax spelling is unknown here and ignored |
| `/cars/honda/cr-v` | 33 items (models `CR-V` and `CR-V Hybrid`) |
| `/cars/ford/prelude` | 0 items: `prelude` is a known model, just not Ford's, so the filter applies and nothing matches |

So a wrong slug quietly returns the whole make, which would put hundreds of unrelated Listings on the chart. **Check `selectedFacets` in the response**: it must contain an entry with `category` `model` (or `series`, below) whose `value` equals the slug requested, or the model was ignored and the source should treat the search as failed or skipped with a logged warning, like a model with no Carfax name. The make is checked the same way (`category` `make`).

Where the other spellings land:

| App model (CSV) | CarMax slug | Notes |
| --- | --- | --- |
| Honda CR-V | `cr-v` | |
| Ford F150 | `f150` | no hyphen, unlike Carfax's `F-150`; `f250`, `f350` the same; the CSV's F450 has no CarMax model |
| Mercedes-Benz make | `mercedes-benz` | hyphen kept |
| Land Rover make | `land-rover` | |
| Land Rover Range Rover | `range-rover` | also matches `Range Rover PH` |
| Mercedes-Benz C-Class / E-Class | `c-class`, `e-class` | a **series**, not a model (below) |
| Mercedes-Benz GLC, GLE, ... | none | `/cars/mercedes-benz/glc` is ignored and returns all 2814 Mercedes. CarMax models are `glc300`, `gle350`, ... so no single slug covers the family |
| BMW 3 Series | `3-series` | a series; the models are `330`, `328`, ... |

**Series.** For some families `selectedFacets` reports `category: "series"` instead of `"model"` (seen: `c-class`, `e-class`, `3-series`) and matches every model in that family (`/cars/mercedes-benz/e-class`: E300, E350, E400, E43 AMG...). Series slugs are accepted but **not listed** in the facet list, so there is no way to enumerate them; the models are listed instead.

### A facet list of valid models exists

Every response's `filterCategories` has an entry with `name: "Make"` whose `data` is a list of `{value, urlSegment, count, children}`; each make's `children` is its models as `{value, urlSegment, count}`. `urlSegment` is exactly the slug to use in `uri` (for example `{"value": "CR-V", "urlSegment": "cr-v"}`, `{"value": "F150", "urlSegment": "f150"}`). It was 36 makes at 94103.

- The list is **scoped to the current search**: counts are for the search, and makes and models with no stock in range are dropped (Honda at 94103 radius-50 lacked, for example, Ford's `c-max-energi` which a wider search listed). For a list to check the lookup CSV against, take it from an unfiltered, wide search (`/cars`, `radius-nationwide`, `shipping=-1`) or union several.
- The facet lists models only, not series (see above), so a series slug such as `c-class` cannot be checked against it; check it with a live search and `selectedFacets`.
- Model names are CarMax's trim-level names for some makes (Mercedes: `c300`, `gle350`; BMW: `328`, `330`), so a lookup column cannot be derived from Craigslist's names automatically for those.

## Listing fields

One Honda Civic item (about 100 fields; the rest is financing, transfer ETAs, badges, features and engine specs):

| App field | CarMax field | Notes |
| --- | --- | --- |
| id | `stockNumber` | int, unique; the Listing id would be `carmax:<stockNumber>` |
| vin | `vin` | |
| year/make/model/trim | `year`, `make`, `model`, `trim` | `trim` was `null` on 1 of 100 |
| mileage | `mileage` | int; present on all 239 Hondas seen |
| price | `basePrice` | float (`15998.0`); present on all 239. `originalPrice` is the pre-drop price, `null` unless `hasPriceDrop` is true (18 of 100) |
| dealer | `storeName`, `storeCity`, `stateAbbreviation` | always present; `state` is the full state name |
| distance | `distance` | miles to the store |
| on sale | `lastMadeSaleableDate` | ISO 8601 UTC string (`2026-10-02T19:58:32.415Z`); **`null` on 2 of 239**, so it can be missing |
| price dropped | `hasPriceDrop` | bool |
| one owner | `highlights` | list of strings; `"singleOwner"` present on 54 of 100. Others seen: `fuelEfficient`, `lowMilesPerYear`, `advancedFeatures`, `warranty`, `lowMiles`, `premiumAudio` |
| image | `heroImageUrl` | see Photos |
| link | none | build `https://www.carmax.com/car/<stockNumber>` |

Keys that are `null` on every item seen (ignore): `repairPalData`, `normalizedExteriorColor`, `normalizedInteriorColor`, `review`, `fuelType`, `series`, `heroThumbnailImageUrl`, `savedCount`. There is no accident field, no owner count and no first-seen date (hence the #42 Preview choices). Every item seen had `isSaleable: true` and `isComingSoon: false`.

`robots.txt` allows `/cars/` and `/cars/api/` and disallows `/car/*` (the detail page): link to it, never fetch it.

## Photos

Each item has exactly one photo URL: `heroImageUrl`, such as `https://img2.carmax.com/assets/70175009/hero.jpg?width=400`. It was present on every item. There is no photo list in the search result.

Hotlinking works from another origin, with no Referer, no cookies and no User-Agent:

- `curl` with no headers, and with `Origin`/`Referer: http://127.0.0.1:8080`, both got **200 `image/jpeg`** with `access-control-allow-origin: *` and `timing-allow-origin: *`. The image host is Akamai Image Manager (`img2.carmax.com`), separate from the bot-protected `www.carmax.com`.
- `?width=400` returns a 400x400 progressive JPEG (about 21 KB). The same path without `width` is the original (2602x2602, about 240 KB), so keep `width` for Preview.
- Building the other photos from the stock number: `https://img2.carmax.com/assets/<stockNumber>/image/1.jpg` is a 200 full-size photo. `.../image/1/medium.jpg` is a 302 to `https://img2.carmax.com/Images/fallback.jpg`, so it is not a valid pattern. The numbering of photos past 1 was not probed.
- `cache-control: private, no-transform, max-age=86400`.

So #42's "hotlink if possible" is satisfied. Some photos are owned by EVOX Productions (terms of use); hotlink, never store.

## Fixtures

Saved in `tests/fixtures/`, refreshable with `uv run python tests/fixtures/refresh.py` (which needs the `h2` package and sends one warm-up request and then one request a second):

- `carmax_page_1.json`: Honda Civic, zip 94103, `radius-50`, `shipping=0`, `take=20` (51 results that day) - first page, full. One listing has its price and mileage removed, to give the tests a listing with neither (not seen missing live).
- `carmax_page_2.json`: same search, `skip=20` - a later full page.
- `carmax_last_page.json`: same search, `skip=40` - the last, short page (11 items).
- `carmax_empty.json`: Honda Prelude, same zip and radius - `totalCount` 0 and `items` empty.

- `carmax_unknown_model.json`: `/cars/honda/zzznotreal` - the unknown slug is ignored, so it holds Honda Listings and a `selectedFacets` with only make `honda`.

Each keeps `totalCount`, `take`, `searchFailed`, `hasSearchError`, `selectedFacets` cut to `category` and `value` (the check for an ignored slug) and, per item, only the fields in the table above (`CARMAX_LISTING_FIELDS` in `refresh.py`).
