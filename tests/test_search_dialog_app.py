"""Streamlit interaction smoke tests; all search services are stubbed, so no API calls occur."""
import pytest

from rivian_finder.ui import common
from rivian_finder.sources.base import SUPPORTED_BRANDS


@pytest.fixture
def app(monkeypatch):
    from streamlit.testing.v1 import AppTest
    calls = []
    monkeypatch.setattr(common, "conn", lambda: "connection")
    monkeypatch.setattr(common, "settings", lambda: {"collection": {"searches": None}})

    def run(conn, keys, settings, *, brands):
        calls.append((keys, brands))
        return {"status": "success", "text": "Search completed"}

    monkeypatch.setattr(common.services, "run_sources", run)
    app = AppTest.from_string("""
import streamlit as st
from rivian_finder.ui import common
if st.button('Run Search', key='open'):
    common.search_dialog()
if st.button('Run one connector', key='one'):
    common.search_dialog(['autodev'])
""").run(timeout=10)
    assert not app.exception
    return app, calls


def test_popup_opens_without_searching_and_cancel_closes(app):
    app, calls = app
    app.button(key="open").click().run(timeout=10)
    assert not app.exception
    assert app.multiselect(key="search_brands").value == ["Rivian"]
    assert calls == []
    app.button(key="search_cancel").click().run(timeout=10)
    assert not app.exception
    assert calls == []
    assert not app.multiselect


def test_clearing_selection_disables_start(app):
    app, calls = app
    app.button(key="open").click().run(timeout=10)
    app.multiselect(key="search_brands").set_value([])
    # AppTest reruns the full script for dialog inputs; keep its opener triggered for that run.
    app.button(key="open").click().run(timeout=10)
    assert not app.exception
    assert app.button(key="search_start").disabled
    assert calls == []


@pytest.mark.parametrize("opener,selected,expected,keys", [
    ("open", ["Ford", "GMC"], ["Ford", "GMC"], None),
    ("one", ["All brands"], list(SUPPORTED_BRANDS), ["autodev"]),
])
def test_submit_honors_brand_and_connector_choices(app, opener, selected, expected, keys):
    app, calls = app
    app.button(key=opener).click().run(timeout=10)
    app.multiselect(key="search_brands").set_value(selected)
    assert calls == []
    app.button(key=opener).click()
    app.button(key="search_start").click().run(timeout=10)
    assert not app.exception
    assert calls == [(keys, expected)]
    assert app.session_state["last_search_brands"] == expected
    assert app.session_state["last_summary"]["text"] == "Search completed"
    assert not app.multiselect
    app.button(key=opener).click().run(timeout=10)
    assert app.multiselect(key="search_brands").value == expected
    assert calls == [(keys, expected)]
