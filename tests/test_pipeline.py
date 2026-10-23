"""Change detection: new, price changes, mileage, seller, disappear/return, incomplete and failed scans."""
import pytest

from conftest import FakeAdapter, listing, vin

from rivian_finder import pipeline, queries
from rivian_finder.models import AttributeClaim, FetchResult, RateLimited, SourceError


def run(conn, *adapters):
    return pipeline.run_search(conn, list(adapters), {})


def ok(listings, complete=True, scope="s1"):
    return FetchResult(listings=listings, complete=complete, scope_hash=scope)


def status_of(conn, source_listing_id):
    return conn.execute("SELECT status FROM listings WHERE source_listing_id=?", (source_listing_id,)).fetchone()[0]


def test_first_run_reports_new_listings(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1)), listing(vin=vin(2))])])
    s = run(conn, a)
    assert s["counts"]["new_listing"] == 2
    assert s["status"] == "success"
    assert conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 2


def test_price_drop_and_increase(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1), price=60000), listing(vin=vin(2), price=50000)]),
                                ok([listing(vin=vin(1), price=58500), listing(vin=vin(2), price=51000)])])
    run(conn, a)
    s = run(conn, a)
    assert s["counts"]["price_drop"] == 1
    assert s["counts"]["price_increase"] == 1
    ev = conn.execute("SELECT old_value, new_value FROM change_events WHERE event_type='price_drop'").fetchone()
    assert (ev[0], ev[1]) == ("60000", "58500")
    # history is kept, not overwritten
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 4


def test_mileage_and_seller_changes(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1), miles=15000, seller_name="A Motors")]),
                                ok([listing(vin=vin(1), miles=15250, seller_name="B Auto Group")])])
    run(conn, a)
    s = run(conn, a)
    assert s["counts"]["mileage_update"] == 1
    assert s["counts"]["seller_change"] == 1


def test_disappearance_requires_complete_scan(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1)), listing(vin=vin(2))]),
                                ok([listing(vin=vin(1))], complete=False),
                                ok([listing(vin=vin(1))], complete=True)])
    run(conn, a)
    s2 = run(conn, a)
    assert s2["counts"]["disappeared"] == 0
    assert status_of(conn, vin(2)) == "active"
    assert s2["status"] == "partial"
    s3 = run(conn, a)
    assert s3["counts"]["disappeared"] == 1
    assert status_of(conn, vin(2)) == "missing"   # missing, not "sold"


@pytest.mark.parametrize("field", ["trim", "title", "battery"])
@pytest.mark.parametrize("exclude", [False, True])
def test_standard_range_exclusion_does_not_create_false_disappearances(conn, field, exclude):
    values = {field: "Elevation Standard Range"} if field != "battery" else {
        "attributes": [AttributeClaim("battery", "Standard Range", "high", "Vehicle configuration")]}
    truck = listing(sid="gmc-standard", make="GMC", model="Sierra EV", **values)
    a = FakeAdapter("autodev", [ok([truck]), ok([])])
    scope = {"include_other_brands": True, "exclude_standard_range": exclude}
    pipeline.run_search(conn, [a], scope)
    result = pipeline.run_search(conn, [a], scope)
    assert result["counts"]["disappeared"] == int(not exclude)
    assert status_of(conn, "gmc-standard") == ("active" if exclude else "missing")


def test_failed_source_never_marks_listings_missing(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1)), listing(vin=vin(2))]),
                                SourceError("HTTP 500"), RateLimited("429")])
    run(conn, a)
    s = run(conn, a)
    assert s["status"] == "failed"
    assert s["counts"]["disappeared"] == 0
    s = run(conn, a)
    assert "Rate limited" in s["sources"][0]["error"]
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE status='active'").fetchone()[0] == 2


def test_one_failing_source_does_not_affect_another(conn):
    good = FakeAdapter("autodev", [ok([listing(vin=vin(1))]), ok([listing(vin=vin(1))])])
    bad = FakeAdapter("marketcheck", [ok([listing("marketcheck", sid="m2", vin=vin(2))]), SourceError("boom")])
    run(conn, good, bad)
    s = run(conn, good, bad)
    assert s["status"] == "partial"
    assert status_of(conn, "m2") == "active"
    assert "previous listings left unchanged" in queries.summary_text(s, 1)


def test_listing_returns_after_disappearing(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1)), listing(vin=vin(2))]), ok([listing(vin=vin(1))]),
                                ok([listing(vin=vin(1)), listing(vin=vin(2))])])
    run(conn, a)
    run(conn, a)
    s = run(conn, a)
    assert s["counts"]["returned"] == 1
    assert status_of(conn, vin(2)) == "active"


def test_scope_change_skips_disappearance_once(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1)), listing(vin=vin(2))], scope="old"),
                                ok([listing(vin=vin(1))], scope="new"),
                                ok([listing(vin=vin(1))], scope="new")])
    run(conn, a)
    s = run(conn, a)
    assert s["counts"]["disappeared"] == 0
    assert any("scope changed" in n for n in s["sources"][0]["notes"])
    assert run(conn, a)["counts"]["disappeared"] == 1


