# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Dash web app that scrapes Craigslist car listings with headless Chrome (Selenium) and plots price vs. mileage, with an exponential-decay fit line per owner type. Hovering a point shows listing details and the thumbnail; clicking opens the listing.

## Commands

uv-managed, Python 3.14 (`.python-version`). Not a package: there is no build system, and `__init__.py` is run as a script.

```
uv sync                         # create .venv from uv.lock
uv run __init__.py              # Dash dev server (debug=True), http://127.0.0.1:8050
uv run __init__.py --log DEBUG
uv add <pkg>                    # add a dependency (updates pyproject.toml and uv.lock)
```

- Run from the repo root. Image downloads use the relative path `assets/car_images/`.
- No Chrome install needed. Selenium Manager downloads Chrome for Testing and chromedriver into `~/.cache/selenium` on first launch.
- No tests or lint config exist.
- `scratch.py` and `scratch2.py` are old experiments. They import `webdriver_manager` and `bs4`, which are not dependencies.

## Architecture

Import chain: `__init__.py` -> `layout_objects.py` -> `backend.py` -> `web_interface.py`. Every module imports `color_logging`.

- `__init__.py`: the Dash app, page layout, and all callbacks. The main `on_click` callback calls `Backend.get_all_cars`, builds a `px.scatter`, then `Backend.solve_curves` adds `curve_fit` lines. The click-to-open-listing callback is clientside JS writing to a hidden `H1`.
- `layout_objects.py`: component definitions, populated at import time from `Backend` (states, cities for `'CA'`, makes). It creates its own throwaway `dash.Dash` just to call `get_asset_url`.
- `backend.py`: `Backend` loads pickled lookup tables from `resources/` and turns Selenium elements into `car_object` instances, returned as a DataFrame (columns = `car_object` attributes).
- `web_interface.py`: `Web_Interface` owns the Chrome driver and all Craigslist HTML selectors (see Gotchas).

### Data files in `resources/`

- `df_cities.p`: DataFrame with `state`, `city`, `href` (the city's Craigslist base URL).
- `df_make_model.p`: DataFrame with `make`, `model`.
- `p_car_objects.p`: dict of posting id (numeric `data-pid` string) -> `backend.car_object`. It is a scrape cache: rewritten after every new car, and hits skip the detail-page fetch. Renaming or moving `car_object` breaks unpickling.

## Gotchas

- Craigslist selectors, current as of 2026-09:
  - Each listing is a `gallery-card`, with the title and link in `a.posting-title` and the price in `priceinfo`.
  - The posting id is `data-pid` on the card's parent `div.cl-search-result`. Listing URLs no longer contain it.
  - Detail pages list `key: value` lines in `attrgroup`. The odometer has thousands separators and can be empty.
  - When scraping breaks, check these first. `get_car_objects` logs each failure and silently drops the car.
- `on_click` crashes with `KeyError: 'miles'` when a search yields zero cars (empty DataFrame).
- `color_logging.py` runs `argparse` on `sys.argv` at import time. Any importer (pytest, gunicorn, a REPL with extra args) fails on unrecognized arguments.
- Logs go to `logs/` in the repo (override with `CRAIGSLIST_LOGDIR`), created at import time.
- `Backend()` launches Chrome in its constructor and never quits it. Both `layout_objects.py` and `__init__.py` create a `Backend`, so two browsers start. The Flask dev reloader (`debug=True`) can start more. chromedriver and Chrome can outlive a killed Python process, so check with `pgrep -fa selenium/chrom`.
- Star imports carry names across modules: `os` reaches `backend.py`/`web_interface.py` through `from color_logging import *`, and `dash`/`dcc`/`html`/`dbc` reach `__init__.py` through `from layout_objects import *`. Removing an import from those modules breaks the others.
- `get_all_cars` only scrapes `'owner'` listings. The dealer color and fit paths exist but get no data. `build_url` computes `owner` (`cto`/`ctd`) and never uses it.
- Cars whose image resolves to `placeholder.png` are dropped entirely, not just left uncached.
- `on_click` silently falls back to CA / Orange County / honda / civic when any dropdown is empty.
- The graph callback reads `customdata` by position: `[url, image, attributes]`. Keep `custom_data=` in `on_click` in sync with `display_hover_data` and the clientside callback.

## Agent skills

### Issue tracker

GitHub Issues on `JohnMansell/CraigsListScrape`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one root `CONTEXT.md` plus `docs/adr/`, created on demand. See `docs/agents/domain.md`.
