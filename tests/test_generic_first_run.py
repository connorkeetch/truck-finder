"""A fresh workspace opens without keys, listing requests, or existing private inventory."""
from pathlib import Path

import requests

from rivian_finder import config, credentials, db
from rivian_finder.ui import common


def test_fresh_inventory_and_settings_open_without_provider_calls(conn, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "capture_server", lambda: None)
    monkeypatch.setattr(common, "_upgrade_thumbs", lambda: 0)
    monkeypatch.setattr(common, "_setup_logging", lambda: True)
    monkeypatch.setattr(credentials, "get_api_key", lambda key: (None, "not configured"))

    def no_network(*args, **kwargs):
        raise AssertionError("Opening the app must not query a provider")

    monkeypatch.setattr(requests.Session, "request", no_network)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=20)
    assert not app.exception
    assert db.load_settings(conn)["collection"]["searches"] == config.default_settings()["collection"]["searches"]
    assert conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 0
    app = AppTest.from_string("from rivian_finder.ui.settings_page import render\nrender()").run(timeout=20)
    assert not app.exception
    assert app.checkbox(key="collection_custom_searches").value
    assert app.number_input(key="collection_max_distance").value == 0
    assert conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0] == 0
