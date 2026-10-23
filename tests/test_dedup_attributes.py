"""VIN deduplication, conservative fuzzy candidates, merging, and attribute resolution."""
from conftest import listing, vin

import pytest

from rivian_finder import attributes, dedup, pipeline
from rivian_finder.models import AttributeClaim


def imp(conn, *ls):
    return pipeline.import_listings(conn, list(ls), "manual_entry")


def test_same_vin_across_sources_is_one_vehicle(conn):
    imp(conn, listing("autotrader", import_method="email", url="https://www.autotrader.com/cars-for-sale/vehicle/711111111",
                      source_listing_id="711111111", vin=vin(5)),
        listing("dealer", import_method="capture", url="https://dealer.example/r1t", vin=vin(5).lower()))
    assert conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 2


def test_same_url_reimport_updates_existing_listing(conn):
    url = "https://www.cars.com/vehicledetail/abc-123/?utm_source=alert"
    imp(conn, listing("cars_com", import_method="email", url=url, price=61000, vin=None))
    s = imp(conn, listing("cars_com", import_method="capture", url="https://cars.com/vehicledetail/abc-123",
                          price=59900, vin=None))
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1
    assert s["counts"]["price_drop"] == 1


def test_invalid_checksum_vin_is_not_used_for_auto_merge(conn):
    good = vin(7)
    typo = good[:8] + ("1" if good[8] != "1" else "2") + good[9:]
    imp(conn, listing("dealer", import_method="manual", url="https://a.example/1", vin=good))
    imp(conn, listing("dealer", import_method="manual", url="https://b.example/2", vin=typo))
    rows = conn.execute("SELECT vin, vin_raw FROM vehicles ORDER BY id").fetchall()
    assert rows[0]["vin"] == good
    assert rows[1]["vin"] is None and rows[1]["vin_raw"] == typo


def test_vinless_lookalike_creates_candidate_but_never_merges(conn):
    imp(conn, listing("ksl", import_method="manual", url="https://cars.ksl.com/listing/1111111", source_listing_id="1111111",
                      vin=None, year=2023, miles=21000, price=55000, exterior_color="Launch Green", seller_name="Jane Doe",
                      city="Provo", state="UT"))
    imp(conn, listing("facebook", import_method="manual", url="https://www.facebook.com/marketplace/item/2222222",
                      source_listing_id="2222222", vin=None, year=2023, miles=21100, price=54500,
                      exterior_color="Launch Green", seller_name="Jane Doe", city="Provo", state="UT"))
    assert conn.execute("SELECT COUNT(*) FROM vehicles WHERE merged_into_id IS NULL").fetchone()[0] == 2
    cand = conn.execute("SELECT * FROM match_candidates").fetchall()
    assert len(cand) == 1 and cand[0]["status"] == "pending"


def test_different_trucks_do_not_become_candidates(conn):
    imp(conn, listing("ksl", import_method="manual", url="https://x.example/1", vin=None, year=2023, miles=21000,
                      exterior_color="Launch Green", state="UT"),
        listing("ksl", import_method="manual", url="https://x.example/2", vin=None, year=2023, miles=39000,
                exterior_color="Glacier White", state="CA"))
    assert conn.execute("SELECT COUNT(*) FROM match_candidates").fetchone()[0] == 0


def test_two_different_valid_vins_are_never_candidates(conn):
    imp(conn, listing("dealer", import_method="manual", url="https://x.example/1", vin=vin(1), miles=20000),
        listing("dealer", import_method="manual", url="https://x.example/2", vin=vin(2), miles=20000))
    assert conn.execute("SELECT COUNT(*) FROM match_candidates").fetchone()[0] == 0


def test_merge_preserves_listings_and_history(conn):
    imp(conn, listing("ksl", import_method="manual", url="https://x.example/1", vin=None))
    imp(conn, listing("dealer", import_method="manual", url="https://x.example/2", vin=vin(9)))
    a, b = [r[0] for r in conn.execute("SELECT id FROM vehicles ORDER BY id")]
    keep = dedup.merge_vehicles(conn, b, a)
    assert keep == b
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE vehicle_id=?", (b,)).fetchone()[0] == 2
    assert conn.execute("SELECT merged_into_id FROM vehicles WHERE id=?", (a,)).fetchone()[0] == b
    assert conn.execute("SELECT COUNT(*) FROM merges").fetchone()[0] == 1


def test_merge_refuses_conflicting_vins(conn):
    imp(conn, listing("dealer", import_method="manual", url="https://x.example/1", vin=vin(1)),
        listing("dealer", import_method="manual", url="https://x.example/2", vin=vin(2)))
    a, b = [r[0] for r in conn.execute("SELECT id FROM vehicles ORDER BY id")]
    with pytest.raises(ValueError):
        dedup.merge_vehicles(conn, a, b)


def test_set_vin_merges_into_existing_vehicle(conn):
    imp(conn, listing("dealer", import_method="manual", url="https://x.example/1", vin=vin(3)))
    imp(conn, listing("ksl", import_method="manual", url="https://x.example/2", vin=None))
    vinless = conn.execute("SELECT id FROM vehicles WHERE vin IS NULL").fetchone()[0]
    keep, msg = dedup.set_vin(conn, vinless, vin(3))
    assert "merged" in msg
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE vehicle_id=?", (keep,)).fetchone()[0] == 2


def test_vin_gives_year_and_generation(conn):
    imp(conn, listing("dealer", import_method="manual", url="https://x.example/1", vin=vin(4, year_code="S"), year=None))
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    r = attributes.resolve(conn, vid)
    assert r["model_year"].value == "2025"
    assert r["generation"].value == "Gen 2"
    assert r["generation"].source == "vin_rule"


# ------------------------------------------------------------------ attribute resolution

def _vehicle_with(conn, claims):
    imp(conn, listing("dealer", import_method="manual", url="https://x.example/v", vin=vin(11), attributes=claims))
    return conn.execute("SELECT id FROM vehicles").fetchone()[0]


def test_higher_confidence_wins_and_conflict_is_flagged(conn):
    vid = _vehicle_with(conn, [AttributeClaim("battery", "Large", "low", "text"),
                               AttributeClaim("battery", "Max", "medium", "structured")])
    r = attributes.resolve(conn, vid)["battery"]
    assert r.value == "Max"
    assert r.conflict


def test_user_override_beats_every_source_and_survives_rescans(conn):
    vid = _vehicle_with(conn, [AttributeClaim("tonneau", "yes", "medium", "structured")])
    attributes.set_override(conn, vid, "tonneau", "yes", "opened and closed it")
    imp(conn, listing("dealer", import_method="manual", url="https://x.example/v", vin=vin(11),
                      attributes=[AttributeClaim("tonneau", "yes", "medium", "structured")]))
    r = attributes.resolve(conn, vid)["tonneau"]
    assert r.value == "yes"
    assert r.confidence == "verified"
    assert not r.conflict   # 'listed' is consistent with 'confirmed working'


def test_unknown_when_no_source_reports(conn):
    vid = _vehicle_with(conn, [])
    r = attributes.resolve(conn, vid)
    assert r["tonneau"].value == "unknown"
    assert r["battery"].value == "Unknown"
    assert r["epa_range"].value is None


def test_performance_dual_refines_vpic_dual(conn):
    vid = _vehicle_with(conn, [AttributeClaim("motor", "Dual", "high", "vPIC", source="nhtsa_vpic"),
                               AttributeClaim("motor", "Performance Dual", "low", "listing text")])
    r = attributes.resolve(conn, vid)["motor"]
    assert r.value == "Performance Dual"
    assert not r.conflict
