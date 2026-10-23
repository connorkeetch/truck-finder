"""A refresh waits for an explicit, nonempty brand choice; connector selection is preserved."""
from contextlib import nullcontext

import pytest

from rivian_finder.ui import common
from rivian_finder.sources.base import SUPPORTED_BRANDS


class Rerun(Exception):
    pass


class Dialog:
    def __init__(self, selected=None, action=None, previous=None):
        self.selected, self.action = selected, action
        self.session_state = {"last_search_brands": previous} if previous else {}
        self.disabled = {}

    def multiselect(self, label, options, default, **kwargs):
        return default if self.selected is None else self.selected

    def caption(self, *args):
        pass

    def info(self, *args):
        pass

    def columns(self, count):
        return [self] * count

    def button(self, label, key, disabled=False, **kwargs):
        self.disabled[key] = disabled
        return key == self.action

    def spinner(self, *args):
        return nullcontext()

    def rerun(self):
        raise Rerun()


def setup_dialog(monkeypatch, dialog):
    calls = []
    monkeypatch.setattr(common, "st", dialog)
    monkeypatch.setattr(common, "conn", lambda: "connection")
    monkeypatch.setattr(common, "settings", lambda: {"collection": {"searches": None}})

    def run(conn, keys, settings, *, brands):
        calls.append((conn, keys, settings, brands))
        return {"status": "success", "text": "Search completed"}

    monkeypatch.setattr(common.services, "run_sources", run)
    return calls


@pytest.mark.parametrize("previous", [None, ["Ford", "GMC"]])
def test_opening_picker_does_not_search(monkeypatch, previous):
    dialog = Dialog(previous=previous)
    calls = setup_dialog(monkeypatch, dialog)
    common.search_dialog.__wrapped__()
    assert calls == []
    assert not dialog.disabled["search_start"]


def test_cancel_does_not_search(monkeypatch):
    calls = setup_dialog(monkeypatch, Dialog(selected=["All brands"], action="search_cancel"))
    with pytest.raises(Rerun):
        common.search_dialog.__wrapped__()
    assert calls == []


def test_empty_selection_is_disabled_and_never_searches(monkeypatch):
    dialog = Dialog(selected=[], action="search_start")
    calls = setup_dialog(monkeypatch, dialog)
    common.search_dialog.__wrapped__()
    assert dialog.disabled["search_start"]
    assert calls == []


@pytest.mark.parametrize("selected,expected", [(["Ford"], ["Ford"]), (["Rivian", "GMC"], ["Rivian", "GMC"]),
                                              (["All brands"], list(SUPPORTED_BRANDS))])
@pytest.mark.parametrize("keys", [None, ["autodev"]])
def test_submit_refreshes_only_chosen_brands(monkeypatch, selected, expected, keys):
    dialog = Dialog(selected=selected, action="search_start")
    calls = setup_dialog(monkeypatch, dialog)
    with pytest.raises(Rerun):
        common.search_dialog.__wrapped__(keys)
    assert calls == [("connection", keys, {"collection": {"searches": None}}, expected)]
    assert dialog.session_state["last_search_brands"] == expected
    assert dialog.session_state["last_summary"]["text"] == "Search completed"
    assert dialog.session_state["_flash"] == [("success", "Search completed")]
