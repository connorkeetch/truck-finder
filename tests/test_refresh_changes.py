"""Refresh summaries use recorded changes, including updates hidden by ordinary inventory filters."""
import pytest

from conftest import FakeAdapter, listing, vin
from rivian_finder import pipeline, queries
from rivian_finder.models import FetchResult, SourceError


def scan(conn, entries, complete=True, scope=None):
    return pipeline.run_search(conn, [FakeAdapter("autodev", [FetchResult(entries, complete, "scope")])], scope or {})


def test_no_refresh_does_not_treat_an_import_as_a_refresh(conn):
    pipeline.import_listings(conn, [listing(vin=vin(1))], "csv")
    result = queries.refresh_changes(conn)
    assert result["run"] is None and result["events"].empty


def test_latest_refresh_has_new_both_price_directions_removed_and_missing(conn):
    scan(conn, [listing(vin=vin(i), price=60000) for i in range(1, 5)])
    latest = scan(conn, [listing(vin=vin(1), price=58500), listing(vin=vin(2), price=61000),
                         listing(vin=vin(3), removed_at="2026-10-25"), listing(vin=vin(5), price=55000)])
    result = queries.refresh_changes(conn)
    assert result["run"]["id"] == latest["run_id"] and not result["run"]["first_refresh"]
    events = result["events"]
    assert events["category"].value_counts().to_dict() == {"price": 2, "new": 1, "removed": 1, "missing": 1}
    changes = events[events["category"] == "price"].set_index("vin")
    assert (changes.loc[vin(1), "old_price"], changes.loc[vin(1), "new_price"], changes.loc[vin(1), "price_delta"]) == (
        60000, 58500, -1500)
    assert changes.loc[vin(2), "price_delta"] == 1000
    assert events[events["category"] == "removed"]["listing_status"].tolist() == ["removed"]
    assert events[events["category"] == "missing"]["listing_status"].tolist() == ["missing"]


def test_first_refresh_is_a_baseline_and_records_a_first_seen_removal_correctly(conn):
    scan(conn, [listing(vin=vin(1)), listing(vin=vin(2), removed_at="2026-10-25")])
    result = queries.refresh_changes(conn)
    assert result["run"]["first_refresh"]
    assert result["events"].set_index("vin")["category"].to_dict() == {vin(1): "new", vin(2): "removed"}


def test_later_imports_keep_original_refresh_prices_and_do_not_replace_the_refresh(conn):
    scan(conn, [listing(vin=vin(1), price=60000)])
    refresh = scan(conn, [listing(vin=vin(1), price=58000)])
    pipeline.import_listings(conn, [listing(vin=vin(1), price=57000), listing(vin=vin(2))], "csv")
    result = queries.refresh_changes(conn)
    assert result["run"]["id"] == refresh["run_id"]
    events = result["events"]
    original = events[(events["run_id"] == refresh["run_id"]) & (events["category"] == "price")].iloc[0]
    assert (original.old_price, original.new_price, original.price_delta) == (60000, 58000, -2000)
    assert original.current_price == 57000
    assert sorted(events[events["category"] == "price"]["price_delta"]) == [-2000, -1000]
    assert "After refresh" in set(events["update_origin"])


def test_manual_removal_after_refresh_is_visible_but_older_manual_events_are_not(conn):
    scan(conn, [listing(vin=vin(1)), listing(vin=vin(2))])
    ids = dict(conn.execute("SELECT source_listing_id, id FROM listings"))
    pipeline.mark_removed(conn, ids[vin(1)], "Marked sold by user")
    conn.execute("UPDATE change_events SET created_at='2000-01-01T00:00:00Z' WHERE event_type='marked_removed'")
    scan(conn, [listing(vin=vin(2))])
    pipeline.mark_removed(conn, ids[vin(2)], "Marked sold by user")
    events = queries.refresh_changes(conn)["events"]
    assert events[events["event_type"] == "marked_removed"]["vin"].tolist() == [vin(2)]
    assert events[events["event_type"] == "marked_removed"]["update_origin"].tolist() == ["After refresh"]


@pytest.mark.parametrize("complete", [True, False])
def test_brand_refresh_omits_old_changes_and_other_brand_statuses(conn, complete):
    scan(conn, [listing(vin=vin(1)), listing(vin=vin(2))])
    scan(conn, [listing(vin=vin(1))])  # old Rivian missing event
    ford = listing(sid="ford", make="Ford", model="F-150 Lightning")
    latest = scan(conn, [ford], complete=complete, scope={"brands": ["Ford"]})
    result = queries.refresh_changes(conn)
    assert result["run"]["id"] == latest["run_id"]
    assert result["run"]["status"] == ("success" if complete else "partial")
    assert result["events"]["make"].tolist() == ["Ford"]
    assert "missing" not in set(result["events"]["category"])


def test_failed_refresh_is_not_replaced_by_the_previous_success(conn):
    scan(conn, [listing(vin=vin(1))])
    pipeline.run_search(conn, [FakeAdapter("autodev", [SourceError("Unavailable")])], {})
    result = queries.refresh_changes(conn)
    assert result["run"]["status"] == "failed" and result["events"].empty


def test_failed_first_attempt_does_not_establish_the_baseline(conn):
    pipeline.run_search(conn, [FakeAdapter("autodev", [SourceError("Unavailable")])], {})
    assert not queries.refresh_changes(conn)["run"]["first_refresh"]
    scan(conn, [listing(vin=vin(1))])
    assert queries.refresh_changes(conn)["run"]["first_refresh"]


def test_unfinished_refresh_does_not_show_half_ingested_changes(conn):
    scan(conn, [listing(vin=vin(1))])
    latest = scan(conn, [listing(vin=vin(1), price=58000)])
    running = pipeline.start_run(conn, "run_search", ["autodev"])
    pipeline.Ingestor(conn, running).ingest(listing(vin=vin(1), price=57000))
    result = queries.refresh_changes(conn)
    assert result["run"]["id"] == latest["run_id"]
    assert result["events"]["price_delta"].tolist() == [-2000]


def test_removed_link_retains_its_source_url_when_the_vehicle_has_an_active_listing(conn):
    first = listing(vin=vin(1), url="https://dealer.example/removed-link")
    second = listing("marketcheck", sid="second", vin=vin(1), url="https://dealer.example/active-link")
    pipeline.run_search(conn, [FakeAdapter("autodev", [FetchResult([first], True, "scope")]),
                               FakeAdapter("marketcheck", [FetchResult([second], True, "scope")])], {})
    scan(conn, [listing(vin=vin(1), removed_at="2026-10-25", url=first.url)])
    removed = queries.refresh_changes(conn)["events"].query("category == 'removed'").iloc[0]
    assert removed.url == first.url and removed.source == "Auto.dev"
    assert conn.execute("SELECT status FROM listings WHERE source_key='marketcheck'").fetchone()[0] == "active"
