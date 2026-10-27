"""Refresh context and compact retirement history render without searches or writes."""
import copy

import pandas as pd
import pytest

from conftest import FakeAdapter, listing, vin
from rivian_finder import pipeline, queries
from rivian_finder.models import FetchResult
from rivian_finder.ui import common


def changes():
    base = {"created_at": "2026-10-25T12:05:00Z", "run_id": 2, "vehicle_id": 1, "listing_id": 1,
            "make": "Ford", "model": "F-150 Lightning", "trim": "Lariat", "year": 2023, "vin": "",
            "source": "Auto.dev", "seller_name": "Test dealer", "is_demo": False,
            "listing_status": "active", "update_origin": "Refresh", "new_value": None,
            "url": "https://dealer.example/ford"}
    return {"run": {"id": 2, "started_at": "2026-10-25T12:00:00Z", "status": "partial", "first_refresh": False,
                    "summary": {"sources": [{"source": "autodev", "name": "Auto.dev", "status": "success"},
                                               {"source": "marketcheck", "name": "MarketCheck", "status": "partial",
                                                "notes": ["Page cap reached.", "Collection scope changed; disappearance detection skipped."],
                                                "error": "Incomplete scan"}]}},
            "events": pd.DataFrame([
                {**base, "id": 1, "category": "new", "event_type": "new_source_for_vin"},
                {**base, "id": 2, "category": "price", "event_type": "price_drop"},
                {**base, "id": 3, "listing_id": 2, "vehicle_id": 2, "category": "removed", "event_type": "marked_removed",
                 "make": "Chevrolet", "model": "Silverado EV", "trim": "4WT", "listing_status": "removed",
                 "update_origin": "After refresh", "new_value": "Marked sold/removed by user",
                 "url": "https://dealer.example/chevy"},
                {**base, "id": 4, "listing_id": 3, "vehicle_id": 3, "category": "missing", "event_type": "disappeared",
                 "make": "GMC", "model": "Sierra EV", "trim": "Denali", "listing_status": "missing",
                 "url": "https://dealer.example/gmc"},
            ])}


def unavailable_rows(count=1):
    return pd.DataFrame([{"vehicle_id": n, "listing_id": 100 + n, "year": 2024, "make": "Ford",
                          "model": "F-150 Lightning", "trim": f"Archive {n}", "status": "removed",
                          "active_listings": 0, "source": "Auto.dev", "seller": "Archive dealer",
                          "is_demo": False, "last_seen": "2026-10-24T10:00:00Z", "hidden": True,
                          "status_reason": "Seller reported removal", "notes": "Keep this inspection note",
                          "url": f"https://dealer.example/archive/{n}"} for n in range(1, count + 1)])


@pytest.fixture
def render_app(monkeypatch, conn, settings):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common.services, "run_sources", lambda *args, **kwargs: pytest.fail("Rendering must not search."))
    monkeypatch.setattr(common, "save_settings", lambda *args: pytest.fail("Rendering must not save settings."))
    opened = []
    monkeypatch.setattr(common, "open_vehicle", opened.append)

    def run(result=None, inv=None, *, context_only=False):
        if result is not None:
            monkeypatch.setattr(queries, "refresh_changes", lambda c: copy.deepcopy(result))
        monkeypatch.setattr(common, "inventory", lambda s: inv.copy() if inv is not None else queries.inventory_frame(conn, s))
        script = """
import streamlit as st
from rivian_finder import queries
from rivian_finder.ui import common, refresh_changes
st.session_state['last_summary'] = {'text': 'Stale session summary'}
c, s = common.conn(), common.settings()
result = queries.refresh_changes(c)
refresh_changes.render(c, s, result=result)
"""
        if not context_only:
            script += "refresh_changes.render_retired(c, s, inv=common.inventory(s), result=result, key='test_retired')\n"
        before = conn.total_changes
        app = AppTest.from_string(script).run(timeout=10)
        assert not app.exception
        assert conn.total_changes == before
        app.opened_vehicles = opened
        return app

    return run


def text(app):
    return "\n".join(item.value for kind in (app.markdown, app.caption, app.info, app.warning) for item in kind)


def links(app):
    return {element.proto.url for element in app.get("link_button")}


def test_compact_context_has_no_title_metrics_tables_or_change_tabs(render_app):
    app = render_app(changes(), context_only=True)
    assert "Latest refresh:" in text(app) and "partial" in text(app)
    assert not app.title and not app.subheader and not app.metric and not app.dataframe and not app.tabs
    assert "Stale session summary" not in text(app)
    assert any("MarketCheck: partial" in item.value and "Incomplete scan" in item.value for item in app.warning)
    assert "disappearance detection skipped" in text(app)
    assert "Page cap reached" not in text(app)


