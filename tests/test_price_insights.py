"""Price insights count observed cuts, never differences between mirrored feeds."""
import pytest

from rivian_finder import price_insights


def vehicle(conn, serial=1, make="Rivian", **extra):
    values = dict(vin=f"TESTVIN{serial:010d}", make=make, model="R1T" if make == "Rivian" else "F-150 Lightning",
                  year=2024, created_at="2026-01-01", updated_at="2026-01-01")
    values.update(extra)
    columns = ",".join(values)
    return conn.execute(f"INSERT INTO vehicles ({columns}) VALUES ({','.join('?' for _ in values)})",
                        tuple(values.values())).lastrowid


def history(conn, vid, prices, source="autodev", seller="Rivian Richmond", url=None, **extra):
    values = dict(vehicle_id=vid, source_key=source, import_method="api", seller_name=seller, url=url,
                  first_seen_at="2026-01-01", last_seen_at="2026-01-01")
    values.update(extra)
    columns = ",".join(values)
    lid = conn.execute(f"INSERT INTO listings ({columns}) VALUES ({','.join('?' for _ in values)})",
                       tuple(values.values())).lastrowid
    for item in prices:
        at, price, *observation_seller = item
        conn.execute("INSERT INTO observations (listing_id,observed_at,price,import_method,seller_name) VALUES (?,?,?,'api',?)",
                     (lid, at, price, observation_seller[0] if observation_seller else seller))
    return lid


def day(n):
    return f"2026-01-{n:02d}T12:00:00Z"


def test_repeated_mirror_beats_one_day_direct_snapshot_without_stitching(conn):
    vid = vehicle(conn)
    mirror = history(conn, vid, [(day(1), 65000), (day(2), 63000), (day(3), 63000)])
    history(conn, vid, [(day(4), 59000)], source="rivian")
    history(conn, vid, [(day(1), 65000), (day(2), 63000)], source="marketcheck")
    result = price_insights.for_vehicle(conn, vid)
    own, cohort = result["vehicle"], result["rivian_seller"]
    assert own["listing_id"] == mirror and own["listing_timelines"] == 3
    assert (cohort["vehicle_count"], cohort["total_cuts"], cohort["total_reductions"]) == (1, 1, 2000)
    assert own["latest_observed_price"] == 63000
    assert own["mean_interval_days"] is None and cohort["interval_count"] == 0
    assert own["source"] == "autodev" and own["cohort_basis"] == "provider-reported Rivian seller identity"


def test_useful_direct_authority_precedes_longer_mirror_then_span_breaks_ties(conn):
    vid = vehicle(conn)
    history(conn, vid, [(day(1), 65000), (day(9), 60000)])
    direct = history(conn, vid, [(day(2), 64000), (day(3), 63500)], source="rivian")
    history(conn, vid, [(day(1), 65000), (day(8), 61000)], source="dealer", url="https://preowned.rivian.com/truck")
    result = price_insights.for_vehicle(conn, vid)["vehicle"]
    assert result["listing_id"] == direct and result["total_reductions"] == 500


def test_snapshot_feeds_never_create_a_cut_or_a_cadence(conn):
    vid = vehicle(conn)
    history(conn, vid, [(day(1), 65000)])
    history(conn, vid, [(day(4), 60000)], source="rivian")
    row = price_insights.for_vehicle(conn, vid)["vehicle"]
    assert row["history_status"] == "Single observed day"
    assert row["drops_count"] == 0 and row["net_change"] == 0
    assert row["mean_cut"] is None and row["mean_interval_days"] is None
    assert row["interval_status"] == "Insufficient history"


def test_one_same_day_interval_is_reported_with_sparse_support(conn):
    vid = vehicle(conn)
    history(conn, vid, [("2026-01-01T01:00:00Z", 60000), ("2026-01-01T03:00:00Z", 59000),
                        ("2026-01-01T09:00:00Z", 58000)])
    result = price_insights.for_vehicle(conn, vid)
    row, cohort = result["vehicle"], result["rivian_seller"]
    assert row["history_status"] == "Single observed day" and row["mean_interval_days"] == .25
    assert (cohort["interval_count"], cohort["interval_vehicles"]) == (1, 1)
    assert cohort["interval_status"] == "One observed interval"


def test_increases_and_unchanged_prices_do_not_reset_cut_intervals(conn):
    vid = vehicle(conn)
    history(conn, vid, [(day(1), 60000), (day(2), 58000), (day(3), 58000),
                        (day(4), 59000), (day(6), 56000)])
    row = price_insights.for_vehicle(conn, vid)["vehicle"]
    assert (row["drops_count"], row["increases_count"], row["total_reductions"], row["net_change"]) == (2, 1, 5000, -4000)
    assert (row["mean_cut"], row["median_cut"]) == (2500, 2500)
    assert row["mean_interval_days"] == 4 and row["interval_count"] == 1
    assert row["interval_status"] == "One observed interval"
    assert row["cuts"][1] == dict(previous_observed_at=day(4), detected_at=day(6), old_price=59000, new_price=56000, amount=3000)


