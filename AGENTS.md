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
- `page.py`: the NiceGUI Search page. `SearchForm` holds the toolbar values (Owner, Dealer and an independent Carfax checkbox, each ticked by default) and the Search-enabled rules; `SearchForm.from_query`/`to_query` map the URL to the controls. `search_page` builds one page per browser tab and runs `search.run_live_search` in `run.io_bound`, polling a queue every 0.25 s to draw each batch. All Search state lives inside `search_page`: the page serves several people from one process, so nothing may be module-level. `serve` binds 127.0.0.1:8080, light or dark following the browser.
- `chart.py`: ECharts option dicts from a `SearchResult`, plus the empty-chart message and status line. Default axes fit the kept points (`PriceCurve.min_miles`..`max_price`), padded 5%; outliers become edge arrows carrying `actual`. Drag-zoom uses the ECharts toolbox `dataZoom`, armed by `dispatchAction` after each update. `curve_notes` gives the too-few-points notes. No NiceGUI import, so it tests without a browser. Carfax is a third series (`CARFAX_NAME`/`CARFAX_COLOR`, hollow like Dealer) with its own Price curve; since a Carfax Listing also carries `OwnerType.DEALER`, every owner-type-keyed function filters on `listing.source` too, not owner type alone.
- `preview.py`: Preview panel content, built without NiceGUI, plus the no-mileage note and `load_details(listing, fetch)`. `page.py` wires chart hover, click and pin to it. For a Carfax Listing, `PreviewContent` carries dealer name, owners, accidents and a price-drop note straight from the Listing (`load_details` returns `{}` without fetching: `www.carfax.com` is DataDome-blocked and the Search result already has everything).
- `search.py`: `run_search(Search, fetch, on_batch, should_stop)` validates lookup values, reports each API page's Listings as it arrives, then returns Listings and a Price curve per owner type (`curve.py`). A failed request or a stop returns the Listings that arrived, with `error` or `cancelled` set, instead of raising. `run_live_search` does the same with its own `HttpFetcher` when no fetch is given.
- `listings.py`: Listing source. `search_listings(Search, fetch)` returns Listings (including `posted` and `location`, each `None` when unknown) from Craigslist's undocumented JSON search API (`sapi.craigslist.org`), one API search per owner type. `fetch(url) -> str` is passed in; `HttpFetcher` is the live one (User-Agent, 0.5 s pacing). Every Craigslist URL and response-layout guess lives here. Findings behind it: `docs/research/craigslist-search.md`. `Listing.id` is a string unique across Sources (`"craigslist:<post id>"` here); `Listing.source` is the `Source` enum (`CRAIGSLIST` or `CARFAX`) shared with the Carfax source; `Listing.images` holds full, hotlinkable photo URLs rather than Craigslist's image codes.
- `carfax.py`: Carfax Listing source. `search_carfax(Search, fetch)` returns Listings (`OwnerType.DEALER` only) from Carfax's undocumented helix JSON search API (`helix.carfax.com`), searched by `City.zip` and a fixed 50-mile radius. Findings behind it: `docs/research/carfax-search.md`. A make/model with no Carfax name (`lookup.carfax_model`) is skipped with a logged warning. A search over Carfax's 1250-listing page cap (`PAGE_SIZE * MAX_PAGE`) is split into `priceMin`/`priceMax` bands, deduplicated by id. **Carfax's terms of use limit this to personal, non-commercial use** (the #25 decisions on issue #24) — never point this source at a server shown to other people; that separation is a later ticket.
- `log.py`: `configure_logging` sets up loguru: stderr plus `craigslist.log`, rotated at midnight with 10 files kept, in `logs/` or `$CRAIGSLIST_LOGDIR`. Calling it again replaces the handlers.
- `lookup.py`: `states`, `cities(state)` (each a `City` with name, Craigslist base URL, and a zip near its centre for Carfax's zip + radius search), `makes`, `models(make)`, `carfax_model(make, model)`. Reads `data/cities.csv` and `data/makes_models.csv`; edit the CSVs to add a city or model. State and make lookups ignore case. `makes_models.csv`'s `carfax_model` column is Carfax's own spelling for that make/model (for example `Ford,F150,F-150`), checked against `facetCountMap` in a live response; blank when Carfax doesn't carry that model under any name Craigslist's model matches (a genuinely ambiguous stem like Audi's `RS` or Porsche's `718`, or a sub-brand prefix like `Mercedes-AMG`) — `carfax_model` returns `None` for those, and the Carfax source skips the model with a logged warning rather than guessing.

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
