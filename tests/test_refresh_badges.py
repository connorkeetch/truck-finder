"""Card badges use recorded event prices from one listing, not changes between mirrors."""
import copy

import pandas as pd
import pytest

from conftest import FakeAdapter, listing, vin
from rivian_finder import pipeline, queries
from rivian_finder.models import FetchResult, SourceError


def change(event_type="price_drop", *, id=1, vehicle_id=1, listing_id=10, source_key="autodev", **values):
    return {"id": id, "vehicle_id": vehicle_id, "listing_id": listing_id, "event_type": event_type,
            "old_value": "60000", "new_value": "58000", "source_key": source_key,
            "url": f"https://{source_key}.example/listing/{listing_id}", "run_id": 7,
            "created_at": "2026-10-26T12:00:00Z", **values}


def attach(events, rows=None, run=None):
    rows = rows if rows is not None else [{"vehicle_id": 1, "listing_id": 10, "status": "active", "active_listings": 1}]
    return queries.attach_refresh_badges(pd.DataFrame(rows), {"run": run or {"id": 7, "status": "success"},
                                                           "events": pd.DataFrame(events)})


def test_no_refresh_and_empty_or_older_frames_are_safe_and_lists_are_independent():
    original = pd.DataFrame({"vehicle_id": [1, 2]}, index=[5, 5])
    before = original.copy(deep=True)
    result = queries.attach_refresh_badges(original, {"run": None, "events": pd.DataFrame([change()])})
    pd.testing.assert_frame_equal(original, before)
    assert result["refresh_categories"].tolist() == [[], []]
    assert result["refresh_note"].tolist() == ["", ""]
    result.iloc[0]["refresh_badges"].append({"text": "test"})
    assert result.iloc[1]["refresh_badges"] == []
    empty = queries.attach_refresh_badges(pd.DataFrame(), {})
    assert list(empty) == ["refresh_categories", "refresh_badges", "refresh_note"]
    assert queries.filter_refresh_changes(empty, ["new"]).equals(empty)
    assert attach([change()], rows=[{"price": 58000}])["refresh_badges"].tolist() == [[]]


def test_primary_listing_price_wins_without_mirror_inflation_or_current_price_inference():
    events = [change(id=1), change(id=2, listing_id=20, source_key="marketcheck"),
              change(id=3, old_value="58000", new_value="57000", update_origin="After refresh"),
              change(id=4, listing_id=20, source_key="marketcheck", old_value="58000", new_value="50000")]
    row = attach(list(reversed(events)), rows=[{"vehicle_id": 1, "listing_id": 10, "price": 1}]).iloc[0]
    assert row.refresh_categories == ["price"]
    assert row.refresh_badges[0]["text"] == "Price down $3,000"
    assert row.refresh_badges[0]["kind"] == "price_down"
    assert "$60,000 → $57,000" in row.refresh_note and "After refresh" in row.refresh_note
    assert "autodev.example/listing/10" in row.refresh_note and "marketcheck" not in row.refresh_note


def test_without_primary_change_latest_changed_listing_is_used_with_its_own_baseline():
    events = [change(id=1), change(id=2, listing_id=20, source_key="marketcheck", old_value="50000", new_value="49000"),
              change("price_increase", id=3, listing_id=20, source_key="marketcheck", old_value="49000", new_value="51000")]
    badge = attach(events, rows=[{"vehicle_id": 1, "listing_id": 99}]).iloc[0].refresh_badges[0]
    assert badge["text"] == "Price up $1,000" and badge["kind"] == "price_up"
    assert "MarketCheck: $50,000 → $51,000" in badge["detail"]


@pytest.mark.parametrize("events, text", [
    ([change(), change("price_increase", id=2, old_value="58000", new_value="60000")], "Price changed"),
    ([change(old_value=None)], "Price changed"),
    ([change(new_value="bad")], "Price changed"),
    ([change(new_value=0)], "Price changed"),
    ([change(old_value="60000.50", new_value="60000.25")], "Price down $0.25"),
])
def test_zero_net_invalid_prices_and_cents_are_labeled_without_fabrication(events, text):
    assert attach(events).iloc[0].refresh_badges[0]["text"] == text


