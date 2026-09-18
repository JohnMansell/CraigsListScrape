import ast
from pathlib import Path

from craigslist import lookup
from craigslist.lookup import City


def test_cities_for_CA_include_orange_county_with_its_base_url():
    assert City("Orange County", "https://orangecounty.craigslist.org") in lookup.cities("CA")


def test_cities_only_come_from_the_given_state():
    names = [city.name for city in lookup.cities("NY")]

    assert "Albany" in names
    assert "Orange County" not in names


def test_states_are_unique_and_sorted():
    states = lookup.states()

    assert "CA" in states
    assert states == sorted(set(states))


def test_models_for_honda_include_civic():
    assert "Civic" in lookup.models("honda")


def test_make_lookup_ignores_case():
    assert lookup.models("HONDA") == lookup.models("Honda")


def test_makes_are_unique_and_sorted():
    makes = lookup.makes()

    assert "Honda" in makes
    assert makes == sorted(set(makes))


def test_unknown_make_or_state_gives_an_empty_list():
    assert lookup.models("no such make") == []
    assert lookup.cities("ZZ") == []


def test_loader_does_not_use_pandas():
    tree = ast.parse(Path(lookup.__file__).read_text())
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}

    assert not any(name.split(".")[0] == "pandas" for name in imported)
