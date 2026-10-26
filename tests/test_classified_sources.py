"""KSL, RivianForums and Rivian Roamer: parsing what the user brings in, and never collecting what terms forbid."""
from pathlib import Path

import pytest

from conftest import vin
from rivian_finder import db, links, pipeline
from rivian_finder.extract import extract_attributes, identify_site, normalize_state, parse_seller_type
from rivian_finder.importers import capture, email_alerts, forum_listing

FIXTURES = Path(__file__).parent / "fixtures"
THREAD_URL = "https://www.rivianforums.com/forum/threads/utah-for-sale-2022-r1t-launch-green.59999/"


# ------------------------------------------------------------------ site recognition

@pytest.mark.parametrize("url, expected", [
    (THREAD_URL, ("rivianforums", "59999")),
    ("https://rivianforums.com/forum/threads/wtb-gen-1-r1t.44142/post-783566", ("rivianforums", "44142")),
    ("https://www.rivianforums.com/forum/threads/41933/unread", ("rivianforums", "41933")),
    ("https://www.rivianforums.com/forum/forums/rivians-vehicles-for-sale.62/", ("rivianforums", None)),
    ("https://rivianroamer.com/inventory/abc123", ("roamer", "abc123")),
    ("https://rivianroamer.com/inventory?condition=PRE_OWNED_VEHICLE", ("roamer", None)),
    ("https://rivian.com/configurations/list?INVENTORY_TYPE=PRE_OWNED_VEHICLE", ("rivian", None)),
])
def test_forum_and_roamer_urls_are_recognized(url, expected):
    assert identify_site(url) == expected


def test_forum_threads_are_seller_listings_and_roamer_is_an_aggregator():
    assert links.listing_role(THREAD_URL)[0] == "seller"
    assert links.listing_role("https://rivianroamer.com/inventory/abc123")[0] == "aggregator"


# ------------------------------------------------------------------ RivianForums titles and threads

@pytest.mark.parametrize("title, state, year, price, miles, status", [
    ("Texas - For Sale: 2022 R1T El Cap Granite w/ Forest Edge Interior, 26k miles; $56k, PENDING",
     "TX", 2022, 56000, 26000, "pending"),
    ("California - For Sale: 64K - Adventure-Ready 2022 Rivian R1T Adventure Edition - 20,500 Miles",
     "CA", 2022, 64000, 20500, None),
    ("Sold: Texas 2025 R1T Tri-Max, El Cap/Slate Sky, 12,7xx miles, $83,000", "TX", 2025, 83000, None, "sold"),
    ("Washington - WTB 2023 Large pack R1T around $52k", "WA", 2023, 52000, None, "wanted"),
    ("New Mexico - 2023 R1T Quad, looking for a quick sale $61,500", "NM", 2023, 61500, None, None),
    ("Arizona - For Sale: 2023 R1T Dual Large, 18k miles, $52.5k | Rivian Forum – R1T R1S R2 R3 News",
     "AZ", 2023, 52500, 18000, None),
])
def test_forum_title_parsing(title, state, year, price, miles, status):
    facts = forum_listing.parse_title(title)
    assert (facts["state"], facts["year"], facts["price"], facts["miles"], facts["status"]) == (
        state, year, price, miles, status)
    assert "Rivian Forum" not in facts["title"]


def test_two_bare_k_numbers_are_not_guessed_as_a_price():
    assert forum_listing.parse_title("Utah - 2023 R1T, 18K, asking 55K")["price"] is None


def test_pasted_thread_reads_title_and_first_post_only():
    text = (FIXTURES / "synthetic_rivianforums_thread.txt").read_text(encoding="utf-8")
    d = capture.draft_from_text(text, THREAD_URL)
    assert d["source"] == "rivianforums" and d["source_listing_id"] == "59999"
    assert d["vin"] == vin(4242, "N", "A")
    assert (d["year"], d["price"], d["miles"]) == (2022, 54500, 31000)    # title wins over the post's MSRP
    assert (d["city"], d["state"]) == ("Lehi", "UT")
    assert d["seller_type"] == "private" and d["seller_name"] == "trailrunner42 (RivianForums)"
    assert d["forum_status"] is None
    claims = {c.field: c.value for c in d["claims"]}
    assert claims["battery"] == "Large" and claims["motor"] == "Quad" and claims["tonneau"] == "yes"
    assert "49,900" not in d["description"] and "Max pack" not in d["description"]   # the reply is ignored


def test_highlighted_first_post_uses_the_browser_tab_title():
    d = capture.draft_from_text("Quad-Motor, Large pack. Clean title.", THREAD_URL,
                                title="Utah - For Sale: SOLD 2022 R1T, 31k miles; $54,500 | Rivian Forum – R1T R1S")
    assert d["forum_status"] == "sold" and d["price"] == 54500 and d["state"] == "UT"
    assert d["title"].startswith("Utah - For Sale")


def test_sold_forum_thread_can_be_recorded_as_sold(conn):
    d = capture.draft_from_text("Quad, Large pack.", THREAD_URL, title="Sold: Utah 2022 R1T, 31k miles, $54,500")
    nl = capture.listing_from_draft(d)
    summary = pipeline.import_listings(conn, [nl], "capture")
    pipeline.mark_removed(conn, summary["listing_ids"][0], "Forum thread is marked SOLD")
    row = conn.execute("SELECT status, status_reason, source_key FROM listings").fetchone()
    assert tuple(row) == ("removed", "Forum thread is marked SOLD", "rivianforums")