def test_unscanned_models_remain_active(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1)), listing(vin=vin(2), make="Ford", model="F-150 Lightning")]),
                                ok([listing(vin=vin(1))])])
    run(conn, a)
    s = pipeline.run_search(conn, [a], {"include_other_brands": False})
    assert s["counts"]["disappeared"] == 0
    assert status_of(conn, vin(2)) == "active"


def test_competitors_use_their_own_price_and_mileage_scope(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1), make="Ford", model="F-150 Lightning", price=66000),
                                    listing(vin=vin(2), make="Chevrolet", model="Silverado EV", miles=46000),
                                    listing(vin=vin(3), make="GMC", model="Sierra EV", miles=44000),
                                    listing(vin=vin(4), make="Ford", model="F-150 Lightning", zip="10001")]),
                                ok([])])
    scope = {"include_other_brands": True, "other_max_price": 65000, "other_max_miles": 45000,
             "home_zip": "84020", "max_price": 75000, "max_miles": 60000}
    pipeline.run_search(conn, [a], scope)
    s = pipeline.run_search(conn, [a], scope)
    assert s["counts"]["disappeared"] == 1  # Only the covered Sierra was re-checked.
    assert status_of(conn, vin(3)) == "missing"
    assert status_of(conn, vin(4)) == "active"  # Outside the geographic query.
    for serial in (1, 2):
        reason = conn.execute("SELECT status_reason FROM listings WHERE source_listing_id=?", (vin(serial),)).fetchone()[0]
        assert "outside the collection scope" in reason


def test_unconfigured_source_is_skipped(conn):
    s = run(conn, FakeAdapter("autodev", [], configured=False))
    assert s["sources"][0]["status"] == "skipped"


def test_new_source_for_existing_vin(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1))])])
    m = FakeAdapter("marketcheck", [ok([listing("marketcheck", sid="mc-1", vin=vin(1), url="https://dealer.example/x")])])
    run(conn, a)
    s = run(conn, m)
    assert s["counts"]["new_source_for_vin"] == 1
    assert s["counts"]["new_listing"] == 0
    assert conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 2


def test_manual_import_never_marks_others_missing(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1)), listing(vin=vin(2))])])
    run(conn, a)
    pipeline.import_listings(conn, [listing("ksl", import_method="manual", url="https://cars.ksl.com/listing/123456",
                                            source_listing_id="123456")], "manual_entry")
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE status='active'").fetchone()[0] == 3


def test_equipment_change_detected(conn):
    t1 = [AttributeClaim("tonneau", "yes", "medium", "api")]
    t2 = [AttributeClaim("tonneau", "no", "medium", "api")]
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1), attributes=t1)]), ok([listing(vin=vin(1), attributes=t2)])])
    run(conn, a)
    s = run(conn, a)
    assert s["counts"]["equipment_change"] == 1


def test_provider_removed_is_distinct_from_missing(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1))]), ok([listing(vin=vin(1), removed_at="2026-10-01")], complete=False)])
    run(conn, a)
    run(conn, a)
    assert status_of(conn, vin(1)) == "removed"


def test_user_mark_removed(conn):
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1))])])
    run(conn, a)
    lid = conn.execute("SELECT id FROM listings").fetchone()[0]
    pipeline.mark_removed(conn, lid)
    assert status_of(conn, vin(1)) == "removed"


def test_listings_outside_collection_scope_are_not_counted_missing(conn):
    scope = {"year_min": 2023, "year_max": 2026, "max_price": 75000, "max_miles": 60000}
    a = FakeAdapter("autodev", [ok([listing(vin=vin(1, "N"), year=2022), listing(vin=vin(2)), listing(vin=vin(3))]),
                                ok([listing(vin=vin(2))])])
    pipeline.run_search(conn, [a], {})
    s = pipeline.run_search(conn, [a], scope)
    assert s["counts"]["disappeared"] == 1                       # vin(3): in scope, really gone
    row = conn.execute("SELECT status, status_reason FROM listings WHERE source_listing_id=?", (vin(1, "N"),)).fetchone()
    assert row["status"] == "missing" and "outside the collection scope" in row["status_reason"]
    assert any("outside the collection scope" in n for n in s["sources"][0]["notes"])


def test_outside_scope_reasons():
    scope = {"year_min": 2023, "year_max": 2026, "max_price": 75000, "max_miles": 60000}
    assert pipeline.outside_scope(2022, 50000, 10000, scope).startswith("model year 2022")
    assert "above $75,000" in pipeline.outside_scope(2024, 76000, 10000, scope)
    assert "mileage" in pipeline.outside_scope(2024, 60000, 61000, scope)
    assert pipeline.outside_scope(2024, 60000, 20000, scope) is None
    assert pipeline.outside_scope(2022, 1, 1, {}) is None


def test_api_budget(conn):
    a = FakeAdapter("autodev", [FetchResult([listing(vin=vin(1))], True, "s", api_calls=11)])
    pipeline.run_search(conn, [a], {})
    for _ in range(30):
        conn.execute("INSERT INTO api_usage(source_key, called_at, endpoint, status_code) VALUES ('autodev', ?, 'x', 200)",
                     (pipeline.utcnow(),))
    b = queries.api_budget(conn, "autodev", 1000)
    assert (b["used"], b["per_run"], b["left"], b["runs_left"]) == (30, 11, 970, 88)
