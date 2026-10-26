"""Recorded updates reach cards/table and never hide the unavailable-truck archive."""
import copy

import pandas as pd
import pytest
import streamlit as st

from conftest import listing, vin
from rivian_finder import pipeline, queries
from rivian_finder.ui import common, inventory


@pytest.fixture
def inventory_app(conn, settings, monkeypatch):
    from streamlit.testing.v1 import AppTest
    pipeline.import_listings(conn, [listing(vin=vin(n), price=55000 + n) for n in (930, 931, 932)], "manual_entry")
    frame = queries.inventory_frame(conn, settings).sort_values("vin").reset_index(drop=True)
    settings["filters"].update(near_misses=False, max_price=100000, max_miles=100000)
    base = {"run_id": 2, "created_at": "2026-10-26T10:00:00Z", "source": "Auto.dev",
            "source_key": "manual_entry", "url": "https://dealer.example/truck", "update_origin": "Refresh"}
    result = {"run": {"id": 2}, "events": pd.DataFrame([
        {**base, "id": 1, "vehicle_id": frame.iloc[0]["vehicle_id"], "listing_id": frame.iloc[0]["listing_id"],
         "event_type": "new_listing", "category": "new"},
        {**base, "id": 2, "vehicle_id": frame.iloc[1]["vehicle_id"], "listing_id": frame.iloc[1]["listing_id"],
         "event_type": "price_drop", "category": "price", "old_value": "60000", "new_value": "55000"},
    ])}
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common, "inventory", lambda *args: frame.copy())
    monkeypatch.setattr(common, "photo_size_control", lambda *args: "S")
    monkeypatch.setattr(common, "save_settings", lambda *args: pytest.fail("Viewing must not save settings."))
    monkeypatch.setattr(queries, "refresh_changes", lambda *args: copy.deepcopy(result))
    monkeypatch.setattr(inventory.add_truck, "add_truck_panel", lambda *args: None)
    monkeypatch.setattr(inventory.refresh_changes, "render", lambda *args: None)
    monkeypatch.setattr(inventory, "adjustments_editor", lambda *args: None)
    monkeypatch.setattr(inventory.services, "run_sources", lambda *args, **kwargs: pytest.fail("Viewing must not search."))

    def retired(c, s, inv, refresh, key):
        st.session_state["retired_ids"] = inv["vehicle_id"].tolist()
        st.session_state["retired_run"] = refresh["run"]["id"]
    monkeypatch.setattr(inventory.refresh_changes, "render_retired", retired)
    monkeypatch.setattr(inventory.cards, "render", lambda payload, *args: st.session_state.__setitem__("cards", payload))
    monkeypatch.setattr(inventory, "_table", lambda view, *args: st.session_state.__setitem__("table", view.to_dict("records")))

    def run(layout="Cards"):
        settings.setdefault("ui", {})["inventory_view"] = layout
        return AppTest.from_string("from rivian_finder.ui.inventory import render\nrender()").run(timeout=10)
    return run, frame, conn


@pytest.mark.parametrize("layout", ["Cards", "Table"])
def test_update_filter_and_badges_share_results_in_both_layouts(inventory_app, layout):
    run, frame, conn = inventory_app
    before = conn.total_changes
    app = run(layout)
    assert not app.exception
    app.selectbox(key="inv_updates").set_value("Price changes").run(timeout=10)
    assert not app.exception
    records = app.session_state["cards" if layout == "Cards" else "table"]
    assert [r["vid" if layout == "Cards" else "vehicle_id"] for r in records] == [frame.iloc[1]["vehicle_id"]]
    assert records[0]["refresh_badges"][0]["text"] == "Price down $5,000"
    if layout == "Table":
        assert records[0]["updates"] == "Price down $5,000"
    app.selectbox(key="inv_updates").set_value("New / new source").run(timeout=10)
    records = app.session_state["cards" if layout == "Cards" else "table"]
    assert [r["vid" if layout == "Cards" else "vehicle_id"] for r in records] == [frame.iloc[0]["vehicle_id"]]
    app.selectbox(key="inv_updates").set_value("Changed since refresh").run(timeout=10)
    records = app.session_state["cards" if layout == "Cards" else "table"]
    assert len(records) == 2
    assert conn.total_changes == before


def test_empty_filtered_results_still_receive_unfiltered_archive(inventory_app):
    run, frame, conn = inventory_app
    app = run()
    app.selectbox(key="inv_updates").set_value("Listing status changes").run(timeout=10)
    assert not app.exception
    assert any("No trucks match" in item.value for item in app.info)
    assert app.session_state["retired_ids"] == frame["vehicle_id"].tolist()
    assert app.session_state["retired_run"] == 2


def test_exact_vin_lookup_bypasses_update_filter(inventory_app):
    run, frame, conn = inventory_app
    app = run()
    app.selectbox(key="inv_updates").set_value("Price changes")
    app.text_input(key="inv_search").set_value(frame.iloc[2]["vin"]).run(timeout=10)
    assert not app.exception
    assert [r["vid"] for r in app.session_state["cards"]] == [frame.iloc[2]["vehicle_id"]]
    assert any("outside the Updates filter" in item.value for item in app.caption)


def test_empty_inventory_still_renders_archive(inventory_app):
    run, frame, conn = inventory_app
    frame.drop(frame.index, inplace=True)
    app = run()
    assert not app.exception
    assert app.session_state["retired_ids"] == []
