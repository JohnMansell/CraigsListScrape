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


@cache
def _read_csv(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(newline="") as file:
        return tuple(csv.DictReader(file))


def states() -> list[str]:
    return sorted({row["state"] for row in _read_csv(CITIES_CSV)})


def cities(state: str) -> list[City]:
    """Cities in `state`, in file order."""
    return [
        City(row["city"], row["url"]) for row in _read_csv(CITIES_CSV) if row["state"].casefold() == state.casefold()
    ]


def makes() -> list[str]:
    return sorted({row["make"] for row in _read_csv(MAKES_MODELS_CSV)})


def models(make: str) -> list[str]:
    """Models of `make`, in file order."""
    return [row["model"] for row in _read_csv(MAKES_MODELS_CSV) if row["make"].casefold() == make.casefold()]
