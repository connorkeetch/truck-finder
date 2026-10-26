"""Hosted settings expose only actions that work without a desktop or local credential store."""
import copy

import pandas as pd
import pytest

from rivian_finder import backup, db
from rivian_finder.ui import common, settings_page, sources


@pytest.fixture
def cloud_ui(conn, settings, monkeypatch):
    monkeypatch.setenv("RIVIAN_FINDER_CLOUD", "1")
    monkeypatch.setenv("TZ", "America/Denver")
    monkeypatch.setenv("AUTODEV_API_KEY", "fictional-key-12345678")
    monkeypatch.delenv("MARKETCHECK_API_KEY", raising=False)
    settings["alerts"] = {"enabled": False, "times": ["08:00"]}
    settings["export"]["export_dir"] = r"C:\OldComputer\Exports"
    db.save_settings(conn, settings)
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: copy.deepcopy(db.load_settings(conn)))
    monkeypatch.setattr(common, "inventory", lambda *args: pd.DataFrame())
    monkeypatch.setattr(common, "save_settings", lambda value: db.save_settings(conn, value))
    monkeypatch.setattr(common, "capture_server", lambda: pytest.fail("Cloud pages cannot start a capture receiver"))
    monkeypatch.setattr(common, "reset_connection", lambda: pytest.fail("Cloud pages cannot replace the active database"))
    monkeypatch.setattr(settings_page.services, "available_sources", lambda c: [])
    monkeypatch.setattr(settings_page.services, "run_sources", lambda *args, **kwargs: pytest.fail("Rendering must not search"))
    for name in ("create_commands", "supported", "installed", "install", "remove"):
        monkeypatch.setattr(settings_page.scheduler, name, lambda *args: pytest.fail("Cloud settings cannot use the OS scheduler"))
    for name in ("get_api_key", "save_api_key", "delete_api_key"):
        monkeypatch.setattr(settings_page.credentials, name, lambda *args: pytest.fail("Cloud settings cannot use the OS credential store"))
    monkeypatch.setattr(settings_page.notifier, "notify", lambda *args: pytest.fail("Cloud settings cannot send desktop notifications"))
    monkeypatch.setattr(settings_page.access, "load", lambda: pytest.fail("Cloud settings cannot read the LAN PIN"))
    monkeypatch.setattr(backup, "restore_db", lambda *args: pytest.fail("Live cloud restore is disabled"))
    return conn


def render(module="settings_page"):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(f"from rivian_finder.ui.{module} import render\nrender()").run(timeout=10)
    assert not app.exception
    return app


def button(app, label):
    return next(element for element in app.button if element.label == label)


def test_cloud_settings_mask_environment_keys_and_remove_desktop_controls(cloud_ui):
    app = render()
    assert any(tab.label == "Cloud access" for tab in app.tabs)
    assert not any(tab.label == "Phone access" for tab in app.tabs)
    assert not any("PIN" in widget.label or "API key" in widget.label for widget in app.text_input)
    assert not any("credential store" in widget.label or "test notification" in widget.label for widget in app.button)
    content = "\n".join(item.value for item in app.markdown)
    assert "Railway" in content and "fict…78" in content
    assert "fictional-key-12345678" not in content
    assert any("private hosted URL" in item.value for item in app.markdown)
    assert any("America/Denver" in item.value for item in app.caption)


def test_cloud_schedule_saves_enabled_and_times_without_running_a_search(cloud_ui):
    app = render()
    app.toggle(key="cloud_alert_enabled").set_value(True)
    app.text_input(key="cloud_alert_times").set_value("15:30, 08:00, 15:30")
    button(app, "Save scheduled search settings").click().run(timeout=10)
    assert not app.exception
    saved = db.load_settings(cloud_ui)["alerts"]
    assert saved["enabled"] is True and saved["times"] == ["08:00", "15:30"]
    app.toggle(key="cloud_alert_enabled").set_value(False)
    button(app, "Save scheduled search settings").click().run(timeout=10)
    assert db.load_settings(cloud_ui)["alerts"]["enabled"] is False
    assert any("phone push" in item.value for item in app.markdown)


def test_invalid_cloud_times_cannot_be_enabled_but_schedule_can_be_disabled(cloud_ui):
    app = render()
    app.toggle(key="cloud_alert_enabled").set_value(True)
    app.text_input(key="cloud_alert_times").set_value("25:00").run(timeout=10)
    assert app.error and button(app, "Save scheduled search settings").disabled
    assert db.load_settings(cloud_ui)["alerts"]["enabled"] is False
    app.toggle(key="cloud_alert_enabled").set_value(False).run(timeout=10)
    assert not button(app, "Save scheduled search settings").disabled
    button(app, "Save scheduled search settings").click().run(timeout=10)
    assert db.load_settings(cloud_ui)["alerts"]["times"] == ["08:00"]


def test_cloud_exports_use_managed_folder_and_restore_is_disabled(cloud_ui):
    backup.backup_db(cloud_ui)
    app = render()
    assert button(app, "Restore selected backup").disabled
    assert not any("Also save exports to folder" in widget.label for widget in app.text_input)
    assert any("managed data folder" in item.value for item in app.caption)
    assert any("server maintenance" in item.value for item in app.info)
    assert any(element.proto.label == "Download selected database backup" for element in app.get("download_button"))
    button(app, "Save export settings").click().run(timeout=10)
    assert not app.exception and db.load_settings(cloud_ui)["export"]["export_dir"] == ""


def test_cloud_sources_keep_paste_and_explain_local_extension_without_receiver(cloud_ui):
    app = render("sources")
    assert not any("Capture receiver could not start" in item.value for item in app.warning)
    assert any("Copy for pasting" in item.value for item in app.info)
    assert any(tab.label == "Paste from a listing" for tab in app.tabs)
    assert app.text_area


def test_local_sources_keep_receiver_and_extension_instructions(cloud_ui, monkeypatch):
    monkeypatch.delenv("RIVIAN_FINDER_CLOUD", raising=False)
    receivers = []

    def receiver():
        receivers.append(True)
        return type("Receiver", (), {"port": 8765})()

    monkeypatch.setattr(common, "capture_server", receiver)
    app = render("sources")
    assert receivers == [True]
    assert any("Receiver running on http://127.0.0.1:8765" in item.value for item in app.success)
    assert any("Load unpacked" in item.value for item in app.markdown)


def test_local_phone_settings_keep_pin_controls(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("RIVIAN_FINDER_CLOUD", raising=False)
    monkeypatch.setattr(settings_page.access, "load", lambda: {"lan": False, "pin_hash": None})
    monkeypatch.setattr(settings_page.access, "lan_ips", lambda: [])
    app = AppTest.from_string("from rivian_finder.ui.settings_page import phone_settings\nphone_settings()").run(timeout=10)
    assert not app.exception and any("PIN" in widget.label for widget in app.text_input)
