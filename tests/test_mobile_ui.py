"""Mobile layout contracts and accessible card actions, without provider calls or new dependencies."""
import json
from html.parser import HTMLParser
import shutil
import subprocess

import pytest
import streamlit as st

from conftest import listing, vin
from rivian_finder import compare, pipeline, queries
from rivian_finder.ui import cards, common, compare_page, inventory


def test_cards_can_shrink_and_stack_on_phone_screens():
    assert "minmax(min(100%, var(--card-min, 540px)), 1fr)" in cards.CSS
    phone = cards.CSS.split("@media (max-width:640px)")[1]
    assert "grid-template-columns:minmax(0, 1fr)" in phone
    assert "flex-direction:column" in phone
    assert "width:100%" in phone and "aspect-ratio:4 / 3" in phone
    assert "white-space:normal" in phone and "overflow-wrap:anywhere" in phone
    assert "width:44px; height:44px" in cards.CSS
    assert "min-width:44px; min-height:44px" in cards.CSS
    assert ".links a, .links button { display:inline-flex; align-items:center; min-width:44px; min-height:44px" in cards.CSS
    assert "button:focus-visible" in cards.CSS


@pytest.mark.skipif(not shutil.which("node"), reason="Optional JavaScript behavior check uses an existing Node runtime.")
def test_native_card_buttons_preserve_events_and_accessible_state():
    js = cards.JS.replace("__ICONS__", json.dumps(cards.ICONS)).replace("export default function (component)", "function mount(component)")
    program = js + r'''
const root = { style: { setProperty() {} } };
const events = [];
const name = '2024 Ford <Lightning> "Lariat"';
mount({data: {cards: [{vid: 9, title: name, fav: false, selected: false}]},
  parentElement: {querySelector() {return root;}}, setTriggerValue(key, value) {events.push({key, ...value});}});
function classes() {
  const values = new Set();
  return {contains(value) {return values.has(value);}, toggle(value, enabled) {enabled ? values.add(value) : values.delete(value);}};
}
const cardRoot = {dataset: {vid: '9', name}, classList: classes()};
function button(action) {
  return {tagName: 'BUTTON', dataset: {act: action}, classList: classes(), attributes: {},
    setAttribute(key, value) {this.attributes[key] = value;},
    closest(selector) {return selector === '[data-act]' ? this : selector === '.card' ? cardRoot : null;}};
}
const toggle = button('toggle'), favorite = button('fav'), open = button('open');
for (const target of [toggle, favorite, open]) root.onclick({target, stopPropagation() {}});
console.log(JSON.stringify({html: root.innerHTML, events, toggle: toggle.attributes, favorite: favorite.attributes}));
'''
    result = subprocess.run([shutil.which("node"), "--input-type=module"], input=program, text=True,
                            encoding="utf-8", capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    class Controls(HTMLParser):
        def __init__(self):
            super().__init__()
            self.controls = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "data-act" in attrs:
                self.controls.append((tag, attrs))

    parsed = Controls()
    parsed.feed(data["html"])
    assert len(parsed.controls) == 5
    assert all(tag == "button" and attrs["type"] == "button" for tag, attrs in parsed.controls)
    selection = next(attrs for _, attrs in parsed.controls if attrs["data-act"] == "toggle")
    assert selection["role"] == "checkbox" and selection["aria-checked"] == "false"
    assert "Ford <Lightning>" in selection["aria-label"]
    assert data["toggle"]["aria-checked"] == "true"
    assert data["favorite"]["aria-pressed"] == "true"
    assert data["favorite"]["aria-label"].startswith("Remove 2024 Ford")
    assert [event["kind"] for event in data["events"]] == ["toggle", "fav", "open"]
    assert all(event["vid"] == 9 and event["key"] == "action" for event in data["events"])
    assert data["events"][0]["on"] is True and data["events"][1]["on"] is True


def test_inventory_selection_actions_and_refresh_are_available_outside_sidebar(conn, settings, monkeypatch):
    from streamlit.testing.v1 import AppTest
    pipeline.import_listings(conn, [listing(vin=vin(920)), listing(vin=vin(921))], "manual_entry")
    frame = queries.inventory_frame(conn, settings)
    ids = frame["vehicle_id"].astype(int).tolist()
    refreshes = []
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common, "inventory", lambda *args: frame.copy())
    monkeypatch.setattr(common, "photo_size_control", lambda *args: "S")
    monkeypatch.setattr(common, "search_dialog", lambda: refreshes.append("open"))
    monkeypatch.setattr(inventory.add_truck, "add_truck_panel", lambda *args: None)
    monkeypatch.setattr(inventory.refresh_changes, "render", lambda *args: None)
    monkeypatch.setattr(inventory, "adjustments_editor", lambda *args: None)
    monkeypatch.setattr(inventory.cards, "render", lambda *args: None)
    monkeypatch.setattr(inventory.services, "run_sources", lambda *args, **kwargs: pytest.fail("Rendering must not search."))
    app = AppTest.from_string(f"""
import streamlit as st
from rivian_finder.ui import inventory
st.session_state.setdefault('inv_selected', set({ids!r}))
st.session_state['_actions_box'] = st.sidebar.container()
inventory.render()
""").run(timeout=10)
    assert not app.exception
    assert app.main.button(key="inv_sel_cmp").disabled is False
    assert app.main.button(key="inv_sel_clear")
    assert not app.sidebar.button
    app.button(key="inv_refresh").click().run(timeout=10)
    assert not app.exception and refreshes == ["open"]


def test_compact_comparison_shortens_matrix_without_changing_prices(conn, settings, monkeypatch):
    from streamlit.testing.v1 import AppTest
    pipeline.import_listings(conn, [listing(vin=vin(922), price=58000), listing(vin=vin(923), price=61000)], "manual_entry")
    frame = queries.inventory_frame(conn, settings)
    ids = frame["vehicle_id"].astype(int).tolist()
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: settings)
    monkeypatch.setattr(common, "inventory", lambda: frame)
    monkeypatch.setattr(common, "photo_image", lambda *args: None)
    monkeypatch.setattr(compare_page, "payments_section", lambda *args: st.caption("Payment details"))
    before = conn.total_changes
    app = AppTest.from_string(f"""
from rivian_finder.ui import common, compare_page
compare_page.render_compare(common.inventory(), {ids!r})
""").run(timeout=10)
    assert not app.exception
    full = app.dataframe[0].value.copy()
    assert len(full) == len(compare.ROWS)
    app.toggle(key="compare_compact").set_value(True).run(timeout=10)
    assert not app.exception
    compact = app.dataframe[0].value
    assert len(compact) <= 14 < len(full)
    assert compact.loc["Price"].equals(full.loc["Price"])
    assert "My requirements" in compact.index and "Tow confidence" in compact.index
    assert any(expander.label == "Payment scenarios" for expander in app.expander)
    assert conn.total_changes == before
