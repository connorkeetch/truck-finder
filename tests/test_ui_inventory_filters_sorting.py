"""Inventory controls pass real filters and one shared sort into both visual layouts."""
import pytest
import streamlit as st

from conftest import listing, vin
from rivian_finder import deals, pipeline, queries
from rivian_finder.ui import common, inventory


@pytest.mark.parametrize("key", ["inv", "set"])
def test_deal_seller_and_drop_controls_return_selected_filters(key):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string(f"""
import streamlit as st
from rivian_finder.config import default_settings
from rivian_finder.ui.inventory import filter_controls
st.session_state['filters'] = filter_controls(default_settings()['filters'], key={key!r})
""").run(timeout=10)
    assert not app.exception
    assert app.multiselect(key=f"{key}_deal_types").options == list(deals.DEAL_TYPES)
    app.multiselect(key=f"{key}_deal_types").set_value(["Good deal", "Not rated (branded title)"])
    app.multiselect(key=f"{key}_seller_types").set_value(["private"])
    app.multiselect(key=f"{key}_match_statuses").set_value(["Needs verification"])
    app.checkbox(key=f"{key}_price_drops").set_value(True).run(timeout=10)
    assert not app.exception
    filters = app.session_state["filters"]
    assert filters["deal_types"] == ["Good deal", "Not rated (branded title)"]
    assert filters["seller_types"] == ["private"]
    assert filters["match_statuses"] == ["Needs verification"]
    assert filters["price_drops_only"] is True


@pytest.mark.parametrize("layout", ["Cards", "Table"])
def test_inventory_filters_then_sorts_the_same_results_in_both_layouts(conn, settings, monkeypatch, layout):
    from streamlit.testing.v1 import AppTest
    pipeline.import_listings(conn, [listing(vin=vin(i), price=price) for i, price in
                                    [(901, 60000), (902, 55000), (903, 58000), (904, 62000)]], "manual_entry")
    frame = queries.inventory_frame(conn, settings).sort_values("price", ascending=False).reset_index(drop=True)
    frame["deal_label"] = ["Good deal", "Good deal (accident reported)", "Good deal", "Great deal"]
    frame["deal_type"] = frame["deal_label"].map(deals.deal_type)
    frame["seller_type"] = ["dealer", "dealer", "dealer", "private"]
    frame["price_drops"] = [1, 2, 0, 1]
    with_drops = frame.iloc[:2]["vehicle_id"].tolist()
    all_good_dealers = frame.iloc[:3]["vehicle_id"].tolist()
    frame = frame.iloc[[2, 1, 3, 0]].reset_index(drop=True)
    settings["filters"].update(near_misses=False, max_price=100000, max_miles=100000)
    settings.setdefault("ui", {})["inventory_view"] = layout
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common, "inventory", lambda *args: frame.copy())
    monkeypatch.setattr(common, "save_settings", lambda *args: None)
    monkeypatch.setattr(common, "photo_size_control", lambda *args: "S")
    monkeypatch.setattr(inventory.add_truck, "add_truck_panel", lambda *args: None)
    monkeypatch.setattr(inventory.refresh_changes, "render", lambda *args: None)
    monkeypatch.setattr(inventory, "adjustments_editor", lambda *args: None)
    monkeypatch.setattr(inventory.services, "run_sources", lambda *args, **kwargs: pytest.fail("Rendering must not search."))
    monkeypatch.setattr(inventory.cards, "render", lambda payload, *args: st.session_state.__setitem__("rendered_ids", [r["vid"] for r in payload]))
    monkeypatch.setattr(inventory, "_table", lambda view, *args: st.session_state.__setitem__("rendered_ids", view["vehicle_id"].tolist()))
    app = AppTest.from_string("from rivian_finder.ui.inventory import render\nrender()").run(timeout=10)
    assert not app.exception
    assert app.selectbox(key="inv_sort").options == list(queries.SORT_OPTIONS)
    app.multiselect(key="inv_deal_types").set_value(["Good deal"])
    app.multiselect(key="inv_seller_types").set_value(["dealer"])
    app.checkbox(key="inv_price_drops").set_value(True)
    app.selectbox(key="inv_sort").set_value("Price ↓").run(timeout=10)
    assert not app.exception
    assert app.session_state["rendered_ids"] == with_drops
    app.checkbox(key="inv_price_drops").set_value(False).run(timeout=10)
    assert not app.exception
    assert app.session_state["rendered_ids"] == all_good_dealers
    assert app.selectbox(key="inv_sort").value == "Price ↓"
