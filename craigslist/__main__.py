import argparse

from loguru import logger

from craigslist import lookup
from craigslist.listings import Fetch, HttpFetcher, OwnerType, Search, search_listings
from craigslist.log import LOG_LEVELS, configure_logging


def main(argv: list[str] | None = None, fetch: Fetch | None = None) -> None:
    """`fetch` replaces the live HTTP fetcher, for tests."""
    parser = argparse.ArgumentParser(prog="craigslist", description="Craigslist price vs. mileage app")
    parser.add_argument("--log", dest="log_level", default="INFO", choices=LOG_LEVELS, help="logging level")
    commands = parser.add_subparsers(dest="command")
    listings_parser = commands.add_parser("listings", help="print the Listings for a live Search")
    listings_parser.add_argument("--state", default="CA")
    listings_parser.add_argument("--city", default="Orange County")
    listings_parser.add_argument("--make", help="for example honda; omit for every make")
    listings_parser.add_argument("--model", help="for example civic; needs --make")
    listings_parser.add_argument(
        "--owner-type", choices=[owner_type.value for owner_type in OwnerType], help="omit for both"
    )
    args = parser.parse_args(argv)

    log_file = configure_logging(args.log_level)
    logger.debug("Logging to {}", log_file)
    if args.command == "listings":
        cities = {city.name.casefold(): city for city in lookup.cities(args.state)}
        city = cities.get(args.city.casefold())
        if city is None:
            parser.error(f"no city {args.city!r} in state {args.state!r}")
        if args.model and not args.make:
            parser.error("--model needs --make")
        owner_types = (OwnerType(args.owner_type),) if args.owner_type else tuple(OwnerType)
        print_listings(Search(city, args.make, args.model, owner_types), fetch)
    else:
        logger.info("Nothing to run: pass a command, such as `listings`")


def print_listings(search: Search, fetch: Fetch | None) -> None:
    http = None
    if fetch is None:
        fetch = http = HttpFetcher()
    try:
        results = search_listings(search, fetch)
    finally:
        if http:
            http.close()
    for listing in results.listings:
        mileage = "?" if listing.mileage is None else f"{listing.mileage:,}"
        print(f"{listing.owner_type:<6} {listing.post_id} ${listing.price:>7,} {mileage:>9} mi  {listing.title}")
    for owner_type, total in results.reported_totals.items():
        count = sum(listing.owner_type == owner_type for listing in results.listings)
        print(f"{owner_type}: {count} Listings, API reported total {total}")


if __name__ == "__main__":
    main()
