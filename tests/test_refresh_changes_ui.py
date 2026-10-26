"""The refresh section renders persistent, source-specific updates without searching."""
import copy

import pandas as pd
import pytest

from conftest import FakeAdapter, listing, vin
from rivian_finder import pipeline, queries
from rivian_finder.models import FetchResult
from rivian_finder.ui import common, refresh_changes


def changes():
    base = {"created_at": "2026-10-25T12:05:00Z", "run_id": 2, "vehicle_id": 1, "listing_id": 1,
            "make": "Ford", "model": "F-150 Lightning", "trim": "Lariat", "year": 2023, "vin": "",
            "source": "Auto.dev", "seller_name": "Test dealer", "state": "UT", "current_price": 57500,
            "current_miles": 20000, "is_demo": False, "listing_status": "active", "update_origin": "Refresh",
            "old_value": None, "new_value": None, "old_price": None, "new_price": None, "price_delta": None,
            "url": "https://dealer.example/ford"}
    return {"run": {"id": 2, "started_at": "2026-10-25T12:00:00Z", "status": "partial", "first_refresh": False,
                    "summary": {"sources": [{"source": "autodev", "name": "Auto.dev", "status": "success"},
                                               {"source": "marketcheck", "name": "MarketCheck", "status": "partial",
                                                "notes": ["Page cap reached.", "Collection scope changed; disappearance detection skipped."],
                                                "error": "Incomplete scan"}]}},
            "events": pd.DataFrame([
                {**base, "category": "new", "event_type": "new_source_for_vin", "new_price": 59000, "new_value": "59000"},
                {**base, "category": "price", "event_type": "price_drop", "old_value": "60000", "new_value": "58500",
                 "old_price": 60000, "new_price": 58500, "price_delta": -1500},
                {**base, "category": "price", "event_type": "price_increase", "old_price": 50000,
                 "new_price": 51000, "price_delta": 1000, "url": "https://other.example/ford"},
                {**base, "category": "removed", "event_type": "marked_removed", "make": "Chevrolet",
                 "model": "Silverado EV", "trim": "4WT", "listing_status": "removed", "update_origin": "After refresh",
                 "new_value": "Marked sold/removed by user", "url": "https://dealer.example/chevy"},
                {**base, "category": "missing", "event_type": "disappeared", "make": "GMC", "model": "Sierra EV",
                 "trim": "Denali", "listing_status": "missing", "url": "https://dealer.example/gmc"},
            ])}


@pytest.fixture
def render_app(monkeypatch, conn, settings):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common, "inventory", lambda *args: pytest.fail("Refresh rendering does not need inventory."))
    monkeypatch.setattr(common.services, "run_sources", lambda *args, **kwargs: pytest.fail("Rendering must not search."))

    def run(result=None):
        if result is not None:
            monkeypatch.setattr(queries, "refresh_changes", lambda c: copy.deepcopy(result))
        app = AppTest.from_string("""
import streamlit as st
from rivian_finder.ui import common, refresh_changes
st.session_state['last_summary'] = {'text': 'Stale session summary'}
refresh_changes.render(common.conn(), common.settings())
""").run(timeout=10)
        assert not app.exception
        return app

    return run


def test_source_identity_prices_and_removed_rows_ignore_inventory_filters(render_app, settings):
    settings["filters"].update(brands=["Rivian"], max_price=1, favorites_only=True, include_missing=False)
    app = render_app(changes())
    assert [t.label for t in app.tabs] == ["New listings (1)", "Price changes (2)", "Sold or removed (1)", "Not seen (1)"]
    new, prices, removed, missing = [frame.value for frame in app.dataframe]
    assert new.iloc[0]["Update"] == "New source for known vehicle"
    assert "Ford F-150 Lightning Lariat" in new.iloc[0]["Vehicle"]
    assert new.iloc[0]["Listed price"] == 59000
    assert prices["Before"].tolist() == [60000, 50000]
    assert prices["After"].tolist() == [58500, 51000]
    assert prices["Change ($)"].tolist() == ["-$1,500", "+$1,000"]
    assert prices["Listing"].tolist() == ["https://dealer.example/ford", "https://other.example/ford"]
    assert removed.iloc[0]["Listing"] == "https://dealer.example/chevy"
    assert "Chevrolet Silverado EV 4WT" in removed.iloc[0]["Vehicle"]
    assert removed.iloc[0]["Recorded"] == "After refresh"
    assert removed.iloc[0]["Listing status"] == "removed"
    assert missing.iloc[0]["Listing status"] == "missing"
    assert any("sale is unconfirmed" in item.value for item in app.caption)
    assert any("MarketCheck: partial" in item.value for item in app.warning)
    assert any("disappearance detection skipped" in item.value for item in app.caption)
    assert not any("Page cap reached" in item.value for item in app.caption)


def test_first_refresh_and_empty_window_explain_baseline(render_app):
    result = changes()
    result["run"]["first_refresh"] = True
    result["events"] = result["events"].iloc[:0]
    app = render_app(result)
    assert any("establishes a baseline" in item.value for item in app.info)
    assert any("No recorded changes" in item.value for item in app.info)


def test_no_refresh_has_a_prompt_and_no_rows(render_app):
    app = render_app({"run": None, "events": pd.DataFrame()})
    assert any("No refresh yet" in item.value for item in app.info)
    assert not app.dataframe


def test_first_failed_refresh_does_not_claim_a_baseline_or_unchanged_inventory(render_app):
    result = changes()
    result["run"].update(first_refresh=True, status="failed")
    result["events"] = result["events"].iloc[:0]
    result["run"]["summary"]["sources"] = [{"name": "Auto.dev", "status": "failed", "error": "HTTP 503"}]
    app = render_app(result)
    assert not any("baseline" in item.value for item in app.info)
    assert any("not confirmation" in item.value for item in app.warning)
    assert any("HTTP 503" in item.value for item in app.warning)


def test_demo_preference_is_the_only_inventory_filter_applied(render_app, settings):
    result = changes()
    demo = result["events"].iloc[:1].copy()
    demo["is_demo"] = True
    demo["url"] = "https://demo.example/truck"
    result["events"] = pd.concat([result["events"], demo], ignore_index=True)
    settings["filters"]["show_demo"] = False
    app = render_app(result)
    assert app.tabs[0].label == "New listings (1)"
    assert not any("demo.example" in str(frame.value) for frame in app.dataframe)


def test_new_app_session_reads_the_same_persisted_search(render_app, conn):
    adapter = FakeAdapter("autodev", [FetchResult([listing(vin=vin(900), price=60000)], True, "same"),
                                      FetchResult([listing(vin=vin(900), price=58500)], True, "same")])
    pipeline.run_search(conn, [adapter], {})
    pipeline.run_search(conn, [adapter], {})
    first = render_app()
    second = render_app()
    assert first.dataframe[0].value.equals(second.dataframe[0].value)
    assert first.dataframe[0].value.iloc[0]["Change ($)"] == "-$1,500"
    assert first.dataframe[0].value.iloc[0]["Recorded"] == "Refresh"
    assert "Stale session summary" not in str([item.value for item in second.caption])
