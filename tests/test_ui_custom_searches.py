"""Custom make/model setup and refresh choices work without querying providers."""
import copy

import pandas as pd
import pytest

from rivian_finder.sources.base import EV_TRUCK_PRESET
from rivian_finder.ui import common, settings_page


def test_make_model_lines_are_normalized_and_deduplicated():
    assert settings_page.parse_searches("Toyota | Tacoma\nToyota | Tundra\nRam | 1500\n toyota |  tacoma \n") == [
        {"make": "Toyota", "model": "Tacoma"}, {"make": "Toyota", "model": "Tundra"}, {"make": "Ram", "model": "1500"}]


@pytest.mark.parametrize("text", ["", "Toyota", "Toyota |", "| Tacoma", "Toyota,Ford | Tacoma", "Toyota | Tacoma | TRD"])
def test_invalid_make_model_lines_are_rejected(text):
    with pytest.raises(ValueError):
        settings_page.parse_searches(text)


@pytest.fixture
def custom_settings_app(conn, settings, monkeypatch):
    from streamlit.testing.v1 import AppTest
    settings["collection"]["searches"] = [{"make": "Toyota", "model": "Tacoma"}]
    settings["collection"].update(excluded_trims={"Ford": ["Pro"], "Chevrolet": ["WT"]}, exclude_standard_range=True)
    saved = []
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: copy.deepcopy(settings))
    monkeypatch.setattr(common, "inventory", lambda s: pd.DataFrame())
    monkeypatch.setattr(common, "save_settings", lambda s: saved.append(copy.deepcopy(s)))
    monkeypatch.setattr(settings_page.credentials, "get_api_key", lambda key: ("", "not configured"))
    monkeypatch.setattr(settings_page, "alert_settings", lambda *args: None)
    monkeypatch.setattr(settings_page, "phone_settings", lambda: None)
    app = AppTest.from_string("from rivian_finder.ui.settings_page import render\nrender()").run(timeout=10)
    assert not app.exception
    return app, saved


def test_custom_searches_save_common_limits_and_preserve_ev_preferences(custom_settings_app):
    app, saved = custom_settings_app
    assert app.checkbox(key="collection_custom_searches").value
    assert app.number_input(key="collection_max_distance").value == 0
    assert not any(w.label.startswith("Other brands:") for w in app.number_input)
    assert not any(w.label == "MarketCheck search ZIP" for w in app.text_input)
    assert any(w.label == "Exclude Ford Lightning trims" for w in app.multiselect)
    app.text_area(key="collection_searches_text").set_value("Toyota | Tacoma\nToyota | Tundra\nRam | 1500")
    app.number_input(key="collection_max_distance").set_value(450)
    app.checkbox(key="collection_used_only").set_value(False)
    next(b for b in app.button if b.label == "Save collection scope").click().run(timeout=10)
    assert not app.exception
    assert saved[-1]["collection"]["searches"] == settings_page.parse_searches("Toyota | Tacoma\nToyota | Tundra\nRam | 1500")
    assert saved[-1]["collection"]["max_distance"] == 450
    assert saved[-1]["collection"]["used_only"] is False
    assert saved[-1]["collection"]["excluded_trims"] == {"Ford": ["Pro"], "Chevrolet": ["WT"]}
    assert saved[-1]["collection"]["exclude_standard_range"] is True


def test_invalid_searches_do_not_save_and_ev_preset_can_restore(custom_settings_app):
    app, saved = custom_settings_app
    app.text_area(key="collection_searches_text").set_value("")
    next(b for b in app.button if b.label == "Save collection scope").click().run(timeout=10)
    assert not app.exception and app.error
    assert not saved
    app.button(key="collection_ev_presets").click().run(timeout=10)
    assert not app.exception
    assert settings_page.parse_searches(app.text_area(key="collection_searches_text").value) == EV_TRUCK_PRESET


def test_custom_searches_can_return_to_legacy_mode(custom_settings_app):
    app, saved = custom_settings_app
    app.checkbox(key="collection_custom_searches").set_value(False).run(timeout=10)
    assert not app.exception
    assert not any(w.key == "collection_searches_text" for w in app.text_area)
    next(b for b in app.button if b.label == "Save collection scope").click().run(timeout=10)
    assert saved[-1]["collection"]["searches"] is None


