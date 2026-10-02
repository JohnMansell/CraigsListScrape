import ast
import re
from pathlib import Path

from craigslist import lookup
from craigslist.lookup import City


def test_cities_for_CA_include_orange_county_with_its_base_url():
    assert City("Orange County", "https://orangecounty.craigslist.org", "92702") in lookup.cities("CA")


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


def test_every_city_has_a_five_digit_zip():
    for state in lookup.states():
        for city in lookup.cities(state):
            assert re.fullmatch(r"\d{5}", city.zip), f"{state} {city.name!r} has no 5-digit zip: {city.zip!r}"


def test_known_cities_map_to_their_expected_zip():
    expected = {
        ("CA", "Orange County"): "92702",
        ("CA", "Sf Bay Area"): "94108",
        ("NY", "New York City"): "10001",
        ("IL", "Chicago"): "60604",
    }
    for (state, name), zip_code in expected.items():
        city = next(city for city in lookup.cities(state) if city.name == name)
        assert city.zip == zip_code


def test_carfax_model_matches_craigslists_name_for_most_models():
    assert lookup.carfax_model("Honda", "Civic") == "Civic"


def test_carfax_model_differs_for_a_name_carfax_spells_differently():
    assert lookup.carfax_model("Ford", "F150") == "F-150"


def test_carfax_model_is_none_for_a_model_carfax_does_not_carry():
    assert lookup.carfax_model("Porsche", "718") is None


def test_carfax_model_is_none_for_an_unknown_make_or_model():
    assert lookup.carfax_model("no such make", "Civic") is None
    assert lookup.carfax_model("Honda", "no such model") is None


def test_carfax_model_lookup_ignores_case():
    assert lookup.carfax_model("HONDA", "civic") == "Civic"


def test_loader_does_not_use_pandas():
    tree = ast.parse(Path(lookup.__file__).read_text())
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}

    assert not any(name.split(".")[0] == "pandas" for name in imported)
