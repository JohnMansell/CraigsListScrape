import argparse

from loguru import logger

from craigslist.log import LOG_LEVELS, configure_logging


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="craigslist", description="Craigslist price vs. mileage app")
    parser.add_argument("--log", dest="log_level", default="INFO", choices=LOG_LEVELS, help="logging level")
    args = parser.parse_args(argv)

    log_file = configure_logging(args.log_level)
    logger.debug("Logging to {}", log_file)
    logger.info("Nothing to run yet: the rebuild has no commands so far")


if __name__ == "__main__":
    main()
