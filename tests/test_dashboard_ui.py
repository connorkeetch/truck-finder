"""The overview is useful for a general vehicle search without fetching listings."""
import pytest

from conftest import listing
from rivian_finder import pipeline, queries
from rivian_finder.ui import common


def test_dashboard_uses_general_vehicle_summary_and_explains_saved_filters(conn, settings, monkeypatch):
    from streamlit.testing.v1 import AppTest

    settings["collection"].update(searches=[{"make": "Toyota", "model": "Camry"}],
                                  exclude_standard_range=False, excluded_trims={})
    pipeline.import_listings(conn, [listing(make="Toyota", model="Camry", trim="LE", price=25000)], "manual_entry")
    frame = queries.inventory_frame(conn, settings)
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common, "inventory", lambda *args: frame.copy())
    monkeypatch.setattr(common.services, "run_sources", lambda *args, **kwargs: pytest.fail("Dashboard must not search."))
    app = AppTest.from_string("from rivian_finder.ui.dashboard import render\nrender()").run(timeout=10)
    assert not app.exception
    assert "Favorites" in [item.label for item in app.metric]
    assert not any("Tonneau" in item.label for item in app.metric)
    assert [item.label for item in app.get("tab")] == ["Price", "Year", "Brand", "Model"]
    assert any("saved default filters" in item.value for item in app.caption)
    top = app.dataframe[0].value
    assert list(top.columns[:3]) == ["name", "price", "miles"]
    assert "Toyota Camry LE" in top.iloc[0]["name"]
    assert "battery" not in top and "tonneau" not in top and "photo" not in top
