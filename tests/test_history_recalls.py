"""Carfax links, listing age, MarketCheck Carfax flags, NHTSA recalls, and the v3 backfill migration."""
import json
import sqlite3

from conftest import FakeAdapter, listing, load_json, vin
from test_sources import FakeResponse, FakeSession, adapter

from rivian_finder import db, pipeline, queries, recalls
from rivian_finder.models import FetchResult
from rivian_finder.sources import autodev, marketcheck


def test_autodev_history_link_and_listing_date():
    a = adapter(autodev.AutoDevAdapter, [FakeResponse(200, load_json("autodev_page1.json")),
                                         FakeResponse(200, load_json("autodev_page2.json"))])
    first = a.fetch({}).listings[0]
    assert first.history_report_url.startswith("https://www.carfax.com/") and "partner=TEST" in first.history_report_url
    assert first.listed_at == "2026-10-01T10:00:00Z"


def test_marketcheck_carfax_flags_phone_and_age():
    a = adapter(marketcheck.MarketCheckAdapter, [FakeResponse(200, load_json("marketcheck_page1.json"))])
    first, second = a.fetch({}).listings
    claims = {c.field: c.value for c in first.attributes}
    assert claims["title_status"] == "clean" and claims["owners"] == "1 owner"
    assert first.seller_phone == "(801) 555-0100"
    assert first.days_on_market == 45
    assert first.listed_at == "2026-09-05T08:00:00Z"          # earliest of the provider's first-seen dates
    assert first.dealer_website == "https://exampleevdealer.example"
    assert "title_status" not in {c.field for c in second.attributes}   # False isn't evidence of a branded title


def test_listed_at_keeps_the_earliest_date(conn):
    a = FakeAdapter("autodev", [FetchResult([listing(vin=vin(1), listed_at="2026-09-01T00:00:00Z")], True, "s"),
                                FetchResult([listing(vin=vin(1), listed_at="2026-10-15T00:00:00Z")], True, "s")])
    pipeline.run_search(conn, [a], {})
    pipeline.run_search(conn, [a], {})
    assert conn.execute("SELECT listed_at FROM listings").fetchone()[0] == "2026-09-01T00:00:00Z"


class RecallSession(FakeSession):
    def __init__(self, by_year):
        super().__init__([])
        self.by_year = by_year

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(dict(params or {}))
        return FakeResponse(200, {"Count": 1, "results": self.by_year.get(params["modelYear"], [])})


RECALL = {"NHTSACampaignNumber": "24V408000", "ReportReceivedDate": "05/06/2024", "Component": "AIR BAGS",
          "Summary": "Clips may detach.", "Consequence": "Injury risk.", "Remedy": "Dealer repair.",
          "overTheAirUpdate": False, "parkIt": False}


def test_recalls_fetch_cache_and_lookup(conn, settings):
    sess = RecallSession({2023: [RECALL, dict(RECALL, NHTSACampaignNumber="23V783000", overTheAirUpdate=True)], 2025: []})
    out = recalls.refresh(conn, [2023, 2025], session=sess)
    assert out == {"years_fetched": 2, "errors": []}
    rows = recalls.for_year(conn, 2023)
    assert {r["campaign"] for r in rows} == {"24V408000", "23V783000"}
    assert rows[0]["report_date"] == "2024-06-05" or rows[1]["report_date"] == "2024-06-05"
    assert recalls.counts_by_year(conn) == {2023: 2}
    assert recalls.for_year(conn, 2025) == []
    recalls.refresh(conn, [2023, 2025], session=sess)        # cached for a week: no new calls
    assert len(sess.calls) == 2
    pipeline.import_listings(conn, [listing("dealer", import_method="manual", url="https://d.example/1",
                                            vin=vin(5, "P"), year=2023)], "manual_entry")
    row = queries.inventory_frame(conn, settings).iloc[0]
    assert row["recall_count"] == 2
    assert row["recall_lookup_url"].endswith("?vin=" + vin(5, "P"))


def test_migration_003_backfills_existing_rows(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    for name in ("001_initial", "002_seller_links_and_hiding"):
        c.executescript((db.MIGRATIONS_DIR / f"{name}.sql").read_text())
        c.execute("INSERT INTO schema_migrations VALUES (?, 'x')", (name,))
    c.execute("INSERT INTO vehicles(id, vin, created_at, updated_at) VALUES (1, 'X', 'x', 'x')")
    raw_ad = {"createdAt": "2026-10-16 09:27:42", "retailListing": {"carfaxUrl": "https://www.carfax.com/r?vin=X"}}
    raw_mc = {"first_seen_at_date": "2026-10-14T05:07:54.000Z", "dom": 36}
    for i, (src, raw) in enumerate((("autodev", raw_ad), ("marketcheck", raw_mc)), start=1):
        c.execute("INSERT INTO listings(id, vehicle_id, source_key, import_method, first_seen_at, last_seen_at, raw_json)"
                  " VALUES (?, 1, ?, 'api', 'x', 'x', ?)", (i, src, json.dumps(raw)))
    c.commit()
    c.close()
    c = db.connect(path)
    ad = c.execute("SELECT history_report_url, listed_at FROM listings WHERE id=1").fetchone()
    mc = c.execute("SELECT listed_at, days_on_market FROM listings WHERE id=2").fetchone()
    assert tuple(ad) == ("https://www.carfax.com/r?vin=X", "2026-10-16T09:27:42Z")
    assert tuple(mc) == ("2026-10-14T05:07:54Z", 36)
