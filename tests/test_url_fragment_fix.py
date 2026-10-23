"""Regression tests for the shared-aggregator-URL bug and its one-time repair."""
import json
import sqlite3

from conftest import FakeAdapter, listing, vin

from rivian_finder import db, pipeline, repairs
from rivian_finder.dedup import norm_seller
from rivian_finder.extract import canonical_url
from rivian_finder.models import AttributeClaim, FetchResult

AUTOLIST = "https://www.autolist.com/rivian-r1t#vin="


def test_canonical_url_keeps_identifying_fragments():
    assert canonical_url(AUTOLIST + "AAA") != canonical_url(AUTOLIST + "BBB")
    assert canonical_url("https://www.cargurus.com/Cars/x#listing=123") == "https://cargurus.com/Cars/x#listing=123"
    assert canonical_url("https://dealer.example/r1t#gallery") == "https://dealer.example/r1t"


def test_trucks_sharing_an_aggregator_url_stay_separate(conn):
    rows = [listing(vin=vin(i), url=AUTOLIST + vin(i), price=50000 + i * 1000, seller_name=f"Dealer {i}") for i in range(1, 6)]
    s = pipeline.run_search(conn, [FakeAdapter("autodev", [FetchResult(rows, True, "s")])], {})
    assert s["counts"]["new_listing"] == 5 and s["counts"]["price_drop"] == 0 and s["counts"]["seller_change"] == 0
    assert conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 5


def test_url_match_never_joins_different_vins(conn):
    # even if two URLs are literally identical, different validated VINs must not merge
    same = "https://shared.example/listing"
    pipeline.import_listings(conn, [listing("dealer", import_method="manual", url=same, vin=vin(1))], "manual_entry")
    pipeline.import_listings(conn, [listing("dealer", import_method="manual", url=same, vin=vin(2))], "manual_entry")
    assert conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 2


def test_seller_name_variants_are_the_same_seller():
    assert norm_seller("Carvana - Columbus") == norm_seller("Carvana")
    assert norm_seller("BMW of Carlsbad") == norm_seller("BMW Carlsbad")
    assert norm_seller("CarMax Salt Lake (South Jordan)") == norm_seller("CarMax Centennial")
    assert norm_seller("AutoMatch") == norm_seller("Automatch")
    assert norm_seller("Reel Deal Auto") != norm_seller("AutoMatch")


def test_carvana_hub_names_are_not_seller_changes(conn):
    a = FakeAdapter("autodev", [FetchResult([listing(vin=vin(1), seller_name="Carvana - Columbus")], True, "s"),
                                FetchResult([listing(vin=vin(1), seller_name="Carvana")], True, "s")])
    pipeline.run_search(conn, [a], {})
    assert pipeline.run_search(conn, [a], {})["counts"]["seller_change"] == 0


def test_repair_removes_mixed_up_listing(tmp_path):
    path = tmp_path / "live.db"
    c = db.connect(path)
    good = [listing(vin=vin(1), url="https://good.example/1")]
    pipeline.run_search(c, [FakeAdapter("autodev", [FetchResult(good, True, "s")])], {})
    # simulate the old bug: a listing that absorbed other trucks
    pipeline.import_listings(c, [listing("dealer", import_method="api", url="https://autolist.com/r1t", vin=vin(2),
                                         attributes=[AttributeClaim("vin_conflict", vin(3), "low", "x")])], "manual_entry")
    c.execute("INSERT INTO change_events(run_id, listing_id, vehicle_id, event_type, old_value, new_value, created_at)"
              " VALUES (NULL, 1, 1, 'seller_change', 'Carvana - Dallas', 'Carvana', 'x')")
    c.execute("DELETE FROM preferences WHERE key LIKE 'repair:%'")
    c.commit()
    out = repairs.repair_url_fragments(c)
    assert out == {"listings": 1, "vehicles": 1, "seller_events": 1}
    assert c.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 1           # the good truck survives
    assert c.execute("SELECT COUNT(*) FROM vehicle_attributes WHERE field='vin_conflict'").fetchone()[0] == 0
    assert list((tmp_path / "backups").glob("*before_repair.db"))                  # backed up first
    assert repairs.repair_url_fragments(c) == {}                                    # runs once
    c.close()
    c = db.connect(path)                                                             # and not again on reopen
    assert json.loads(c.execute("SELECT value FROM preferences WHERE key='repair:2026-10-url-fragments'").fetchone()[0])


def test_repair_keeps_vehicles_with_user_data(tmp_path):
    c = db.connect(tmp_path / "x.db")
    pipeline.import_listings(c, [listing("dealer", import_method="api", url="https://autolist.com/r1t", vin=vin(2),
                                         attributes=[AttributeClaim("vin_conflict", vin(3), "low", "x")])], "manual_entry")
    vid = c.execute("SELECT id FROM vehicles").fetchone()[0]
    c.execute("INSERT INTO watchlist(vehicle_id, added_at) VALUES (?, 'x')", (vid,))
    c.execute("DELETE FROM preferences WHERE key LIKE 'repair:%'")
    c.commit()
    assert repairs.repair_url_fragments(c)["vehicles"] == 0
    assert c.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 1
