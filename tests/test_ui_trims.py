"""Trim controls preserve selections and allow restoring the excluded base models."""
import pandas as pd
import pytest


@pytest.mark.parametrize("key", ["inv", "set"])
def test_trim_choices_survive_brand_changes_and_missing_saved_trim(key):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(f'''
import streamlit as st
from rivian_finder.config import default_settings
from rivian_finder.ui.inventory import filter_controls
f = default_settings()["filters"]
f["trims"] = ["Ford · Platinum"]
st.session_state["result"] = filter_controls(
    f, key={key!r}, trim_options=["Ford · Lariat", "Chevrolet · LT"])
''').run()
    assert not app.exception
    trims = app.multiselect(key=f"{key}_trims")
    assert trims.options == ["Chevrolet · LT", "Ford · Lariat", "Ford · Platinum"]
    assert trims.value == ["Ford · Platinum"]
    app.multiselect(key=f"{key}_brands").set_value(["Chevrolet"]).run()
    assert not app.exception
    assert app.multiselect(key=f"{key}_trims").value == ["Ford · Platinum"]
    app.multiselect(key=f"{key}_trims").set_value(["Chevrolet · LT"]).run()
    assert app.session_state["result"]["trims"] == ["Chevrolet · LT"]


def test_settings_can_restore_base_trims_and_standard_range_without_touching_inventory(conn, settings, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from rivian_finder.ui import common, settings_page

    saved = []
    settings["collection"].update(searches=None, excluded_trims={"Ford": ["Pro"], "Chevrolet": ["WT"]},
                                   exclude_standard_range=True)
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common, "inventory", lambda s: pd.DataFrame())
    monkeypatch.setattr(common, "save_settings", lambda s: saved.append(s))
    monkeypatch.setattr(settings_page.credentials, "get_api_key", lambda key: ("", "not configured"))
    monkeypatch.setattr(settings_page, "alert_settings", lambda *args: None)
    monkeypatch.setattr(settings_page, "phone_settings", lambda: None)
    app = AppTest.from_string("from rivian_finder.ui.settings_page import render\nrender()").run()
    assert not app.exception
    ford = next(w for w in app.multiselect if w.label == "Exclude Ford Lightning trims")
    chevy = next(w for w in app.multiselect if w.label == "Exclude Chevrolet Silverado EV trims")
    standard_range = next(w for w in app.checkbox if w.label == "Exclude Standard Range trucks (Ford, Chevrolet, GMC)")
    assert ford.value == ["Pro"] and chevy.value == ["WT"]
    assert standard_range.value is True
    ford.set_value([])
    chevy.set_value([])
    standard_range.set_value(False)
    next(b for b in app.button if b.label == "Save collection scope").click().run()
    assert not app.exception
    assert saved[-1]["collection"]["excluded_trims"] == {"Ford": [], "Chevrolet": []}
    assert saved[-1]["collection"]["exclude_standard_range"] is False
    next(w for w in app.checkbox if w.label == "Exclude Standard Range trucks (Ford, Chevrolet, GMC)").set_value(True)
    next(b for b in app.button if b.label == "Save collection scope").click().run()
    assert not app.exception
    assert saved[-1]["collection"]["exclude_standard_range"] is True
    assert conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 0
