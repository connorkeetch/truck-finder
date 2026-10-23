"""Comparable EV pickups keep their own specifications, limits, and market peers."""
from datetime import date
from urllib.parse import unquote_plus

import pandas as pd
import pytest

from conftest import listing
from rivian_finder import adjust, attributes, deals, enrich, links, pipeline, queries, warranty
from rivian_finder.models import AttributeClaim


def truck(conn, make="Ford", model="F-150 Lightning", **kw):
    nl = listing("dealer", import_method="manual", make=make, model=model,
                 url=f"https://dealer.example/{make}/{conn.total_changes}", **kw)
    pipeline.import_listings(conn, [nl], "manual_entry")
    return conn.execute("SELECT MAX(id) FROM vehicles").fetchone()[0]


def test_other_brands_pass_rivian_equipment_filters_and_brand_search(conn, settings):
    truck(conn, attributes=[AttributeClaim("battery", "Extended Range", "medium", "listing"),
                            AttributeClaim("epa_range", "320", "medium", "listing"),
                            AttributeClaim("tow_capacity_lbs", "10000", "medium", "listing")])
    settings["filters"].update(batteries=["Max"], motors=["Quad"], generations=["Gen 2"], subframes=["cast"])
    frame = queries.inventory_frame(conn, settings)
    assert len(queries.apply_filters(frame, settings["filters"])) == 1
    assert len(queries.apply_filters(frame, settings["filters"], search="lightning")) == 1
    assert queries.apply_filters(frame, {**settings["filters"], "brands": ["Rivian"]}).empty
    assert len(queries.apply_filters(frame, {**settings["filters"], "brands": ["Ford"]})) == 1
    row = frame.iloc[0]
    assert row.tow_capacity_lbs == 10000 and row.tow_conf == "medium" and "Dealer" in row.tow_src
    assert pd.isna(row.epa_est_low) and not row.warranty_expires
    assert pd.isna(row.recall_count) and "warranty" not in row.adjust_note


@pytest.mark.parametrize("kw,visible", [
    ({"price": 65000, "miles": 45000}, True),
    ({"price": 65001}, False),
    ({"miles": 45001}, False),
    ({"price": None}, False),
    ({"miles": None}, False),
    ({"zip": "10001", "city": "New York", "state": "NY"}, False),
    ({"attributes": [AttributeClaim("epa_range", "300", "medium", "listing")]}, False),
    ({"attributes": [AttributeClaim("epa_range", "301", "medium", "listing")]}, True),
])
def test_comparison_limits_are_hard_even_with_near_misses(conn, settings, kw, visible):
    settings["filters"]["max_miles"] = 45000
    truck(conn, **kw)
    frame = queries.inventory_frame(conn, settings)
    assert bool(len(queries.apply_filters(frame, settings["filters"]))) == visible


def test_unknown_range_can_be_excluded_and_verified_specs_win(conn, settings):
    vid = truck(conn)
    frame = queries.inventory_frame(conn, settings)
    assert len(queries.apply_filters(frame, settings["filters"])) == 1
    strict = {**settings["filters"], "min_range": 301, "include_unknown_range": False}
    assert queries.apply_filters(frame, strict).empty
    attributes.set_override(conn, vid, "epa_range", "320")
    attributes.set_override(conn, vid, "tow_capacity_lbs", "7700")
    frame = queries.inventory_frame(conn, settings)
    assert len(queries.apply_filters(frame, strict)) == 1
    assert frame.iloc[0].tow_verified and frame.iloc[0].tow_capacity_lbs == 7700


def test_ice_pickups_do_not_enter_ev_view(conn, settings):
    truck(conn, "Ford", "F-150")
    truck(conn, "Chevrolet", "Silverado 1500")
    truck(conn, "GMC", "Sierra 1500")
    assert queries.apply_filters(queries.inventory_frame(conn, settings), settings["filters"]).empty


def test_non_rivian_warranty_requires_actual_dates_and_limits():
    assert not warranty.remaining("2025-01-01", 20000, use_rules=False)["known"]
    got = warranty.remaining("2025-01-01", 20000, comp_exp="2028-01-01", use_rules=False)
    assert got["comprehensive_miles_limit"] is None and got["battery_expires"] is None
    assert adjust.warranty_months({"make": "Ford", "year": 2025}, 12000) == (None, False)
    months, estimated = adjust.warranty_months(
        {"make": "Ford", "warranty_expires": "2028-01-01", "warranty_miles_limit": 36000, "miles": 35000},
        12000, today=date(2026, 10, 22))
    assert months == 1 and not estimated


def test_non_rivian_decode_never_infers_rivian_pack():
    claims = enrich.claims_from_mc_decode({"version": "Lariat", "electric_range": 352},
                                          2024, "Dual", "Ford", "F-150 Lightning")
    assert not any(c.field == "battery" for c in claims)
    assert any(c.field == "epa_range" and c.value == "352" for c in claims)


def test_spec_lookup_reads_installed_unit_specific_ratings_only():
    equipment = {"STANDARD": [{"attribute": "Towing capacity (lbs)", "value": "10000"}]}
    claims = enrich.claims_from_mc_decode({"installed_equipment": equipment,
        "available_options_details": {"tow_capacity_lbs": 14000}}, 2024, None, "Chevrolet", "Silverado EV")
    tow = [c for c in claims if c.field == "tow_capacity_lbs"]
    assert len(tow) == 1 and tow[0].value == "10000" and tow[0].source == "marketcheck_decode"


def test_deal_estimates_and_comparables_do_not_mix_models():
    from test_deals import market
    rivian = market().assign(make="Rivian", model="R1T")
    ford = market().assign(make="Ford", model="F-150 Lightning")
    ford["price"] += 20000
    mixed = pd.concat([rivian, ford], ignore_index=True)
    result = deals.annotate(mixed)
    expected = deals.annotate(rivian)
    pd.testing.assert_series_equal(result.loc[rivian.index, "market_price"], expected.market_price)
    n, median, _ = deals.comparables(mixed, pd.Series(True, index=mixed.index), 0)
    n_expected, median_expected, _ = deals.comparables(rivian, pd.Series(True, index=rivian.index), 0)
    assert (n, median) == (n_expected, median_expected)


def test_fallback_links_search_the_actual_truck():
    url = links.dealer_search_url("Example Motors", make="Ford", model="F-150 Lightning")
    assert "Ford F-150 Lightning" in unquote_plus(url) and "Rivian" not in url
