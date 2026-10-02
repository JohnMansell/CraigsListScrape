import argparse
import sys

from loguru import logger

from craigslist import lookup
from craigslist.carfax import HttpFetcher as CarfaxHttpFetcher, Search as CarfaxSearch, search_carfax
from craigslist.chart import failure_banner
from craigslist.curve import NotEnoughData, PriceCurve
from craigslist.listings import Fetch, OwnerType
from craigslist.log import LOG_LEVELS, configure_logging
from craigslist.search import Search, SearchError, SearchResult, run_live_search


def main(argv: list[str] | None = None, fetch: Fetch | None = None) -> None:
    """`fetch` replaces the live HTTP fetcher, for tests."""
    parser = argparse.ArgumentParser(
        prog="craigslist", description="Craigslist price vs. mileage app. With no command, serves the Search page."
    )
    parser.add_argument("--log", dest="log_level", default="INFO", choices=LOG_LEVELS, help="logging level")
    commands = parser.add_subparsers(dest="command")
    listings_parser = commands.add_parser("listings", help="print the Listings for a live Search")
    listings_parser.add_argument("--state", required=True)
    listings_parser.add_argument("--city", required=True)
    listings_parser.add_argument("--make", required=True, help="for example honda")
    listings_parser.add_argument("--model", required=True, help="for example civic")
    listings_parser.add_argument(
        "--owner-type", choices=[owner_type.value for owner_type in OwnerType], help="omit for both"
    )
    carfax_parser = commands.add_parser("carfax", help="print the Carfax Listings for a live Search")
    carfax_parser.add_argument("--state", required=True)
    carfax_parser.add_argument("--city", required=True)
    carfax_parser.add_argument("--make", required=True, help="for example honda")
    carfax_parser.add_argument("--model", required=True, help="for example civic")
    args = parser.parse_args(argv)

    log_file = configure_logging(args.log_level)
    logger.debug("Logging to {}", log_file)
    if args.command == "listings":
        owner_types = (OwnerType(args.owner_type),) if args.owner_type else tuple(OwnerType)
        try:
            print_listings(Search(args.state, args.city, args.make, args.model, owner_types, sources=()), fetch)
        except SearchError as error:
            parser.error(str(error))
    elif args.command == "carfax":
        try:
            print_carfax_listings(_carfax_search(args.state, args.city, args.make, args.model), fetch)
        except SearchError as error:
            parser.error(str(error))
    else:
        # Imported here so the `listings` command does not load NiceGUI.
        from craigslist import page

        page.serve()


def _carfax_search(state: str, city: str, make: str, model: str) -> CarfaxSearch:
    if not any(known.casefold() == state.casefold() for known in lookup.states()):
        raise SearchError(f"unknown state {state!r}")
    found_city = next((c for c in lookup.cities(state) if c.name.casefold() == city.casefold()), None)
    if found_city is None:
        raise SearchError(f"unknown city {city!r} in state {state!r}")
    if not any(known.casefold() == make.casefold() for known in lookup.makes()):
        raise SearchError(f"unknown make {make!r}")
    if not any(known.casefold() == model.casefold() for known in lookup.models(make)):
        raise SearchError(f"unknown model {model!r} for make {make!r}")
    return CarfaxSearch(found_city, make, model)


def print_carfax_listings(search: CarfaxSearch, fetch: Fetch | None) -> None:
    if fetch is not None:
        results = search_carfax(search, fetch)
    else:
        http = CarfaxHttpFetcher()
        try:
            results = search_carfax(search, http)
        finally:
            http.close()
    for listing in results.listings:
        mileage = "?" if listing.mileage is None else f"{listing.mileage:,}"
        print(f"{listing.owner_type:<6} {listing.id} ${listing.price:>7,} {mileage:>9} mi  {listing.title}")
    print(f"carfax: {len(results.listings)} Listings, API reported total {results.reported_total}")
    if results.error is not None:
        print(f"carfax: {results.error}", file=sys.stderr)


def print_listings(search: Search, fetch: Fetch | None) -> None:
    results = run_live_search(search, fetch)
    for listing in results.listings:
        mileage = "?" if listing.mileage is None else f"{listing.mileage:,}"
        print(f"{listing.owner_type:<6} {listing.id} ${listing.price:>7,} {mileage:>9} mi  {listing.title}")
    for owner_type, total in results.reported_totals.items():
        count = sum(listing.owner_type == owner_type for listing in results.listings)
        print(_summary(owner_type, count, total, results))
    if banner := failure_banner(results):
        print(banner, file=sys.stderr)


def _summary(owner_type: OwnerType, count: int, total: int, results: SearchResult) -> str:
    curve = results.curves[owner_type]
    if isinstance(curve, PriceCurve):
        return (
            f"{owner_type}: {count} Listings, API reported total {total}; "
            f"curve coefficients a={curve.amplitude:.2f} b={curve.rate:.8f} c={curve.floor:.2f}"
        )
    assert isinstance(curve, NotEnoughData)
    return f"{owner_type}: {count} Listings, API reported total {total}; not enough data: {curve.reason}"


if __name__ == "__main__":
    main()
