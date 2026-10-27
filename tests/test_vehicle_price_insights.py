"""The full details page exposes the saved price analysis without fetching listings."""
import pytest

from conftest import AttributeClaim, listing, vin
from rivian_finder import attributes, pipeline, queries
from rivian_finder.ui import common


def test_details_page_includes_price_drop_patterns(conn, settings, monkeypatch):
    from streamlit.testing.v1 import AppTest

    pipeline.import_listings(conn, [listing(vin=vin(930), price=59000,
                                           attributes=[AttributeClaim("battery", "Large", "medium", "listing")])],
                             "manual_entry")
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    attributes.set_override(conn, vid, "battery", "Max", "Window sticker")
    attributes.set_override(conn, vid, "title_status", "branded")
    attributes.set_override(conn, vid, "accident_history", "reported")
    frame = queries.inventory_frame(conn, settings)
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common, "inventory", lambda *args: frame.copy())
    monkeypatch.setattr(common.services, "run_sources", lambda *args, **kwargs: pytest.fail("Details must not search."))
    app = AppTest.from_string("from rivian_finder.ui.vehicle import render\nrender()").run(timeout=10)
    assert not app.exception
    assert any(item.label == "Price history" for item in app.get("tab"))
    assert any(item.value == "Price-drop patterns" for item in app.subheader)
    assert [item.label for item in app.metric][:3] == ["Price", "Mileage", "Distance"]
    tabs = {item.label: item for item in app.get("tab")}
    assert [item.label for item in tabs["Overview"].get("metric")] == ["Personal score"]
    assert [item.label for item in tabs["Financing"].get("metric")] == ["Est. monthly", "Cash for target payment"]
    assert any(item.label == "Deal rating & negotiation" for item in tabs["Price history"].get("expander"))
    assert any(item.key == f"qv_isd_{vid}" for item in tabs["Verify equipment"].get("date_input"))
    assert any("Branded title · Accident reported" in item.value for item in app.warning)
    assert any("Sources disagree: Battery" in item.value for item in app.warning)
    notes = next(item for item in tabs["Notes & checklist"].get("text_area") if item.label == "📝 Notes")
    notes.set_value("Called the seller; request repair records.").run(timeout=10)
    assert not app.exception
    assert conn.execute("SELECT notes FROM vehicles WHERE id=?", (vid,)).fetchone()[0] == "Called the seller; request repair records."