@pytest.mark.parametrize("status", ["partial", "failed", "skipped"])
def test_all_incomplete_source_statuses_preserve_errors_and_coverage(render_app, status):
    result = changes()
    result["run"]["summary"]["sources"] = [{"name": "Source under test", "status": status, "error": "HTTP 503"}]
    app = render_app(result, context_only=True)
    assert f"Source under test: {status}" in text(app)
    assert any("HTTP 503" in item.value and "cannot be inferred" in item.value for item in app.warning)


def test_first_refresh_explains_baseline_without_a_change_table(render_app):
    result = changes()
    result["run"]["first_refresh"] = True
    app = render_app(result, context_only=True)
    assert any("establishes a baseline" in item.value for item in app.info)
    assert not app.dataframe and not app.tabs


def test_failed_first_refresh_never_claims_baseline_or_unchanged_inventory(render_app):
    result = changes()
    result["run"].update(first_refresh=True, status="failed")
    result["events"] = result["events"].iloc[:0]
    app = render_app(result, context_only=True)
    assert not app.info
    assert any("not confirmation" in item.value for item in app.warning)


def test_no_refresh_is_a_short_caption_and_discoverable_empty_history(render_app):
    app = render_app({"run": None, "events": pd.DataFrame()}, inv=pd.DataFrame())
    assert any("No refresh yet" in item.value for item in app.caption)
    assert app.expander[0].label == "Sold, removed & not seen (0)"
    assert not app.expander[0].proto.expanded
    assert "No sold, removed or missing" in text(app)
    assert not app.info and not app.dataframe