def test_invalid_saved_searches_can_be_repaired(custom_settings_app, settings):
    from streamlit.testing.v1 import AppTest

    app, saved = custom_settings_app
    settings["collection"]["searches"] = []
    app = AppTest.from_string("from rivian_finder.ui.settings_page import render\nrender()").run(timeout=10)
    assert not app.exception
    app.text_area(key="collection_searches_text").set_value("Honda | Civic")
    next(b for b in app.button if b.label == "Save collection scope").click().run(timeout=10)
    assert not app.exception
    assert saved[-1]["collection"]["searches"] == [{"make": "Honda", "model": "Civic"}]


def test_filter_controls_offer_configured_or_stored_make_and_model_choices():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string("""
import streamlit as st
from rivian_finder.config import default_settings
from rivian_finder.ui.inventory import filter_controls
f = default_settings()['filters']
f['models'] = ['Older saved model']
st.session_state['result'] = filter_controls(f, brand_options=['Toyota', 'Ram'], model_options=['Tacoma', '1500'])
""").run(timeout=10)
    assert not app.exception
    assert app.multiselect(key="inv_brands").options == ["Ram", "Toyota"]
    assert app.multiselect(key="inv_models").options == ["1500", "Older saved model", "Tacoma"]
    assert not any(w.key == "inv_bat" for w in app.multiselect)
    app.multiselect(key="inv_brands").set_value(["Toyota"])
    app.multiselect(key="inv_models").set_value(["Tacoma"]).run(timeout=10)
    assert app.session_state["result"]["models"] == ["Tacoma"]


def test_run_search_lists_only_configured_makes_and_all_uses_only_those(monkeypatch):
    from streamlit.testing.v1 import AppTest
    settings = {"collection": {"searches": [{"make": "Toyota", "model": "Tacoma"},
                                               {"make": "Toyota", "model": "Tundra"},
                                               {"make": "Ram", "model": "1500"}]}}
    calls = []
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common, "conn", lambda: "connection")
    monkeypatch.setattr(common.services, "run_sources", lambda c, keys, s, brands: calls.append(brands) or {"text": "Done"})
    app = AppTest.from_string("""
import streamlit as st
from rivian_finder.ui import common
st.session_state.setdefault('last_search_brands', ['Ford'])
if st.button('Run Search', key='open'):
    common.search_dialog()
""").run(timeout=10)
    app.button(key="open").click().run(timeout=10)
    assert not app.exception
    assert app.multiselect(key="search_brands").options == ["All brands", "Toyota (Tacoma, Tundra)", "Ram (1500)"]
    assert app.multiselect(key="search_brands").value == ["Toyota"]
    assert not calls
    app.multiselect(key="search_brands").set_value(["All brands"])
    app.button(key="open").click()
    app.button(key="search_start").click().run(timeout=10)
    assert not app.exception
    assert calls == [["Toyota", "Ram"]]


def test_manual_entry_uses_generic_text_make_and_model():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string("""
import streamlit as st
from rivian_finder.ui.forms import listing_review_form
result = listing_review_form({'make': 'Toyota', 'model': 'Tacoma', 'year': 2018, 'price': 25000}, 'manual', 'manual', show_claims=False)
if result:
    st.session_state['vehicle'] = (result.make, result.model)
""").run(timeout=10)
    next(w for w in app.text_input if w.label == "Make").set_value("Honda")
    next(w for w in app.text_input if w.label == "Model").set_value("Ridgeline")
    next(b for b in app.button if b.label == "Save listing").click().run(timeout=10)
    assert not app.exception
    assert app.session_state["vehicle"] == ("Honda", "Ridgeline")


def test_manual_block_starts_with_first_configured_pair(monkeypatch):
    from rivian_finder.ui import add_truck
    pair = {"make": "Toyota", "model": "Tacoma"}
    seen = []
    monkeypatch.setattr(common, "settings", lambda: {"collection": {"searches": [pair]}})
    monkeypatch.setattr(add_truck, "listing_review_form", lambda draft, *args, **kwargs: seen.append(draft))
    add_truck.manual_block("configured_test")
    assert seen == [pair]
