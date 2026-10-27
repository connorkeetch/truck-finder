"""A saved vehicle without a price leaves the standalone calculator usable."""
import pytest

from conftest import listing
from rivian_finder import pipeline, queries
from rivian_finder.ui import common


@pytest.mark.parametrize("price", [None, 0])
def test_unpriced_inventory_does_not_break_financing(conn, settings, monkeypatch, price):
    from streamlit.testing.v1 import AppTest

    settings["collection"].update(searches=[{"make": "Toyota", "model": "Camry"}],
                                  exclude_standard_range=False, excluded_trims={})
    pipeline.import_listings(conn, [listing(make="Toyota", model="Camry", price=price)], "manual_entry")
    frame = queries.inventory_frame(conn, settings)
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common, "inventory", lambda *args: frame.copy())
    app = AppTest.from_string("from rivian_finder.ui.finance_page import render\nrender()").run(timeout=10)
    assert not app.exception
    assert any("need a price" in item.value for item in app.info)
    assert len(app.dataframe) == 1
    assert any("Loan assumptions" in item.value for item in app.caption)
