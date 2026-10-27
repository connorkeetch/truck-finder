"""Inventory actions change the current view without resetting the shopper's saved setup."""
import copy
import urllib.request

import pytest
import requests
import streamlit as st

from conftest import listing, vin
from rivian_finder import db, pipeline, queries, services
from rivian_finder.ui import common, inventory


@pytest.fixture
def inventory_ui(conn, monkeypatch):
    from streamlit.testing.v1 import AppTest

    def no_network(*args, **kwargs):
        pytest.fail("Inventory actions must not call a network or listing provider")

    def render_cards(payload, key, on_change, *args):
        st.session_state["rendered_ids"] = [row["vid"] for row in payload]
        if payload:
            def open_first():
                st.session_state[key] = {"action": {"kind": "open", "vid": payload[0]["vid"]}}
                on_change()
            st.button("Open first vehicle", key="test_open_card", on_click=open_first)

    def details(vid, note=""):
        st.write(f"Vehicle {vid}")
        st.button("Close vehicle", key="test_close_card", on_click=inventory._close_details)

    monkeypatch.setattr(requests.Session, "request", no_network)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setattr(services, "run_sources", no_network)
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "inventory", lambda s=None: queries.inventory_frame(conn, s or db.load_settings(conn)))
    monkeypatch.setattr(common, "photo_size_control", lambda *args: "S")
    monkeypatch.setattr(inventory.cards, "render", render_cards)
    monkeypatch.setattr(inventory, "details_dialog", details)
    monkeypatch.setattr(inventory.refresh_changes, "render", lambda *args: None)
    monkeypatch.setattr(inventory.refresh_changes, "render_retired", lambda *args, **kwargs: None)
    return lambda: AppTest.from_string("from rivian_finder.ui.inventory import render\nrender()").run(timeout=15)


def _listings(conn):
    result = pipeline.import_listings(conn, [listing(vin=vin(i), price=price, miles=miles)
                                           for i, price, miles in [(901, 55000, 12000), (902, 62000, 18000),
                                                                   (903, 95000, 150000)]], "manual_entry")
    return result["vehicle_ids"]


@pytest.mark.parametrize("selected,field,expected", [
    ({"brands": ["Rivian"]}, "brands", {"brands": []}),
    ({"models": ["R1T"]}, "models", {"models": []}),
    ({"states": ["UT"]}, "states", {"states": []}),
    ({"max_price": 55000}, "max_price", {"max_price": 0}),
    ({"max_miles": 15000}, "max_miles", {"max_miles": 0}),
    ({"include_unknown_range": False}, "known_range", {"include_unknown_range": True}),
    ({"favorites_only": True}, "favorites_only", {"favorites_only": False}),
    ({"hidden_only": True}, "hidden_only", {"hidden_only": False}),
])
def test_filter_chip_clears_only_its_criterion(selected, field, expected):
    filters = {**inventory.clear_filter_values(), **selected}
    original = copy.deepcopy(filters)
    chip = next(chip for chip in inventory.active_filter_chips(filters) if chip[0] == field)
    assert chip[2] == expected
    assert filters == original


def test_removing_price_chip_keeps_mileage_and_saved_defaults(conn, inventory_ui):
    _listings(conn)
    saved = db.load_settings(conn)
    saved["filters"].update(max_price=60000, max_miles=20000, near_misses=False)
    db.save_settings(conn, saved)
    app = inventory_ui()
    assert not app.exception
    app.button(key="inv_chip_max_price").click().run(timeout=15)
    assert not app.exception
    assert app.number_input(key="inv_price").value == 0
    assert app.number_input(key="inv_miles").value == 20000
    assert app.session_state["inv_filters"]["max_price"] == 0
    assert len(app.session_state["rendered_ids"]) == 2
    assert db.load_settings(conn) == saved


def test_reset_defaults_clears_optional_model_selection_missing_from_saved_filters(conn, inventory_ui):
    _listings(conn)
    saved = db.load_settings(conn)
    assert "models" not in saved["filters"]
    app = inventory_ui()
    app.multiselect(key="inv_models").set_value(["R1T"]).run(timeout=15)
    assert not app.exception
    app.button(key="inv_reset_defaults").click().run(timeout=15)
    assert not app.exception
    assert app.multiselect(key="inv_models").value == []
    assert app.session_state["inv_filters"]["models"] == []
    assert db.load_settings(conn) == saved


def test_clear_all_clears_hidden_favorites_updates_and_search_without_saving(conn, inventory_ui):
    ids = _listings(conn)
    saved = db.load_settings(conn)
    saved["filters"].update(max_price=60000, max_miles=20000, hidden_only=True, favorites_only=True,
                             brands=["Ford"], near_misses=False)
    db.save_settings(conn, saved)
    app = inventory_ui()
    assert not app.exception
    app.text_input(key="inv_search").set_value("nothing matches")
    app.selectbox(key="inv_updates").set_value("Price changes").run(timeout=15)
    app.button(key="inv_clear_filters").click().run(timeout=15)
    assert not app.exception
    assert app.session_state["inv_filters"] == inventory.clear_filter_values()
    assert app.toggle(key="inv_hidden_only").value is False
    assert app.toggle(key="inv_favorites_only").value is False
    assert app.selectbox(key="inv_updates").value == "All listings"
    assert app.text_input(key="inv_search").value == ""
    assert set(app.session_state["rendered_ids"]) == set(ids)
    assert db.load_settings(conn) == saved


