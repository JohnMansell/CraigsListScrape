"""States, cities, makes, and models, read from the CSV files in data/.

Add a city or a car model by editing the CSV. Lookups by state or make ignore case.
"""
import csv
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
CITIES_CSV = DATA_DIR / "cities.csv"
MAKES_MODELS_CSV = DATA_DIR / "makes_models.csv"


@dataclass(frozen=True)
class City:
    name: str
    url: str
    """The city's Craigslist base URL, such as https://orangecounty.craigslist.org"""
    zip: str = ""
    """A zip near the city's centre, for Carfax's zip + radius search. Some Craigslist
    areas are regions ("Akron / Canton", "Inland Empire"); their zip is the largest
    city in the region, not necessarily the one named first."""


@cache
def _read_csv(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(newline="") as file:
        return tuple(csv.DictReader(file))


def states() -> list[str]:
    return sorted({row["state"] for row in _read_csv(CITIES_CSV)})


def cities(state: str) -> list[City]:
    """Cities in `state`, in file order."""
    return [
        City(row["city"], row["url"], row["zip"])
        for row in _read_csv(CITIES_CSV)
        if row["state"].casefold() == state.casefold()
    ]


def makes() -> list[str]:
    return sorted({row["make"] for row in _read_csv(MAKES_MODELS_CSV)})


def models(make: str) -> list[str]:
    """Models of `make`, in file order."""
    return [row["model"] for row in _read_csv(MAKES_MODELS_CSV) if row["make"].casefold() == make.casefold()]


def carfax_model(make: str, model: str) -> str | None:
    """Carfax's name for `make`/`model`, or None when Carfax doesn't carry it (or
    the pair isn't in the CSV at all)."""
    for row in _read_csv(MAKES_MODELS_CSV):
        if row["make"].casefold() == make.casefold() and row["model"].casefold() == model.casefold():
            return row["carfax_model"] or None
    return None


def carmax_make(make: str) -> str:
    """CarMax's slug for `make`: lowercase with spaces as hyphens ("Land Rover" is
    `land-rover`). Not checked against CarMax's makes: use it only with a `carmax_model`
    that is not None, because CarMax silently ignores a slug it doesn't know."""
    return make.casefold().replace(" ", "-")


def carmax_model(make: str, model: str) -> str | None:
    """CarMax's slug for `make`/`model`, for `uri=/cars/<carmax_make>/<slug>`, or None when
    CarMax has no single slug for it (or the pair isn't in the CSV at all).

    The slug is CarMax's own spelling (`f150`, `cr-v`) and may be a series (`3-series`,
    `c-class`). It must be exact, since an unknown slug returns the whole make."""
    for row in _read_csv(MAKES_MODELS_CSV):
        if row["make"].casefold() == make.casefold() and row["model"].casefold() == model.casefold():
            return row["carmax_model"] or None
    return None