def test_forum_watched_thread_email():
    meta, found = email_alerts.parse_eml_bytes((FIXTURES / "synthetic_rivianforums_alert.eml").read_bytes())
    assert len(found) == 1                       # title and "View this thread" are one listing; forum links skipped
    nl = found[0]
    assert (nl.source_key, nl.source_listing_id) == ("rivianforums", "60001")
    assert nl.title.startswith("Arizona - For Sale: 2023 R1T")
    assert (nl.year, nl.price, nl.miles, nl.state) == (2023, 52500, 18000, "AZ")   # not the $79,800 MSRP
    assert nl.vin == vin(4243, "P", "B")
    assert nl.seller_type == "private" and nl.seller_name == "desertdriver (RivianForums)"
    assert email_alerts.worth_saving(nl)


def test_wanted_and_sold_forum_emails_start_unticked():
    html = ('<div><p>buyer9 started a new thread.</p><a href="https://www.rivianforums.com/forum/threads/wtb.70001/">'
            'Washington - WTB 2023 Large pack R1T around $52k</a></div>'
            '<div><p>seller7 started a new thread.</p><a href="https://www.rivianforums.com/forum/threads/x.70002/">'
            'Sold: Utah 2022 R1T Quad, 30k miles, $55,000</a></div>')
    found = {nl.source_listing_id: nl for nl in email_alerts.parse_alert(html=html, sender="noreply@rivianforums.com")}
    assert not email_alerts.worth_saving(found["70001"])
    assert not email_alerts.worth_saving(found["70002"])


# ------------------------------------------------------------------ KSL and other classifieds

KSL_PAGE = """2023 Rivian R1T Adventure
$52,000
Mileage 33,000
Title Type
Rebuilt/Reconstructed
Seller Type
For Sale By Owner
Ogden, UT 84401
"""


def test_ksl_paste_detects_private_seller_and_rebuilt_title():
    d = capture.draft_from_text(KSL_PAGE, "https://cars.ksl.com/listing/9900003")
    assert (d["source"], d["source_listing_id"]) == ("ksl", "9900003")
    assert d["seller_type"] == "private" and (d["price"], d["miles"]) == (52000, 33000)
    assert {c.field: c.value for c in d["claims"]}["title_status"] == "branded"


def test_ksl_alert_email_detects_private_sellers():
    text = ("2023 Rivian R1T Adventure\n$52,000 | 33,000 miles | Ogden, UT\nFor Sale By Owner\n"
            "https://cars.ksl.com/listing/9900001")
    [nl] = email_alerts.parse_alert(text=text, sender="KSL Cars <alerts@ksl.com>")
    assert nl.source_key == "ksl" and nl.seller_type == "private"


@pytest.mark.parametrize("text, expected", [
    ("Seller Type: For Sale By Owner", "private"),
    ("Private party sale, no dealer fees", "private"),
    ("Seller Type\nDealership", "dealer"),
    ("Dealer serviced, one owner", None),          # a private ad mentioning a dealer is not a dealer listing
    ("", None),
])
def test_seller_type_needs_explicit_wording(text, expected):
    assert parse_seller_type(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Title Type: Rebuilt/Reconstructed", "branded"),
    ("Title Type\nSalvage", "branded"),
    ("Title Type: Clean Title", "clean"),
    ("Clean title. Rebuilt front suspension last year", "clean"),
])
def test_labeled_title_types(text, expected):
    assert {c.field: c.value for c in extract_attributes(text, "test")}["title_status"] == expected


def test_all_spelled_out_states_normalize():
    assert normalize_state("Massachusetts") == "MA" and normalize_state("north carolina") == "NC"


# ------------------------------------------------------------------ Rivian Roamer: browse only

def test_roamer_pages_cannot_be_captured():
    url = "https://rivianroamer.com/inventory/abc123"
    assert capture.capture_blocked(url)
    assert "rivian.com" in capture.blocked_reason(url)
    assert capture.blocked_reason("https://cars.ksl.com/listing/1") is None


# ------------------------------------------------------------------ saved links for new and existing workspaces

def _forum_and_roamer_links(c):
    return sorted(r[0] for r in c.execute(
        "SELECT source_key FROM saved_searches WHERE source_key IN ('rivianforums', 'roamer')"))


def test_new_saved_links_reach_existing_workspaces_once(tmp_path):
    path = tmp_path / "w.db"
    c = db.connect(path)
    assert _forum_and_roamer_links(c) == ["rivianforums", "roamer"]
    # an older workspace: seeded before these links existed
    with c:
        c.execute("DELETE FROM saved_searches WHERE source_key IN ('rivianforums', 'roamer')")
        c.execute("DELETE FROM preferences WHERE key LIKE 'seed:%'")
    c.close()
    c = db.connect(path)
    assert _forum_and_roamer_links(c) == ["rivianforums", "roamer"]
    # one the user deletes stays deleted
    with c:
        c.execute("DELETE FROM saved_searches WHERE source_key='roamer'")
    c.close()
    c = db.connect(path)
    assert _forum_and_roamer_links(c) == ["rivianforums"]
    assert {"rivianforums", "roamer"} <= {r[0] for r in c.execute("SELECT key FROM sources")}
    c.close()
