import pytest

from craigslist.listings import OwnerType
from craigslist.page import SearchForm
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


def test_search_is_blocked_with_both_owner_types_unchecked():
    form = complete_form()
    form.owner = form.dealer = False

    assert form.problem() == "Pick owner, dealer, or both"


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