def test_cohort_means_weight_every_cut_and_interval_with_support_counts(conn):
    first, second, flat, sparse, empty = [vehicle(conn, n) for n in range(1, 6)]
    history(conn, first, [(day(1), 60000), (day(2), 59000), (day(4), 58000), (day(8), 57000)])
    history(conn, second, [(day(1), 65000), (day(3), 61000), (day(9), 56000)])
    history(conn, flat, [(day(2), 50000), (day(9), 50000)])
    history(conn, sparse, [(day(5), 50000)])
    history(conn, empty, [(day(1), 0), (day(4), None)])
    cohort = price_insights.for_vehicle(conn, first)["rivian_seller"]
    assert (cohort["vehicle_count"], cohort["cut_bearing_vehicles"], cohort["total_cuts"]) == (5, 2, 5)
    assert (cohort["total_reductions"], cohort["mean_cut"], cohort["median_cut"]) == (12000, 2400, 1000)
    assert (cohort["interval_count"], cohort["interval_vehicles"], cohort["mean_interval_days"]) == (3, 2, 4)
    assert cohort["median_interval_days"] == 4
    assert (cohort["repeat_day_vehicles"], cohort["single_day_vehicles"], cohort["no_history_vehicles"]) == (3, 1, 1)
    assert (cohort["first_observed"], cohort["latest_observed"]) == (day(1), day(9))
    flat_row = next(row for row in cohort["vehicles"] if row["vehicle_id"] == flat)
    assert flat_row["history_status"] == "Repeat-day history" and flat_row["drops_count"] == 0
    assert flat_row["interval_count"] == 0 and flat_row["mean_interval_days"] is None


def test_official_seller_scope_and_demo_merged_exclusions(conn):
    current = vehicle(conn, 1, make="Ford")
    history(conn, current, [(day(1), 50000), (day(2), 49000)], seller="Independent Motors")
    for n, kwargs in enumerate([
        dict(source="rivian", seller=""),
        dict(url="https://preowned.rivian.com:443/item", seller=""),
        dict(seller="Rivian Tempe - Delivery Hub"),
        dict(seller="Independent Rivian Specialists"),
        dict(seller="Dealer", url="https://rivian.com.example.org/item"),
        dict(seller="Dealer", url="https://notrivian.com/item"),
        dict(seller="Dealer", url="https://rivian.com@dealer.example/item"),
    ], 2):
        history(conn, vehicle(conn, n), [(day(1), 65000), (day(2), 64000)], **kwargs)
    demo = vehicle(conn, 10, is_demo=1)
    history(conn, demo, [(day(1), 65000), (day(2), 1)], source="rivian")
    history(conn, vehicle(conn, 11), [(day(1), 65000), (day(2), 1)], is_demo=1)
    history(conn, vehicle(conn, 12), [(day(1), 65000), (day(2), 1)], import_method="demo")
    history(conn, vehicle(conn, 13, merged_into_id=current), [(day(1), 65000), (day(2), 1)], source="rivian")
    result = price_insights.for_vehicle(conn, current)
    assert result["vehicle"]["make"] == "Ford" and result["vehicle"]["total_reductions"] == 1000
    assert result["rivian_seller"]["vehicle_count"] == 3 and result["rivian_seller"]["total_reductions"] == 3000
    assert price_insights.for_vehicle(conn, demo)["vehicle"] is None
    assert price_insights.for_vehicle(conn, 999)["vehicle"] is None


def test_invalid_prices_dates_and_other_seller_observations_are_not_cohort_events(conn):
    vid = vehicle(conn)
    history(conn, vid, [(day(1), 65000), ("nonsense", 1), (day(2), 0), (day(3), -100),
                        (day(4), None), (day(5), 1000, "Independent Dealer"), (day(6), 64000)])
    result = price_insights.for_vehicle(conn, vid)
    cohort = result["rivian_seller"]["vehicles"][0]
    assert cohort["priced_observations"] == 2 and cohort["total_reductions"] == 1000
    assert cohort["observation_span_days"] == 5
    assert result["vehicle"] == cohort


def test_generic_history_uses_current_seller_and_allows_blank_seller_observations(conn):
    vid = vehicle(conn, make="Ford")
    history(conn, vid, [(day(1), 60000, "Previous Dealer"), (day(2), 50000, "Current Motors Inc"),
                        (day(3), 50000, ""), (day(4), 49000, "Current Motors")], seller="Current Motors LLC")
    row = price_insights.for_vehicle(conn, vid)["vehicle"]
    assert row["priced_observations"] == 3 and row["first_observed_price"] == 50000
    assert row["drops_count"] == 1 and row["total_reductions"] == 1000
    assert row["interval_count"] == 0 and row["mean_interval_days"] is None


def test_dates_normalize_utc_before_sorting_and_calendar_day_coverage(conn):
    vid = vehicle(conn)
    history(conn, vid, [("2026-01-03T00:00:00+00:00", 58000),
                        ("2026-01-01T20:00:00-07:00", 59000),
                        ("2026-01-01T01:00:00", 60000),
                        ("2026-01-03T12:00:00Z", 57000)])
    row = price_insights.for_vehicle(conn, vid)["vehicle"]
    assert row["first_observed"] == "2026-01-01T01:00:00Z" and row["observation_days"] == 3
    assert row["total_reductions"] == 3000 and row["interval_count"] == 2
    assert row["intervals_days"] == pytest.approx([21 / 24, 12 / 24])


def test_empty_history_is_insufficient_and_read_only(conn):
    vid = vehicle(conn)
    history(conn, vid, [])
    before = conn.total_changes
    result = price_insights.for_vehicle(conn, vid)
    assert conn.total_changes == before
    assert result["vehicle"]["history_status"] == "No priced history"
    assert result["vehicle"]["net_change"] is None and result["rivian_seller"]["net_change"] is None
    assert result["rivian_seller"]["mean_cut"] is None and result["rivian_seller"]["mean_interval_days"] is None
    assert result["rivian_seller"]["first_observed"] is None
    assert "not confirmed dealer" in result["caveat"]
