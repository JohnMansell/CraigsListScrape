import argparse

from loguru import logger

from craigslist.curve import NotEnoughData, PriceCurve
from craigslist.listings import Fetch, HttpFetcher, OwnerType
from craigslist.log import LOG_LEVELS, configure_logging
from craigslist.search import Search, SearchError, SearchResult, run_search


def main(argv: list[str] | None = None, fetch: Fetch | None = None) -> None:
    """`fetch` replaces the live HTTP fetcher, for tests."""
    parser = argparse.ArgumentParser(prog="craigslist", description="Craigslist price vs. mileage app")
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
    args = parser.parse_args(argv)

    log_file = configure_logging(args.log_level)
    logger.debug("Logging to {}", log_file)
    if args.command == "listings":
        owner_types = (OwnerType(args.owner_type),) if args.owner_type else tuple(OwnerType)
        try:
            print_listings(Search(args.state, args.city, args.make, args.model, owner_types), fetch)
        except SearchError as error:
            parser.error(str(error))
    else:
        logger.info("Nothing to run: pass a command, such as `listings`")


def print_listings(search: Search, fetch: Fetch | None) -> None:
    http = None
    if fetch is None:
        fetch = http = HttpFetcher()
    try:
        results = run_search(search, fetch)
    finally:
        if http:
            http.close()
    for listing in results.listings:
        mileage = "?" if listing.mileage is None else f"{listing.mileage:,}"
        print(f"{listing.owner_type:<6} {listing.post_id} ${listing.price:>7,} {mileage:>9} mi  {listing.title}")
    for owner_type, total in results.reported_totals.items():
        count = sum(listing.owner_type == owner_type for listing in results.listings)
        print(_summary(owner_type, count, total, results))


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
