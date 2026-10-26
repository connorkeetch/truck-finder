"""Hosted sessions require the proxy secret and keep separate database connections."""
import sqlite3
from types import SimpleNamespace

import pytest

from rivian_finder.ui import common


@pytest.mark.parametrize("expected,received,allowed", [
    ("", "", False), ("", "forged", False), ("proxy-secret", "", False),
    ("proxy-secret", "forged", False), ("proxy-secret", "proxy-secret", True),
])
def test_cloud_gate_requires_configured_secret_even_with_local_session_bypass(monkeypatch, expected, received, allowed):
    class Stop(Exception):
        pass

    monkeypatch.setenv("RIVIAN_FINDER_CLOUD", "1")
    monkeypatch.setenv("TRUCK_FINDER_PROXY_SECRET", expected)
    fake = SimpleNamespace(context=SimpleNamespace(headers={"X-Truck-Finder-Token": received,
                                                            "X-Truck-Finder-User": "owner"}, ip_address=None),
                           session_state={"remote_ok": True}, error=lambda message: None,
                           stop=lambda: (_ for _ in ()).throw(Stop()))
    monkeypatch.setattr(common, "st", fake)
    if allowed:
        common.remote_gate()
    else:
        with pytest.raises(Stop):
            common.remote_gate()


def test_cloud_connections_are_shared_only_within_one_browser_session(monkeypatch):
    from streamlit.testing.v1 import AppTest

    opened = []

    def connect(*args):
        c = sqlite3.connect(":memory:", check_same_thread=False)
        opened.append(c)
        return c

    monkeypatch.setenv("RIVIAN_FINDER_CLOUD", "1")
    monkeypatch.setattr(common.db, "connect", connect)
    source = """
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx
from rivian_finder.ui import common
# AppTest uses a fixed session ID; emulate two real browser sessions explicitly.
get_script_run_ctx().session_id = SESSION_ID
first = common.conn()
assert first is common.conn()
st.session_state['connection_id'] = id(first)
"""
    first = AppTest.from_string(source.replace("SESSION_ID", repr("cloud-browser-one"))).run(timeout=10)
    second = AppTest.from_string(source.replace("SESSION_ID", repr("cloud-browser-two"))).run(timeout=10)
    assert not first.exception and not second.exception
    assert first.session_state["connection_id"] != second.session_state["connection_id"]


def test_cloud_does_not_start_local_capture_receiver(monkeypatch):
    monkeypatch.setenv("RIVIAN_FINDER_CLOUD", "1")
    monkeypatch.setattr(common, "CaptureServer", lambda *args: pytest.fail("Cloud must not start capture receiver"))
    common.capture_server.clear()
    assert common.capture_server() is None
    common.capture_server.clear()
