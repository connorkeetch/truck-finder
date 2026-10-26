"""Refresh badges stay separate from equipment warnings and safe in the card HTML."""
from html.parser import HTMLParser
import json
import shutil
import subprocess

import pandas as pd
import pytest

from rivian_finder.ui import cards


def _payload(**fields):
    row = {"vehicle_id": 1, "make": "Ford", "model": "F-150 Lightning", "year": 2024,
           "price": 50000, "your_price": 50000, "miles": 10000, **fields}
    return cards.payload(pd.DataFrame([row]), set(), {})[0]


@pytest.mark.parametrize("fields", [
    {},
    {"refresh_badges": [], "refresh_note": ""},
    {"refresh_badges": None, "refresh_note": None},
    {"refresh_badges": float("nan"), "refresh_note": float("nan")},
    {"refresh_badges": [{"text": float("nan"), "kind": "new", "detail": float("nan")}]},
])
def test_refresh_metadata_is_strict_json_with_missing_values(fields):
    card = _payload(**fields)
    json.dumps(card, allow_nan=False)
    assert isinstance(card["refresh_badges"], list)
    assert card["refresh_note"] == ""


@pytest.mark.skipif(not shutil.which("node"), reason="HTML check uses an existing Node runtime.")
def test_refresh_badges_render_prominently_with_escaped_details():
    labels = [
        ("new", "New"), ("new_source", "New source"), ("price_down", "Price down $1,500"),
        ("price_up", "Price up $250"), ("price", "Price changed"),
        ("removed", "Source removed"), ("missing", "Not seen"),
    ]
    detail = 'MarketCheck <source> & "quoted"; not confirmation of a sale'
    unsafe = 'New <script>alert("x")</script>'
    card = _payload(refresh_badges=[{"kind": kind, "text": text, "detail": detail} for kind, text in labels]
                    + [{"kind": 'new" onclick="bad()', "text": unsafe, "detail": detail}],
                    refresh_note='Source <snapshot> & "notes"', title_status="branded")
    js = cards.JS.replace("__ICONS__", json.dumps(cards.ICONS)).replace(
        "export default function (component)", "function mount(component)")
    program = js + "\nconst root = {style:{setProperty(){}}};\nmount({data:{cards:" + json.dumps([card]) + """},
      parentElement:{querySelector(){return root;}}, setTriggerValue(){}});
console.log(JSON.stringify(root.innerHTML));
"""
    result = subprocess.run([shutil.which("node"), "--input-type=module"], input=program,
                            text=True, encoding="utf-8", capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    html = json.loads(result.stdout)

    class Tags(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags = []

        def handle_starttag(self, tag, attrs):
            self.tags.append((tag, dict(attrs)))

    parsed = Tags()
    parsed.feed(html)
    badges = [attrs for tag, attrs in parsed.tags if tag == "span" and "refresh-" in attrs.get("class", "")]
    assert len(badges) == 8
    assert [b["class"] for b in badges[:7]] == [f"chip refresh-{kind}" for kind, _ in labels]
    assert badges[-1]["class"] == "chip refresh-note"
    assert all(b["title"] == detail and b["role"] == "note" for b in badges)
    assert badges[2]["aria-label"] == f"Price down $1,500: {detail}"
    assert not any(tag == "script" or "onclick" in attrs for tag, attrs in parsed.tags)
    assert "New &lt;script&gt;" in html and "Source &lt;snapshot&gt; &amp; &quot;notes&quot;" in html
    assert html.index('class="title"') < html.index('class="chips refresh"') < html.index('class="price"')
    assert html.index('class="chips refresh"') < html.index("Branded title")


@pytest.mark.skipif(not shutil.which("node"), reason="HTML check uses an existing Node runtime.")
def test_unchanged_cards_do_not_add_an_empty_badge_row():
    js = cards.JS.replace("__ICONS__", json.dumps(cards.ICONS)).replace(
        "export default function (component)", "function mount(component)")
    program = js + "\nconst root = {style:{setProperty(){}}};\nmount({data:{cards:" + json.dumps([_payload()]) + """},
      parentElement:{querySelector(){return root;}}, setTriggerValue(){}});
console.log(JSON.stringify(root.innerHTML));
"""
    result = subprocess.run([shutil.which("node"), "--input-type=module"], input=program,
                            text=True, encoding="utf-8", capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'class="chips refresh"' not in json.loads(result.stdout)