def test_new_source_is_distinct_from_new_vehicle_and_can_coexist_with_price():
    source = attach([change("new_source_for_vin"), change(id=2)]).iloc[0]
    assert source.refresh_categories == ["new", "price"]
    assert [badge["text"] for badge in source.refresh_badges] == ["New source", "Price down $2,000"]
    assert source.refresh_badges[0]["kind"] == "new_source"
    new = attach([change("new_source_for_vin"), change("new_listing", id=2)]).iloc[0]
    assert [badge["text"] for badge in new.refresh_badges] == ["New"]


def test_removed_source_and_missing_keep_event_url_and_never_claim_sold():
    events = [change("provider_removed", listing_id=20, source_key="marketcheck", new_value="2026-10-26"),
              change("disappeared", id=2, listing_id=30, new_value="missing")]
    row = attach(events).iloc[0]
    assert row.refresh_categories == ["removed", "missing"]
    assert [badge["text"] for badge in row.refresh_badges] == ["Source removed", "Not seen"]
    assert "marketcheck.example/listing/20" in row.refresh_note
    assert "autodev.example/listing/30" in row.refresh_note
    assert "sale is unconfirmed" in row.refresh_note and "Sold" not in row.refresh_note
    removed = attach(events[:1], rows=[{"vehicle_id": 1, "status": "removed", "active_listings": 0}]).iloc[0]
    assert removed.refresh_badges[0]["text"] == "Removed"


def test_old_event_frames_without_derived_price_columns_or_listing_identity_are_safe():
    events = [change(id=1, listing_id=None), change(id=2, listing_id=None, old_value="58000", new_value="57000")]
    row = attach(events, rows=[{"vehicle_id": 1}]).iloc[0]
    assert row.refresh_badges[0]["text"] == "Price down $1,000"  # Unknown listings must not be stitched.
    events = [{"id": 1, "vehicle_id": 1, "event_type": "price_drop", "old_price": 60000, "new_price": 58000}]
    assert attach(events).iloc[0].refresh_badges[0]["text"] == "Price down $2,000"
    missing = attach([change("marked_removed", run_id=pd.NA)],
                     rows=[{"vehicle_id": 1, "status": pd.NA, "active_listings": pd.NA}]).iloc[0]
    assert missing.refresh_badges[0]["text"] == "Removed" and "After refresh" in missing.refresh_note


def test_change_filter_matches_any_category_and_does_not_change_default_inventory_filters():
    result = attach([change("new_listing"), change(vehicle_id=2, id=2), change("disappeared", vehicle_id=3, id=3)],
                    rows=[{"vehicle_id": i} for i in range(1, 5)])
    assert queries.filter_refresh_changes(result, []).equals(result)
    assert queries.filter_refresh_changes(result, ["new", "missing"])["vehicle_id"].tolist() == [1, 3]
    assert queries.filter_refresh_changes(result, ["price"])["vehicle_id"].tolist() == [2]
    assert queries.filter_refresh_changes(pd.DataFrame({"vehicle_id": [1]}), ["price"]).empty


def test_real_refresh_window_is_stable_and_failed_partial_scans_do_not_invent_missing_badges(conn, settings):
    def scan(entries, complete=True):
        return pipeline.run_search(conn, [FakeAdapter("autodev", [FetchResult(entries, complete, "scope")])], {})

    scan([listing(vin=vin(1)), listing(vin=vin(2))])
    scan([listing(vin=vin(1), price=58000)], complete=False)
    pipeline.import_listings(conn, [listing(vin=vin(1), price=57000)], "csv")
    refresh = queries.refresh_changes(conn)
    original = copy.deepcopy(refresh["events"])
    inventory = queries.inventory_frame(conn, settings)
    before = conn.total_changes
    first = queries.attach_refresh_badges(inventory, refresh)
    again = queries.attach_refresh_badges(inventory, queries.refresh_changes(conn))
    pd.testing.assert_frame_equal(first, again)
    pd.testing.assert_frame_equal(refresh["events"], original)
    assert conn.total_changes == before
    assert first.set_index("vin").loc[vin(1), "refresh_badges"][0]["text"] == "Price down $3,000"
    assert first.set_index("vin").loc[vin(2), "refresh_categories"] == []
    pipeline.run_search(conn, [FakeAdapter("autodev", [SourceError("Unavailable")])], {})
    failed = queries.attach_refresh_badges(inventory, queries.refresh_changes(conn))
    assert failed["refresh_badges"].tolist() == [[], []]