def test_preloaded_context_and_inventory_need_no_extra_connection_or_query(render_app, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(common, "conn", lambda: pytest.fail("Preloaded rendering must not open a connection."))
    monkeypatch.setattr(queries, "refresh_changes", lambda c: pytest.fail("Preloaded rendering must not query again."))
    app = AppTest.from_string("""
import pandas as pd
from rivian_finder.ui import common, refresh_changes
result = {'run': None, 'events': pd.DataFrame()}
refresh_changes.render(result=result)
refresh_changes.render_retired(s=common.settings(), inv=pd.DataFrame(), result=result)
""").run(timeout=10)
    assert not app.exception


def test_retired_source_links_ignore_all_filters_except_demo(render_app, settings):
    settings["filters"].update(brands=["Rivian"], max_price=1, favorites_only=True, include_missing=False,
                                hidden_only=False, show_demo=False)
    result = changes()
    demo = {**result["events"].iloc[2].to_dict(), "id": 5, "listing_id": 5, "vehicle_id": 5,
            "is_demo": True, "url": "https://demo.example/truck"}
    result["events"] = pd.concat([result["events"], pd.DataFrame([demo])], ignore_index=True)
    app = render_app(result, inv=pd.DataFrame())
    assert [tab.label for tab in app.tabs] == ["Recent status changes (2)", "All unavailable vehicles (0)"]
    assert links(app) == {"https://dealer.example/chevy", "https://dealer.example/gmc"}
    assert "Chevrolet Silverado EV 4WT" in text(app) and "GMC Sierra EV Denali" in text(app)
    assert "Sold or removed (reported)" in text(app) and "Not seen — sale unconfirmed" in text(app)
    assert "Current listing status: removed" in text(app) and "After refresh" in text(app)
    assert "Current availability has not been verified" in text(app)
    assert not app.button and not app.dataframe
    settings["filters"]["show_demo"] = True
    app = render_app(result, inv=pd.DataFrame())
    assert app.tabs[0].label == "Recent status changes (3)"
    assert "https://demo.example/truck" in links(app)
    assert "[DEMO]" in text(app)


def test_recent_history_deduplicates_latest_retirement_per_source_listing(render_app):
    result = changes()
    older = {**result["events"].iloc[2].to_dict(), "id": 0, "category": "missing",
             "event_type": "disappeared", "created_at": "2026-10-25T11:00:00Z", "new_value": "Older retirement"}
    same_truck_other_listing = {**result["events"].iloc[2].to_dict(), "id": 7, "listing_id": 7,
                               "source": "MarketCheck", "url": "https://other.example/same-truck"}
    result["events"] = pd.concat([pd.DataFrame([older]), result["events"], pd.DataFrame([same_truck_other_listing])], ignore_index=True)
    app = render_app(result, inv=pd.DataFrame())
    assert app.expander[0].label.endswith("(2)")  # Unique trucks, with three source-listing rows.
    assert app.tabs[0].label == "Recent status changes (3)"
    assert "Older retirement" not in text(app)
    assert "MarketCheck · Test dealer" in text(app)
    assert len(links(app)) == 3


def test_active_again_and_active_elsewhere_do_not_imply_unavailable_trucks(render_app):
    result = changes()
    result["events"].loc[result["events"]["listing_id"].eq(2), "listing_status"] = "active"
    inv = unavailable_rows(3)
    inv["active_listings"] = 1
    inv["status"] = "active"
    app = render_app(result, inv=inv)
    assert text(app).count("Active again") == 1
    assert text(app).count("Another source still lists this truck as active.") == 1
    assert app.tabs[1].label == "All unavailable vehicles (0)"
    assert len(app.button) == 2
    assert len({button.key for button in app.button}) == 2
    app.button(key="test_retired_event_2_3_open").click().run(timeout=10)
    assert not app.exception and app.opened_vehicles == [2]


def test_archive_keeps_hidden_trucks_notes_and_demo_preference(render_app, settings):
    inv = unavailable_rows(2)
    inv.loc[1, "is_demo"] = True
    inv.loc[0, "status"] = "missing"
    settings["filters"].update(brands=["Rivian"], max_price=1, favorites_only=True, show_demo=False)
    app = render_app({"run": None, "events": pd.DataFrame()}, inv=inv)
    assert [tab.label for tab in app.tabs] == ["All unavailable vehicles (1)", "Recent status changes (0)"]
    assert "Archive 1" in text(app) and "Archive 2" not in text(app)
    assert "Keep this inspection note" in text(app) and "Seller reported removal" in text(app)
    assert "Not seen — sale unconfirmed" in text(app)
    assert links(app) == {"https://dealer.example/archive/1"}
    assert len(app.button) == 1


def test_archive_renders_twenty_rows_then_show_more_without_writes(render_app, conn):
    app = render_app({"run": None, "events": pd.DataFrame()}, inv=unavailable_rows(23))
    assert app.tabs[0].label == "All unavailable vehicles (23)"
    assert len(links(app)) == 20 and "Archive 21" not in text(app)
    before = conn.total_changes
    app.button(key="test_retired_archive_more").click().run(timeout=10)
    assert not app.exception
    assert len(links(app)) == 23 and "Archive 23" in text(app)
    assert not any(button.label == "Show more" for button in app.button)
    assert conn.total_changes == before


def test_recent_status_changes_also_start_at_twenty_rows(render_app):
    result = changes()
    row = result["events"].iloc[2].to_dict()
    result["events"] = pd.DataFrame([{**row, "id": n, "listing_id": n, "vehicle_id": n,
                                      "url": f"https://dealer.example/recent/{n}"} for n in range(1, 24)])
    app = render_app(result, inv=pd.DataFrame())
    assert app.tabs[0].label == "Recent status changes (23)"
    assert len(links(app)) == 20
    app.button(key="test_retired_recent_more").click().run(timeout=10)
    assert not app.exception and len(links(app)) == 23


def test_unavailable_truck_survives_next_empty_refresh_and_new_session(render_app, conn, monkeypatch):
    monkeypatch.setattr(pipeline, "utcnow", lambda: "2026-10-25T12:00:00Z")
    adapter = FakeAdapter("autodev", [FetchResult([listing(vin=vin(900), trim="Saved truck")], True, "same"),
                                      FetchResult([], True, "same")])
    pipeline.run_search(conn, [adapter], {})
    lid = conn.execute("SELECT id FROM listings").fetchone()[0]
    monkeypatch.setattr(pipeline, "utcnow", lambda: "2026-10-25T12:01:00Z")
    pipeline.mark_removed(conn, lid, "User reported removed")
    conn.execute("UPDATE vehicles SET hidden_at='2026-10-25T12:00:00Z', notes='Remember my inspection'")
    first = render_app()
    assert first.tabs[0].label == "Recent status changes (1)"
    monkeypatch.setattr(pipeline, "utcnow", lambda: "2026-10-25T12:02:00Z")
    pipeline.run_search(conn, [adapter], {})
    second = render_app()
    third = render_app()
    assert second.tabs[0].label == "All unavailable vehicles (1)"
    assert second.tabs[1].label == "Recent status changes (0)"
    assert "Saved truck" in text(second) and "Remember my inspection" in text(second)
    assert text(second) == text(third)
    assert "Stale session summary" not in text(third)
