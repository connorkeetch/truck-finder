"""Adjusted price: your price + shipping − what features are worth to you."""
from conftest import listing, vin

from rivian_finder import adjust, attributes, pipeline, queries

CFG = {"include_shipping": True, "rules": [
    {"field": "color", "match": "white", "amount": 1000}, {"field": "color", "match": "silver", "amount": 2000},
    {"field": "tonneau", "match": "yes", "amount": 500}, {"field": "battery", "match": "Max", "amount": 1000},
    {"field": "subframe", "match": "welded", "amount": -2000}]}


def test_white_truck_with_tonneau_and_shipping():
    row = {"price": 65000, "your_price": 65000, "transport_cost": 990, "color": "Glacier White", "tonneau": "yes",
           "battery": "Large", "subframe": "cast"}
    price, note = adjust.adjusted(row, CFG)
    assert price == 65000 + 990 - 1000 - 500
    assert note == "+$990 shipping · −$1,000 white · −$500 powered tonneau"


def test_discount_negative_amounts_and_uncertain_battery():
    row = {"price": 60990, "your_price": 59990, "transport_cost": 0, "color": "LA Silver", "battery": "Max",
           "battery_uncertain": True, "subframe": "welded"}
    price, note = adjust.adjusted(row, CFG)
    assert price == 59990 - 2000 + 2000                      # silver −2k, welded +2k, Max not credited (uncertain)
    assert "Max" not in note and "+$2,000 welded subframe" in note


def test_shipping_can_be_left_out_and_no_price_means_none():
    row = {"price": 60000, "transport_cost": 1450, "color": "Midnight"}
    assert adjust.adjusted(row, {**CFG, "include_shipping": False}) == (60000, "")
    assert adjust.adjusted({"price": None}, CFG) == (None, "")


def test_inventory_has_adjusted_price(conn, settings):
    v = vin(961)
    pipeline.import_listings(conn, [listing("dealer", import_method="manual", vin=v, price=62000, zip="84020",
                                            url="https://d.example/vdp/961", exterior_color="Glacier White")], "manual_entry")
    vid = conn.execute("SELECT id FROM vehicles WHERE vin=?", (v,)).fetchone()[0]
    attributes.set_override(conn, vid, "tonneau", "yes")
    row = queries.inventory_frame(conn, {**settings, "adjustments": CFG}).iloc[0]
    assert row["adjusted_price"] == 62000 - 1000 - 500 and "white" in row["adjust_note"]     # local pickup: no shipping


from datetime import date  # noqa: E402

TODAY = date(2026, 10, 22)
WV = {"rules": [], "include_shipping": False,
      "warranty_value": {"enabled": True, "per_month": 100, "baseline": "2028-06-01", "annual_miles": 12000}}


def test_warranty_months_date_miles_and_estimate():
    # Rivian page: comprehensive to Apr 2028 or 60k; 21,234 mi → date binds (17 mo) before miles (38.8k mi ≈ 38 mo)
    m, est = adjust.warranty_months({"warranty_expires": "2028-04-01", "warranty_miles_limit": 60000, "miles": 21234},
                                    12000, today=TODAY)
    assert (round(m), est) == (17, False)
    # Sparks Dual: Dec 2027 or 50k at 40,195 mi → 9,805 mi left ≈ 9.8 months at 12k/yr — miles bind first
    m, _ = adjust.warranty_months({"warranty_expires": "2027-12-01", "warranty_miles_limit": 50000, "miles": 40195},
                                  12000, today=TODAY)
    assert round(m, 1) == 9.8
    # unknown dates: 2024 Quad estimated in service Jul 2024 + 5 yr / 60k
    m, est = adjust.warranty_months({"year": 2024, "motor": "Quad", "miles": 10000}, 12000, today=TODAY)
    assert est and round(m) == 32
    assert adjust.warranty_months({"warranty_expires": "2025-01-01", "miles": 1000}, 12000, today=TODAY)[0] == 0
    assert adjust.warranty_months({}, 12000, today=TODAY) == (None, False)


