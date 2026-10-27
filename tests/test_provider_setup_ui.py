"""Provider setup explains access clearly and never spends API calls while saving configuration."""
import urllib.request

import pytest
import requests

from rivian_finder import cloud, credentials, db, queries, services
from rivian_finder.ui import common, inventory, settings_page


@pytest.fixture
def setup_ui(conn, monkeypatch):
    from streamlit.testing.v1 import AppTest

    writes = []

    class Keyring:
        def get_password(self, *args):
            return None

        def set_password(self, *args):
            writes.append(args)

        def delete_password(self, *args):
            pytest.fail("Tests must not remove credentials")

    def no_network(*args, **kwargs):
        pytest.fail("Setup must not call a provider or external service")

    for name in credentials.KEYS.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(credentials, "_keyring", lambda: Keyring())
    monkeypatch.setattr(requests.Session, "request", no_network)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setattr(services, "run_sources", no_network)
    monkeypatch.setattr(services, "check_mailbox", no_network)
    monkeypatch.setattr(cloud, "is_cloud", lambda: False)
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "inventory", lambda s=None: queries.inventory_frame(conn, s or db.load_settings(conn)))
    monkeypatch.setattr(settings_page, "alert_settings", lambda *args: None)
    monkeypatch.setattr(settings_page, "phone_settings", lambda: None)

    def app(page):
        return AppTest.from_string(f"from rivian_finder.ui.{page} import render\nrender()").run(timeout=15)

    return app, writes


@pytest.mark.parametrize("page", ["settings_page", "sources"])
def test_provider_setup_has_official_links_and_marketcheck_key_instructions(setup_ui, page):
    make_app, _ = setup_ui
    app = make_app(page)
    assert not app.exception
    links = {element.proto.url for element in app.get("link_button")}
    assert {"https://www.auto.dev/signin", "https://www.auto.dev/dashboard",
            "https://developers.marketcheck.com/sign-up", "https://developers.marketcheck.com/api-keys"} <= links
    markdown = "\n".join(element.value for element in app.markdown)
    assert "https://docs.auto.dev/v2/getting-started" in markdown
    assert "https://docs.marketcheck.com/docs/get-started/api/authentication" in markdown
    assert "subscribe to an API package" in markdown
    assert "Copy the **API Key**" in markdown and "does not need the Client Secret" in markdown
    if page == "sources":
        assert any(expander.label == "Connect a provider and run your first search" for expander in app.expander)
        assert app.button(key="sources_setup_API credentials")
        assert app.button(key="sources_setup_Collection scope")


def _save_key(app, provider):
    return next(button for button in app.button if button.label == "Save to OS credential store"
                and button.proto.form_id == f"key_{provider}")


@pytest.mark.parametrize("provider", ["autodev", "marketcheck"])
def test_blank_api_key_never_writes_to_credential_store(setup_ui, provider):
    make_app, writes = setup_ui
    app = make_app("settings_page")
    assert not app.exception
    app.text_input(key=f"k_{provider}").set_value("   ")
    _save_key(app, provider).click().run(timeout=15)
    assert not app.exception
    assert any("Paste an API Key before saving" in error.value for error in app.error)
    assert writes == []


def test_saving_key_warns_when_environment_takes_priority_without_provider_calls(conn, setup_ui, monkeypatch):
    make_app, writes = setup_ui
    monkeypatch.setenv("MARKETCHECK_API_KEY", "fictional-environment-key")
    app = make_app("settings_page")
    app.text_input(key="k_marketcheck").set_value("fictional-saved-key")
    _save_key(app, "marketcheck").click().run(timeout=15)
    assert not app.exception
    assert writes == [(credentials.SERVICE, "MARKETCHECK_API_KEY", "fictional-saved-key")]
    assert any("MARKETCHECK_API_KEY" in warning.value and "takes priority" in warning.value for warning in app.warning)
    assert conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0] == 0


def test_car_and_suv_examples_need_explicit_save_and_preserve_multiple_pairs(conn, setup_ui):
    make_app, _ = setup_ui
    before = db.load_settings(conn)
    app = make_app("settings_page")
    app.button(key="collection_general_presets").click().run(timeout=15)
    assert not app.exception
    expected = [{"make": "Toyota", "model": "Camry"}, {"make": "Honda", "model": "CR-V"},
                {"make": "Ford", "model": "Mustang Mach-E"}]
    assert settings_page.parse_searches(app.text_area(key="collection_searches_text").value) == expected
    assert db.load_settings(conn) == before
    next(button for button in app.button if button.label == "Save collection scope").click().run(timeout=15)
    assert not app.exception
    assert db.load_settings(conn)["collection"]["searches"] == expected
    reopened = make_app("settings_page")
    assert not reopened.exception
    assert settings_page.parse_searches(reopened.text_area(key="collection_searches_text").value) == expected


def test_onboarding_imports_cars_and_suvs_without_credentials_or_provider_calls(conn, setup_ui, monkeypatch):
    make_app, writes = setup_ui
    before = db.load_settings(conn)
    monkeypatch.setattr(inventory.cards, "render", lambda *args, **kwargs: None)
    app = make_app("inventory")
    assert not app.exception
    app.button(key="inv_try_demo").click().run(timeout=15)
    assert not app.exception
    pairs = {(row[0], row[1]) for row in conn.execute("SELECT make, model FROM vehicles WHERE is_demo=1")}
    assert {("Toyota", "Camry"), ("Honda", "CR-V"), ("Ford", "Mustang Mach-E")} <= pairs
    assert conn.execute("SELECT COUNT(*) FROM vehicles WHERE is_demo=0").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0] == 0
    assert writes == [] and db.load_settings(conn) == before


def test_selection_actions_stay_with_results_even_if_old_sidebar_container_exists(setup_ui):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string("""
import pandas as pd
import streamlit as st
from rivian_finder.ui import common
st.session_state['_actions_box'] = st.sidebar.container()
selected = pd.DataFrame([{'vehicle_id': i, 'favorite': False, 'hidden': False, 'sold_by': 'Example seller'}
                         for i in (1, 2)])
common.selection_actions(common.conn(), selected, 'setup_test')
""").run(timeout=15)
    assert not app.exception
    assert app.main.button(key="setup_test_cmp")
    assert app.main.button(key="setup_test_clear")
    assert not app.sidebar.button
