import pytest

from craigslist.listings import OwnerType
from craigslist.page import SearchForm, has_search_params, storage_secret
from craigslist.search import Search


def complete_form() -> SearchForm:
    return SearchForm(state="CA", city="Orange County", make="Honda", model="Civic")


def test_a_complete_form_with_both_owner_types_can_search():
    form = complete_form()

    assert form.problem() is None
    assert form.search() == Search("CA", "Orange County", "Honda", "Civic", (OwnerType.OWNER, OwnerType.DEALER))


@pytest.mark.parametrize("field", ["state", "city", "make", "model"])
def test_search_is_blocked_until_every_dropdown_is_chosen(field):
    form = complete_form()
    setattr(form, field, None)

    assert form.problem() == "Pick a state, city, make, and model"


def test_search_is_blocked_with_owner_dealer_and_carfax_all_unchecked():
    form = complete_form()
    form.owner = form.dealer = form.carfax = False

    assert form.problem() == "Pick owner, dealer, or carfax"


def test_carfax_alone_is_enough_to_search():
    form = complete_form()
    form.owner = form.dealer = False

    assert form.problem() is None
    assert form.search() == Search("CA", "Orange County", "Honda", "Civic", (), True)


def test_one_owner_type_searches_only_that_type():
    form = complete_form()
    form.owner = False

    assert form.problem() is None
    assert form.search().owner_types == (OwnerType.DEALER,)


def test_choosing_a_state_lists_its_cities_and_clears_the_city():
    form = complete_form()

    form.choose_state("TX")

    assert form.city is None
    assert "Abilene" in form.city_options()
    assert "Orange County" not in form.city_options()


def test_choosing_a_make_lists_its_models_and_clears_the_model():
    form = complete_form()

    form.choose_make("Acura")

    assert form.model is None
    assert "ILX" in form.model_options()
    assert "Civic" not in form.model_options()


def test_no_state_or_make_means_no_city_or_model_options():
    form = SearchForm()

    assert form.city_options() == []
    assert form.model_options() == []


def test_a_link_with_a_full_search_fills_the_form_with_lookup_spelling():
    form = SearchForm.from_query({"state": "ca", "city": "orange county", "make": "HONDA", "model": "civic", "dealer": "0"})

    assert form == SearchForm("CA", "Orange County", "Honda", "Civic", owner=True, dealer=False)
    assert form.problem() is None


def test_a_link_can_turn_off_carfax():
    form = SearchForm.from_query({"state": "CA", "city": "Orange County", "make": "Honda", "model": "Civic", "carfax": "0"})

    assert form == SearchForm("CA", "Orange County", "Honda", "Civic", carfax=False)


def test_a_link_with_unknown_values_fills_what_it_can():
    form = SearchForm.from_query({"state": "CA", "city": "Atlantis", "make": "Zorblat", "model": "Civic"})

    assert form == SearchForm(state="CA")
    assert form.problem() == "Pick a state, city, make, and model"


def test_a_city_or_model_is_dropped_when_its_state_or_make_is_unknown():
    form = SearchForm.from_query({"state": "ZZ", "city": "Orange County", "make": "Nope", "model": "Civic"})

    assert form == SearchForm()


def test_a_known_make_keeps_a_model_only_if_the_make_has_it():
    assert SearchForm.from_query({"make": "Acura", "model": "Civic"}).model is None
    assert SearchForm.from_query({"make": "Acura", "model": "ILX"}).model == "ILX"


def test_a_link_with_no_checkbox_or_an_unreadable_one_checks_all_three():
    defaults = SearchForm.from_query({})
    assert defaults.owner and defaults.dealer and defaults.carfax
    form = SearchForm.from_query({"owner": "maybe", "dealer": "FALSE", "carfax": "off"})
    assert form.owner and not form.dealer and not form.carfax


def test_the_query_round_trips_through_the_form():
    form = complete_form()
    form.owner = False
    form.carfax = False

    assert SearchForm.from_query(form.to_query()) == form
    assert SearchForm().to_query() == {"owner": "1", "dealer": "1", "carfax": "1"}


def test_changing_a_dropdown_keeps_the_checkboxes():
    form = complete_form()
    form.owner, form.carfax = False, False

    form.choose_state("TX")
    form.choose_make("Acura")

    assert (form.owner, form.dealer, form.carfax) == (False, True, False)


def test_only_a_url_naming_a_search_overrides_the_browsers_memory():
    assert has_search_params({"make": "Honda"})
    assert has_search_params({"dealer": "0"})
    assert has_search_params({"carfax": "0"})
    assert not has_search_params({"utm": "x"})


def test_the_storage_secret_is_made_once_and_reused(tmp_path):
    directory = tmp_path / "store"

    first = storage_secret(directory)

    assert len(first) == 64
    assert storage_secret(directory) == first
    assert (directory / "storage_secret").stat().st_mode & 0o077 == 0