def test_warranty_value_in_adjusted_price():
    longer = {"price": 60000, "warranty_expires": "2029-05-01", "warranty_miles_limit": 60000, "miles": 20000}
    shorter = {"price": 60000, "warranty_expires": "2027-09-01", "warranty_miles_limit": 50000, "miles": 31942}
    p1, n1 = adjust.adjusted(longer, WV, today=TODAY)
    p2, n2 = adjust.adjusted(shorter, WV, today=TODAY)
    assert p1 == 60000 - 1100 and "−$1,100 warranty (+11 mo vs Jun 2028)" == n1
    assert p2 == 60000 + 900 and n2 == "+$900 warranty (−9 mo vs Jun 2028)"
    est_price, est_note = adjust.adjusted({"price": 60000, "year": 2023, "motor": "Dual", "miles": 30000}, WV, today=TODAY)
    assert "est." in est_note
    off = {**WV, "warranty_value": {**WV["warranty_value"], "enabled": False}}
    assert adjust.adjusted(longer, off, today=TODAY) == (60000, "")


RV = {"enabled": True, "ok_at": 320, "per_mile": 40, "floor": 300, "per_mile_below_floor": 60}


def test_range_penalty_tiers():
    assert adjust.range_penalty(328, RV) == 0                    # Quad Large on 21"
    assert adjust.range_penalty(307, RV) == 13 * 40              # Dual Large on 20" all-terrain
    assert adjust.range_penalty(289, RV) == 31 * 40 + 11 * 60    # Quad Large on 20" → $1,900


def test_effective_range_priority_and_guards():
    exact = {"epa_est_low": 289, "epa_est_high": 289, "epa_range": 328}
    assert adjust.effective_range(exact) == (289, "EPA")                       # wheels known beats the listing
    assert adjust.effective_range({**exact, "epa_range_verified": True}) == (328, "your range")
    bad_listing = {"epa_est_low": 341, "epa_est_high": 352, "epa_range": 270}
    assert adjust.effective_range(bad_listing) == (346.5, "est.")              # impossible for the config
    assert adjust.effective_range({"epa_est_low": 270, "epa_est_high": 352, "epa_range": 270,
                                   "battery_uncertain": True}) == (311, "est.")  # disputed pack: middle
    assert adjust.effective_range({"epa_range": 315}) == (315, "listed")
    assert adjust.effective_range({}) == (None, "")


def test_range_in_adjusted_price():
    cfg = {"rules": [], "include_shipping": False, "range_value": RV}
    price, note = adjust.adjusted({"price": 54000, "epa_est_low": 289, "epa_est_high": 289}, cfg)
    assert price == 55900 and note == "+$1,900 range (289 mi EPA)"


def test_unconfirmed_values_are_never_priced_and_get_a_confirm_tag():
    cfg = {"rules": [{"field": "subframe", "match": "unsure", "amount": -1500},
                     {"field": "subframe", "match": "welded", "amount": -3500}],
           "include_shipping": False, "range_value": RV}
    assert adjust.adjusted({"price": 50000, "subframe": "unsure"}, cfg) == (50000, "")
    assert adjust.adjusted({"price": 50000, "subframe": "welded"}, cfg)[0] == 53500
    assert adjust.to_confirm({"subframe": "unsure", "battery_uncertain": True}, cfg) == ["frame", "battery"]
    assert adjust.to_confirm({"subframe": "cast"}, cfg) == []


def test_estimated_range_only_penalizes_the_best_case():
    cfg = {"rules": [], "include_shipping": False, "range_value": RV}
    quad_unknown_wheels = {"price": 54000, "epa_est_low": 289, "epa_est_high": 328, "subframe": "cast"}
    assert adjust.adjusted(quad_unknown_wheels, cfg) == (54000, "")             # could be 328 on 21" wheels
    assert adjust.to_confirm(quad_unknown_wheels, cfg) == ["wheels"]
    low_span = {"price": 54000, "epa_est_low": 270, "epa_est_high": 310}
    assert adjust.adjusted(low_span, cfg) == (54400, "+$400 range (310 mi best case)")  # certain part only
    assert adjust.to_confirm({"epa_est_low": 355, "epa_est_high": 410}, cfg) == []   # every wheel option is fine
    assert adjust.to_confirm({**quad_unknown_wheels, "wheels": '20" Road wheels'}, cfg) == []


def test_2023_max_uses_the_2024_ratings():
    from rivian_finder import epa
    est = epa.estimate(2023, "Performance Dual", "Max", '20" All-Terrain wheels')
    assert (est["low"], est["high"]) == (355, 355) and "no 2023 Max rating" in est["basis"]
    assert epa.estimate(2024, "Dual", "Max")["text"] == "355–410"
    assert epa.estimate(2023, "Quad", "Large", '20" wheels')["low"] == 289             # own year when rated
