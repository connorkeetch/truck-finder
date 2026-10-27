"""Quick verification changes only the facts the user explicitly confirms."""
from datetime import date

import pytest
import requests

from conftest import AttributeClaim, listing
from rivian_finder import attributes, pipeline, queries
from rivian_finder.ui import common


@pytest.fixture
def quick_verify_app(conn, settings, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "inventory", lambda: queries.inventory_frame(conn, settings))
    monkeypatch.setattr(requests.Session, "request", lambda *args, **kwargs: pytest.fail("Verification must stay offline."))

    def run(make="Rivian", tonneau="yes"):
        pipeline.import_listings(conn, [listing(make=make, model="R1T" if make == "Rivian" else "Camry",
                                               attributes=[AttributeClaim("tonneau", tonneau, "medium", "listing")])],
                                 "manual_entry")
        app = AppTest.from_string("""
from rivian_finder.ui import common
from rivian_finder.ui.vehicle import quick_verify
row = common.inventory().iloc[0]
quick_verify(common.conn(), int(row['vehicle_id']), row)
""").run(timeout=10)
        assert not app.exception
        return app, conn.execute("SELECT id FROM vehicles").fetchone()[0]

    return run


def save(app):
    next(button for button in app.button if button.label == "Save").click().run(timeout=10)
    assert not app.exception


@pytest.mark.parametrize("make", ["Rivian", "Toyota"])
@pytest.mark.parametrize("tonneau", ["yes", "no", "unknown"])
def test_saving_only_date_keeps_tonneau_as_a_source_claim(quick_verify_app, conn, make, tonneau):
    app, vid = quick_verify_app(make, tonneau)
    app.date_input(key=f"qv_isd_{vid}").set_value(date(2024, 1, 1))
    save(app)
    assert conn.execute("SELECT value FROM user_overrides WHERE vehicle_id=? AND field='tonneau'", (vid,)).fetchone() is None
    resolved = attributes.resolve(conn, vid)
    assert resolved["tonneau"].value == tonneau
    assert resolved["tonneau"].confidence == "medium"
    assert resolved["in_service_date"].value == "2024-01-01"
    assert resolved["in_service_date"].confidence == "verified"


@pytest.mark.parametrize("confirmed", ["yes", "no"])
def test_explicit_tonneau_verification_survives_other_edits_and_can_return_to_sources(quick_verify_app, conn, confirmed):
    app, vid = quick_verify_app(tonneau="no" if confirmed == "yes" else "yes")
    source_value = attributes.resolve(conn, vid)["tonneau"].value
    app.selectbox(key=f"qv_ton_{vid}").set_value(confirmed)
    save(app)
    resolved = attributes.resolve(conn, vid)["tonneau"]
    assert resolved.value == confirmed and resolved.confidence == "verified"

    app.date_input(key=f"qv_isd_{vid}").set_value(date(2024, 1, 1))
    save(app)
    resolved = attributes.resolve(conn, vid)["tonneau"]
    assert resolved.value == confirmed and resolved.confidence == "verified"

    app.selectbox(key=f"qv_ton_{vid}").set_value("As listed")
    save(app)
    resolved = attributes.resolve(conn, vid)["tonneau"]
    assert resolved.value == source_value and resolved.confidence == "medium"
    assert conn.execute("SELECT COUNT(*) FROM user_overrides WHERE vehicle_id=? AND field='tonneau'", (vid,)).fetchone()[0] == 0
