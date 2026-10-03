# AGENTS.md

## What this is

A NiceGUI web app that searches Craigslist car listings and plots price vs. mileage in ECharts, with an exponential-decay Price curve per owner type (owner filled, dealer hollow). Hovering a point shows the listing in the Preview panel; clicking pins it. Stack: NiceGUI + ECharts, httpx + selectolax, scipy, loguru. The code is the `craigslist/` package.

## Commands

uv-managed, Python 3.14 (`.python-version`). Not an installable package: there is no build system. The app runs as `python -m craigslist` from the repo root.

```
uv sync                                  # create .venv from uv.lock
uv run python -m craigslist              # Search page, http://127.0.0.1:8080
uv run python -m craigslist --log DEBUG
uv run python -m craigslist listings --make honda --model civic   # live Search, prints Listings
uv run python -m craigslist carfax --make honda --model civic      # live Carfax Search, prints Listings
uv run python -m craigslist carmax --state CA --city "sf bay area" --make honda --model civic   # live CarMax Search, prints Listings
uv run python tests/fixtures/refresh.py  # re-fetch the saved API responses (hits Craigslist)
uv run pytest                            # all tests
uv run pytest tests/test_log.py          # one test file
uv run --with mypy mypy craigslist tests
uv add <pkg>                             # add a dependency (updates pyproject.toml and uv.lock)
```

- Run from the repo root.
- No test may touch the network (`tests/conftest.py` makes connecting fail). The Listing source tests use saved API responses in `tests/fixtures/`, trimmed to 20 results; the tests shrink the page sizes to 20 so those fixtures page like a large search. There is no lint config, and mypy is not a dependency.
- New code must not use star imports or do work at import time. Tests check for star imports, and that importing every module with stray command-line flags succeeds and creates no files or directories.

## Architecture