def test_zero_price_and_mileage_limits_include_expensive_high_mileage_vehicles(conn):
    ids = _listings(conn)
    saved = db.load_settings(conn)
    frame = queries.inventory_frame(conn, saved)
    shown = queries.apply_filters(frame, inventory.clear_filter_values())
    assert set(shown["vehicle_id"]) == set(ids)
    assert shown["price"].max() == 95000
    assert shown["miles"].max() == 150000


def test_favorites_and_sort_survive_opening_and_closing_card(conn, inventory_ui):
    ids = _listings(conn)
    for vid in ids[:2]:
        services.toggle_favorite(conn, vid, True)
    saved = db.load_settings(conn)
    saved["filters"].update(max_price=0, max_miles=0, near_misses=False)
    db.save_settings(conn, saved)
    app = inventory_ui()
    app.toggle(key="inv_favorites_only").set_value(True)
    app.selectbox(key="inv_sort").set_value("Price ↓").run(timeout=15)
    assert not app.exception
    assert app.session_state["rendered_ids"] == [ids[1], ids[0]]
    app.button(key="test_open_card").click().run(timeout=15)
    assert not app.exception
    assert app.session_state["dialog_vid"] == ids[1]
    app.button(key="test_close_card").click().run(timeout=15)
    assert not app.exception
    assert "dialog_vid" not in app.session_state
    assert app.toggle(key="inv_favorites_only").value is True
    assert app.selectbox(key="inv_sort").value == "Price ↓"
    assert app.session_state["rendered_ids"] == [ids[1], ids[0]]
    assert db.load_settings(conn) == saved


def test_inventory_view_survives_page_navigation_and_clear_all(conn, inventory_ui, tmp_path):
    from streamlit.testing.v1 import AppTest

    ids = _listings(conn)
    services.toggle_favorite(conn, ids[0], True)
    saved = db.load_settings(conn)
    saved["filters"].update(max_price=0, max_miles=0, near_misses=False)
    db.save_settings(conn, saved)
    (tmp_path / "inventory.py").write_text("from rivian_finder.ui.inventory import render\nrender()", encoding="utf-8")
    (tmp_path / "other.py").write_text("import streamlit as st\nst.write('Another page')", encoding="utf-8")
    main = tmp_path / "app.py"
    main.write_text("import streamlit as st\nst.navigation([st.Page('inventory.py', default=True), st.Page('other.py')]).run()",
                    encoding="utf-8")
    app = AppTest.from_file(str(main)).run(timeout=15)
    assert not app.exception
    app.toggle(key="inv_favorites_only").set_value(True)
    app.text_input(key="inv_search").set_value("Rivian")
    app.selectbox(key="inv_sort").set_value("Price ↓")
    app.selectbox(key="inv_updates").set_value("New / new source").run(timeout=15)
    assert not app.exception
    app.switch_page("other.py").run(timeout=15)
    assert not app.exception
    assert "inv_sort" not in app.session_state
    assert "inv_search" not in app.session_state
    assert "inv_updates" not in app.session_state
    app.switch_page("inventory.py").run(timeout=15)
    assert not app.exception
    assert app.toggle(key="inv_favorites_only").value is True
    assert app.selectbox(key="inv_sort").value == "Price ↓"
    assert app.text_input(key="inv_search").value == "Rivian"
    assert app.selectbox(key="inv_updates").value == "New / new source"
    app.button(key="inv_clear_filters").click().run(timeout=15)
    assert not app.exception
    assert app.session_state["_inv_search"] == ""
    assert app.session_state["_inv_updates"] == "All listings"
    app.switch_page("other.py").run(timeout=15)
    app.switch_page("inventory.py").run(timeout=15)
    assert not app.exception
    assert app.text_input(key="inv_search").value == ""
    assert app.selectbox(key="inv_updates").value == "All listings"
    assert app.selectbox(key="inv_sort").value == "Price ↓"
    assert app.toggle(key="inv_favorites_only").value is False
    assert db.load_settings(conn) == saved


def test_try_demo_needs_no_network_and_keeps_saved_settings(conn, inventory_ui):
    saved = db.load_settings(conn)
    saved["home_zip"] = "10001"
    saved["collection"]["searches"] = [{"make": "Toyota", "model": "Tacoma"}]
    saved["filters"].update(max_price=10000, show_demo=False)
    db.save_settings(conn, saved)
    app = inventory_ui()
    assert not app.exception
    app.button(key="inv_try_demo").click().run(timeout=15)
    assert not app.exception
    vehicles = conn.execute("SELECT COUNT(*), SUM(is_demo) FROM vehicles").fetchone()
    assert vehicles[0] == vehicles[1] > 0
    assert app.session_state["rendered_ids"]
    assert conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0] == 0
    assert db.load_settings(conn) == saved
