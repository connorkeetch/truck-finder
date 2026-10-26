"""The full details page exposes the saved price analysis without fetching listings."""
import pytest

from conftest import listing, vin
from rivian_finder import pipeline, queries
from rivian_finder.ui import common


def test_details_page_includes_price_drop_patterns(conn, settings, monkeypatch):
    from streamlit.testing.v1 import AppTest

    pipeline.import_listings(conn, [listing(vin=vin(930), price=59000)], "manual_entry")
    frame = queries.inventory_frame(conn, settings)
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common, "inventory", lambda *args: frame.copy())
    monkeypatch.setattr(common.services, "run_sources", lambda *args, **kwargs: pytest.fail("Details must not search."))
    app = AppTest.from_string("from rivian_finder.ui.vehicle import render\nrender()").run(timeout=10)
    assert not app.exception
    assert any(item.label == "Price history" for item in app.get("tab"))
    assert any(item.value == "Price-drop patterns" for item in app.subheader)