- `__main__.py`: entry point. Parses `--log`, calls `configure_logging`, and runs the `listings` or `carfax` command, or with no command serves the Search page.
- `page.py`: the NiceGUI Search page. `SearchForm` holds the toolbar values (Owner, Dealer, and one checkbox per `sources.SOURCES` entry in `sources`, each ticked by default) and the Search-enabled rules; `SearchForm.from_query`/`to_query` map the URL to the controls. `search_page` builds one page per browser tab and runs `search.run_live_search` in `run.io_bound`, polling a queue every 0.25 s to draw each batch. All Search state lives inside `search_page`: the page serves several people from one process, so nothing may be module-level. `serve` binds 127.0.0.1:8080, light or dark following the browser.
- `chart.py`: ECharts option dicts from a `SearchResult`, plus the empty-chart message and status line. Default axes fit the kept points (`PriceCurve.min_miles`..`max_price`), padded 5%; outliers become edge arrows carrying `actual`. Drag-zoom uses the ECharts toolbox `dataZoom`, armed by `dispatchAction` after each update. `curve_notes` gives the too-few-points notes. No NiceGUI import, so it tests without a browser. Each `SOURCES` entry gets its own series (name, colour and marker from the table, hollow like Dealer) and Price curve; since a Carfax Listing also carries `OwnerType.DEALER`, every owner-type-keyed function filters on `listing.source` too, not owner type alone.
- `filters.py`: the display filters, without NiceGUI. `Filters.passes(listing)` decides whether a point is drawn in full or faded to a small light-grey dot; each yes/no `Flag` has an `include_unknown` box (ticked by default) so a Source that doesn't report the attribute isn't faded. Filters only change drawing: `chart.py` fits curves and default axes to every Listing whatever the filters say, and `page.py` redraws from the loaded Listings without searching. `chart_options`, `plotted_listings` and `status_text` take the `Filters`; faded points come first in each series so the full points draw over them.
- `preview.py`: Preview panel content, built without NiceGUI, plus the no-mileage note and `load_details(listing, fetch)`. `page.py` wires chart hover, click and pin to it. For a Carfax Listing, `PreviewContent` carries dealer name, owners, accidents and a price-drop note straight from the Listing (`load_details` returns `{}` without fetching: `www.carfax.com` is DataDome-blocked and the Search result already has everything). A CarMax Listing shows its store name and city, an "On sale since" date (not "Posted"), "One owner" only when known, a price-drop note, no accidents line, and the hotlinked `heroImageUrl`; its link is "Open on CarMax" (`https://www.carmax.com/car/<stockNumber>`), and `load_details` returns `{}` for it too because CarMax's robots.txt disallows `/car/*`.
- `search.py`: `Search` has `owner_types` (Craigslist) and `sources` (a tuple of `Source`, the non-Craigslist sources); `SearchResult` keeps their curves, reported totals and errors in `source_curves`, `source_reported_totals` and `source_errors`, keyed by `Source`. `run_search(Search, fetch, on_batch, should_stop)` validates lookup values, runs Craigslist then each chosen source from the table, reports each API page's Listings as it arrives, then returns Listings and a Price curve per owner type and per source (`curve.py`). A failed request or a stop returns the Listings that arrived, with `error` or `cancelled` set, instead of raising. `run_live_search` does the same when no fetch is given, with Craigslist's `HttpFetcher` and each chosen source's own fetcher from the table.
- `sources.py`: `SOURCES`, the one table of non-Craigslist sources keyed by `Source`. A `SourceInfo` holds `name`, `color`, `marker`, `search` (a function `(city, make, model, fetch, on_batch, should_stop)` returning an object with `listings`, `reported_total`, `requests`, `error`, `cancelled`), `make_fetcher`, `query_key` (URL and remembered-Search key) and `default`. `search.py`, `chart.py` and `page.py` read it and name no source. **Adding a source** is a `Source` enum member, its search function, and one `SOURCES` entry (Carfax: green circle; CarMax: purple `#9467bd` diamond, wired through `_search_carmax`); legend, series, status count, failure text, checkbox and `query_key` link support follow.
- `listings.py`: Listing source. `search_listings(Search, fetch)` returns Listings (including `posted`, `location` and `year`, each `None` when unknown; `year` is read from the title by `model_year`) from Craigslist's undocumented JSON search API (`sapi.craigslist.org`), one API search per owner type. `fetch(url) -> str` is passed in; `HttpFetcher` is the live one (User-Agent, 0.5 s pacing). Every Craigslist URL and response-layout guess lives here. Findings behind it: `docs/research/craigslist-search.md`. `Listing.id` is a string unique across Sources (`"craigslist:<post id>"` here); `Listing.source` is the `Source` enum (`CRAIGSLIST` or `CARFAX`) shared with the Carfax source; `Listing.images` holds full, hotlinkable photo URLs rather than Craigslist's image codes.
- `carfax.py`: Carfax Listing source. `search_carfax(Search, fetch)` returns Listings (`OwnerType.DEALER` only) from Carfax's undocumented helix JSON search API (`helix.carfax.com`), searched by `City.zip` and a fixed 50-mile radius. Findings behind it: `docs/research/carfax-search.md`. A make/model with no Carfax name (`lookup.carfax_model`) is skipped with a logged warning. A search over Carfax's 1250-listing page cap (`PAGE_SIZE * MAX_PAGE`) is split into `priceMin`/`priceMax` bands, deduplicated by id. **Carfax's terms of use limit this to personal, non-commercial use** (the #25 decisions on issue #24) — never point this source at a server shown to other people; that separation is a later ticket.
- `carmax.py`: CarMax Listing source. `search_carmax(Search, fetch, on_batch, should_stop)` returns Listings (`OwnerType.DEALER` only, ids `carmax:<stockNumber>`) from the JSON API behind carmax.com's search page (`www.carmax.com/cars/api/search/run`), searched by `City.zip`, a fixed 50-mile radius and `shipping=0`, `take=100`, `sort=price-asc`. Findings behind it: `docs/research/carmax-search.md`. `HttpFetcher` is the live fetcher (HTTP/2 via `h2`, browser headers, Referer, one warm-up request, 1 s pacing, one per Search). A make/model with no CarMax slug (`lookup.carmax_model`) is skipped with a logged warning. **CarMax's terms of use ban scraping, even for personal use**; the #42 decisions on issue #41 accept that risk for local, personal use only. Never point this source at a server shown to other people.
- `log.py`: `configure_logging` sets up loguru: stderr plus `craigslist.log`, rotated at midnight with 10 files kept, in `logs/` or `$CRAIGSLIST_LOGDIR`. Calling it again replaces the handlers.
- `lookup.py`: `states`, `cities(state)` (each a `City` with name, Craigslist base URL, and a zip near its centre for Carfax's zip + radius search), `makes`, `models(make)`, `carfax_model(make, model)`, `carmax_make(make)`, `carmax_model(make, model)`. Reads `data/cities.csv` and `data/makes_models.csv`; edit the CSVs to add a city or model. State and make lookups ignore case. `makes_models.csv`'s `carfax_model` column is Carfax's own spelling for that make/model (for example `Ford,F150,F-150`), checked against `facetCountMap` in a live response; blank when Carfax doesn't carry that model under any name Craigslist's model matches (a genuinely ambiguous stem like Audi's `RS` or Porsche's `718`, or a sub-brand prefix like `Mercedes-AMG`) — `carfax_model` returns `None` for those, and the Carfax source skips the model with a logged warning rather than guessing. `makes_models.csv`'s `carmax_model` column is CarMax's exact URL slug (`f150`, `cr-v`, `3-series`; series are valid slugs too), checked against live responses (`docs/research/carmax-search.md`); CarMax silently ignores an unknown slug and returns the whole make, so it is blank when CarMax has no single slug (Mercedes `glc`/`gle`, which CarMax splits into `glc300`...) or doesn't carry the model or make. `carmax_model` returns `None` for those. `carmax_make` is just lowercase with hyphens.

## Gotchas

- Search API (`listings.py`), as of 2026-09:
  - `totalResultCount` counts local results only, so paging runs until a batch comes back short. Dealer searches return more results than the total, syndicated from other areas.
  - `batch` pages restart from result 0, repeating the 360 `full` results; Listings are deduplicated by post id.
  - Step 2 (`full?batch=0-<cacheTs>-0-1-0`) has no `cacheId` when there are too few results to page.
  - A search with no results has `"decode": 0` instead of an object.
  - Results with no price are skipped and logged. No mileage gives `None`; no photos gives no image codes.
- Carfax helix API (`carfax.py`), as of 2026-10:
  - A search with no results has no `totalListingCount`, `totalPageCount` or `listings` key at all, rather than zero or an empty list.
  - `rows` caps at 25 and `page` at 50, so one zip/radius/make/model/price-band search sees at most 1250 Listings; `page` past the last one is 200 with an empty list, not an error.
  - Make/model matching is exact on Carfax's own spelling, punctuation included (`F150` must be `F-150`); see `lookup.carfax_model`.
  - Results with no price are skipped and logged. No mileage gives `None`.
  - **Personal, non-commercial use only** per Carfax's terms of use (the #25 decisions on issue #24).
- CarMax search API (`carmax.py`), as of 2026-10:
  - Akamai Bot Manager 403s plain `httpx`. Needs HTTP/2, browser headers, a Referer, and cookies from one warm-up GET of the search page on the same client (the warm-up itself is often a 403 that still sets them). A 403 after the warm-up is **not retried**: it becomes a `ListingSourceError` in the status line. At least 1 s between requests; at most 10 pages (`MAX_PAGES`, 1000 Listings), then a logged warning and what was fetched.
  - `uri` keeps raw slashes (`urlencode(..., safe="/")`); `%2F` is blocked. `take` caps at 100 (101 is a 400).
  - **An unknown make or model slug is ignored with a 200** and returns the whole make or all cars. The first page's `selectedFacets` must hold the make and a `model` or `series` entry equal to the slug asked for; otherwise the search is skipped with a logged warning (no error, no Listings), not shown as a broad result.
  - `totalCount` drifts between pages, so paging runs until a short page. A search with no results has `items: []`, all keys present.
  - `basePrice` is a float; results with no price are skipped and logged. `lastMadeSaleableDate` can be `null` (`posted` is then `None`). `one_owner` is `True` or `None`, never `False`; `no_accidents` is always `None`.
  - Photos: `heroImageUrl` is hotlinkable (200, CORS `*`); never download or store it. The Listing link is `www.carmax.com/car/<stockNumber>`; robots.txt disallows `/car/*`, so link to it, never fetch it.
  - **Personal, local use only**; terms ban scraping (the #42 decisions on #41).
- Remembered Searches use `app.storage.user`, keyed by browser cookie. The signing secret is generated into the gitignored `.nicegui/storage_secret`. A URL naming any part of a Search wins over the browser's memory, and a complete link auto-runs; a plain reload restores the controls without searching.
- `logs/craigslist.log` is created only when the entry point configures logging.

## GitHub identity

- Account: personal (`JohnMansell`).
- Git remote: `github-personal`.

## Agent skills

### Issue tracker

GitHub Issues on `JohnMansell/CraigsListScrape`, via `gh-personal`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one root `CONTEXT.md` plus `docs/adr/`, created on demand. See `docs/agents/domain.md`.
