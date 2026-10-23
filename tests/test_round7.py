"""Warranty paste and rules, EPA estimates, seller discounts, near misses, uncertain battery, second opinions,
VIN lookup, sticky 'sold / dead link', and the 0,0-coordinates fix."""
from datetime import date

import pytest
from conftest import AttributeClaim, listing, vin

from rivian_finder import attributes, enrich, epa, finance, geo, hiding, pipeline, queries, repairs, services, warranty
from rivian_finder.extract import parse_warranty


def vid_for(conn, v):
    return conn.execute("SELECT id FROM vehicles WHERE vin=?", (v,)).fetchone()[0]


def row_for(conn, settings, v):
    inv = queries.inventory_frame(conn, settings)
    return inv[inv["vin"] == v].iloc[0]


# ------------------------------------------------------------------ warranty

USER_PASTE = """Comprehensive
Apr 2028 or 60k mi
Battery pack & drivetrain
Apr 2031 or 175k mi"""


@pytest.mark.parametrize("text", [USER_PASTE, "Comprehensive Apr 2028 or 60k mi · Battery pack & drivetrain Apr 2031 or 175,000 mi"])
def test_parse_warranty(text):
    # month-only dates count from the 1st (the conservative end of that month)
    assert parse_warranty(text) == {"warranty_expiration": "2028-04-01", "warranty_miles": 60000,
                                    "battery_warranty_expiration": "2031-04-01", "battery_warranty_miles": 175000}


def test_parse_warranty_ignores_unrelated_text():
    assert parse_warranty("Great truck, call 801-555-0100") == {}
    assert parse_warranty(None) == {}


@pytest.mark.parametrize("motor,battery,years,miles,batt_miles", [
    ("Dual", "Large", 4, 50000, 150000),          # Rivian pages: Dual + Large pack = 150k battery miles
    ("Dual", "Max", 4, 50000, 175000),
    ("Quad", "Large", 5, 60000, 175000),
    ("Dual", "Standard", 4, 50000, 150000),
])
def test_warranty_terms(motor, battery, years, miles, batt_miles):
    t = warranty.terms_for(motor, battery)
    assert (t["comp_years"], t["comp_miles"], t["battery_miles"]) == (years, miles, batt_miles)


def test_warranty_from_in_service_date_uses_motor_rule():
    r = warranty.remaining("2024-04-15", 21234, motor="Quad", battery="Large", today=date(2026, 10, 20))
    assert r["comprehensive_expires"] == "2029-04-15" and r["comprehensive_miles_left"] == 38766
    assert "5 yr / 60k (Quad)" in r["basis"]


def test_truck_warranty_dates_beat_the_rule():
    r = warranty.remaining(None, 21234, motor="Dual", today=date(2026, 10, 20), comp_exp="2028-04-01", comp_miles=60000,
                           batt_exp="2031-04-01", batt_miles=175000)
    assert r["known"] and r["basis"] == "the truck's warranty dates"
    assert r["summary"] == "17 mo, 38,766 mi (to Apr 2028)" and r["battery_miles_left"] == 153766


def test_warranty_expires_on_miles():
    r = warranty.remaining("2025-01-01", 51000, motor="Dual", today=date(2026, 10, 20))
    assert r["summary"] == "Comprehensive expired"


def test_inventory_warranty_from_override(conn, settings):
    v = vin(701)
    pipeline.import_listings(conn, [listing(vin=v, miles=20000)], "manual_entry")
    vid = vid_for(conn, v)
    for field, value in parse_warranty(USER_PASTE).items():
        attributes.set_override(conn, vid, field, str(value))
    row = row_for(conn, settings, v)
    assert row["warranty_basis"] == "the truck's warranty dates" and "to Apr 2028" in row["warranty"]


# ------------------------------------------------------------------ EPA range

def test_epa_estimate_with_and_without_wheels():
    assert epa.estimate(2024, "Dual", "Large", '21" Road')["text"] == "352"
    est = epa.estimate(2024, "Dual", "Large")
    assert (est["low"], est["high"]) == (307, 352) and "wheel size unknown" in est["basis"]
    assert epa.estimate(2024, "Dual", "Unknown")["text"] == ""


def test_epa_range_points_to_one_battery():
    assert epa.batteries_for_range(2024, "Dual", 352) == {"Large"}
    assert epa.batteries_for_range(2024, "Dual", 9999) == set()


# ------------------------------------------------------------------ seller discounts

A = finance.FinanceAssumptions(discounts=[{"seller": "carvana", "amount": 1000.0, "when": "trade"}])


def test_trade_discount_only_in_trade_scenarios():
    assert finance.discount_for(A, "carvana", "trade_low") == 1000
    assert finance.discount_for(A, "carvana", "cash_sale") == 0
    assert finance.discount_for(A, "carmax", "trade_low") == 0
    assert finance.scenario(64990, A, "trade_high", seller="carvana").price == 63990


def test_best_price():
    assert finance.best_price(64990, A, "carvana") == 63990
    assert finance.best_price(64990, A, None) == 64990
    assert finance.best_price(None, A, "carvana") is None


# ------------------------------------------------------------------ filters, near misses, why hidden, lookup

def _filters(settings, **kw):
    return {**settings["filters"], "max_price": 65000, "max_miles": 40000, "near_misses": True,
            "near_miss_price_pct": 5, "near_miss_miles_pct": 10, "count_discounts": True, "states": [],
            "max_distance": 0, **kw}


@pytest.fixture
def carvana_truck(conn, settings):
    """The real-world case: $65,590 at Carvana, $1,000 off with a trade → $64,590."""
    v = vin(702)
    pipeline.import_listings(conn, [listing(vin=v, price=65590, url="https://www.carvana.com/vehicle/4596079",
                                            seller_name="Carvana", trim="Dual Large")], "manual_entry")
    return v


def test_discount_brings_truck_under_max(conn, settings, carvana_truck):
    inv = queries.inventory_frame(conn, settings)
    row = inv[inv["vin"] == carvana_truck].iloc[0]
    assert row["your_price"] == 64590
    f = _filters(settings, near_misses=False)
    assert carvana_truck in set(queries.apply_filters(inv, f)["vin"])
    assert carvana_truck not in set(queries.apply_filters(inv, {**f, "count_discounts": False})["vin"])


def test_near_miss_shows_and_explains(conn, settings, carvana_truck):
    inv = queries.inventory_frame(conn, settings)
    f = _filters(settings, count_discounts=False)
    assert bool(queries.near_miss_mask(inv, f)[inv["vin"] == carvana_truck].iloc[0])
    assert carvana_truck in set(queries.apply_filters(inv, f)["vin"])
    why = queries.why_hidden(inv[inv["vin"] == carvana_truck].iloc[0], {**f, "near_misses": False})
    assert why == ["price $65,590 is $590 over your $65,000 max"]
    assert carvana_truck not in set(queries.apply_filters(inv, {**f, "near_miss_price_pct": 0})["vin"])


def test_near_miss_is_only_for_price_and_miles(conn, settings):
    v = vin(703)
    pipeline.import_listings(conn, [listing(vin=v, price=66000, trim="Dual Standard")], "manual_entry")
    inv = queries.inventory_frame(conn, settings)
    f = _filters(settings, batteries=["Large", "Max"])
    assert v not in set(queries.apply_filters(inv, f)["vin"])
    reasons = queries.why_hidden(inv[inv["vin"] == v].iloc[0], {**f, "near_misses": False})
    assert any(r.startswith("battery is Standard") for r in reasons) and any(r.startswith("price") for r in reasons)


def test_find_trucks_by_vin_url_or_number(conn, settings, carvana_truck):
    inv = queries.inventory_frame(conn, settings)
    for q in (carvana_truck, carvana_truck.lower(), "https://www.carvana.com/vehicle/4596079?utm=x", "4596079"):
        assert list(queries.find_trucks(inv, q)["vin"]) == [carvana_truck], q
    assert queries.find_trucks(inv, "https://www.carvana.com/vehicle/1111111").empty


# ------------------------------------------------------------------ uncertain battery

def test_disputed_battery_is_uncertain_and_never_filtered_out(conn, settings):
    v = vin(704)
    pipeline.import_listings(conn, [listing(vin=v, trim="Dual Large", attributes=[
        AttributeClaim("battery", "Standard", "medium", "Auto.dev structured vehicle fields", evidence="Standard Pack")])],
        "manual_entry")
    row = row_for(conn, settings, v)
    assert row["battery_uncertain"] and set(row["battery_options"]) == {"Standard", "Large"}
    assert "spec text" in row["battery_note"] and "trim name" in row["battery_note"]
    assert "battery uncertain" in row["epa_basis"]
    inv = queries.inventory_frame(conn, settings)
    for allowed in (["Large", "Max"], ["Standard"]):
        assert v in set(queries.apply_filters(inv, _filters(settings, batteries=allowed))["vin"]), allowed
    assert v not in set(queries.apply_filters(inv, _filters(settings, batteries=["Max"]))["vin"])


def test_your_battery_choice_ends_the_uncertainty(conn, settings):
    v = vin(705)
    pipeline.import_listings(conn, [listing(vin=v, trim="Dual Large", attributes=[
        AttributeClaim("battery", "Standard", "medium", "Auto.dev structured vehicle fields")])], "manual_entry")
    attributes.set_override(conn, vid_for(conn, v), "battery", "Large", "Window sticker")
    row = row_for(conn, settings, v)
    assert row["battery"] == "Large" and not row["battery_uncertain"] and row["battery_note"] == ""


def test_majority_of_independent_sources_wins(conn):
    v = vin(706)
    pipeline.import_listings(conn, [listing(vin=v)], "manual_entry")
    vid = vid_for(conn, v)
    attributes.record_claims(conn, vid, [
        AttributeClaim("battery", "Large", "medium", "Listing trim name", source="autodev"),
        AttributeClaim("battery", "Large", "medium", "MarketCheck structured build fields", source="marketcheck")],
        now="2026-10-01T00:00:00Z")
    attributes.record_claims(conn, vid, [AttributeClaim("battery", "Standard", "medium", "Auto.dev structured vehicle fields",
                                                        source="autodev_style")], now="2026-10-20T00:00:00Z")
    assert attributes.resolve(conn, vid)["battery"].value == "Large"


def test_reread_trim_names_repair(conn):
    v = vin(707)
    pipeline.import_listings(conn, [listing(vin=v)], "manual_entry")
    vid = vid_for(conn, v)
    attributes.record_claims(conn, vid, [AttributeClaim("trim", "Tri Max Pickup 4D", "medium", "Listing", source="autodev")])
    conn.execute("DELETE FROM vehicle_attributes WHERE vehicle_id=? AND field IN ('battery', 'motor')", (vid,))
    conn.execute("DELETE FROM preferences WHERE key='repair:2026-10-reread-config-names'")
    assert repairs.reread_trim_names(conn)["added"] >= 2
    res = attributes.resolve(conn, vid)
    assert (res["battery"].value, res["motor"].value) == ("Max", "Tri")
    assert repairs.reread_trim_names(conn) == {}          # once only


# ------------------------------------------------------------------ MarketCheck second opinion

def test_claims_from_mc_decode_version_text():
    claims = enrich.claims_from_mc_decode({"version": "Adventure Dual-Motor Large Pack", "electric_range": 352,
                                           "record_source": "used_mc_listing"}, 2024, "Dual")
    got = {(c.field, c.value, c.source) for c in claims}
    assert ("battery", "Large", "marketcheck_decode") in got and ("epa_range", "352", "marketcheck_decode") in got
    assert not any(c.source == "epa_match" for c in claims)       # version already named the pack
    assert any(c.field == "mc_decoded" for c in claims)


def test_claims_from_mc_decode_infers_pack_from_epa_range():
    claims = enrich.claims_from_mc_decode({"version": "Adventure", "electric_range": 352}, 2024, "Dual")
    inferred = [c for c in claims if c.source == "epa_match"]
    assert [(c.field, c.value, c.confidence) for c in inferred] == [("battery", "Large", "low")]


def test_mc_second_opinion_records_claims(conn, monkeypatch):
    from rivian_finder.sources import marketcheck
    v = vin(708)
    pipeline.import_listings(conn, [listing(vin=v, trim="Dual Standard")], "manual_entry")
    vid = vid_for(conn, v)
    calls = []

    def fake_get_json(self, url, params=None, **kw):
        calls.append(url)
        return {"version": "Adventure Dual-Motor Large Pack", "electric_range": 352}

    monkeypatch.setattr(marketcheck.MarketCheckAdapter, "get_json", fake_get_json)
    out = enrich.mc_second_opinion(conn, vid, api_key="test-key")
    assert out["ok"] and ("battery", "Large") in out["claims"]
    assert len(calls) == 1 and calls[0].endswith(f"/neovin/{v}/specs")
    sources = {a["source"] for a in attributes.resolve(conn, vid)["battery"].alternatives}
    assert "marketcheck_decode" in sources


def test_mc_second_opinion_needs_a_key(conn, monkeypatch):
    from rivian_finder import credentials
    monkeypatch.setattr(credentials, "get_api_key", lambda name: (None, ""))
    v = vin(709)
    pipeline.import_listings(conn, [listing(vin=v)], "manual_entry")
    assert enrich.mc_second_opinion(conn, vid_for(conn, v)) == {"ok": False, "error": "no MarketCheck API key"}


# ------------------------------------------------------------------ VIN lookup (Auto.dev, 1 call)

class FakeAutoDev:
    def __init__(self, result=None, configured=True, error=None):
        self.result, self.configured, self.error = result, configured, error

    def is_configured(self):
        return (self.configured, "" if self.configured else "no Auto.dev key")

    def lookup_vin(self, v):
        if self.error:
            raise self.error
        return self.result


def test_lookup_vin_adds_the_truck(conn, monkeypatch):
    v = vin(710)
    monkeypatch.setattr(services, "make_adapter", lambda c, k: FakeAutoDev(listing(vin=v, title="2024 Rivian R1T")))
    assert services.lookup_vin(conn, v) == {"found": True, "title": "2024 Rivian R1T"}
    assert conn.execute("SELECT COUNT(*) FROM vehicles WHERE vin=?", (v,)).fetchone()[0] == 1


@pytest.mark.parametrize("fake,expected", [
    (FakeAutoDev(None), {"found": False}),
    (FakeAutoDev(configured=False), {"found": False, "error": "no Auto.dev key"}),
    (FakeAutoDev(error=RuntimeError("HTTP 500")), {"found": False, "error": "HTTP 500"}),
])
def test_lookup_vin_failures(conn, monkeypatch, fake, expected):
    monkeypatch.setattr(services, "make_adapter", lambda c, k: fake)
    assert services.lookup_vin(conn, vin(711)) == expected


# ------------------------------------------------------------------ sold / dead link sticks

def test_sold_dead_link_survives_the_next_search(conn):
    v = vin(712)
    nl = listing(vin=v, url="https://eastbay.example/1")
    pipeline.import_listings(conn, [nl], "manual_entry")
    vid = vid_for(conn, v)
    hiding.hide_vehicle(conn, vid, "sold", "page gone")
    assert hiding.reason_label("sold") == "Sold / dead link"
    pipeline.import_listings(conn, [listing(vin=v, url="https://eastbay.example/1")], "manual_entry")
    status, reason = conn.execute("SELECT status, status_reason FROM listings WHERE vehicle_id=?", (vid,)).fetchone()
    assert status == "removed" and reason.startswith("Marked")
    assert conn.execute("SELECT COUNT(*) FROM change_events WHERE vehicle_id=? AND event_type='returned'",
                        (vid,)).fetchone()[0] == 0


# ------------------------------------------------------------------ 0,0 coordinates

def test_zero_coordinates_fall_back_to_zip():
    assert not geo.usable_coords(0.0, 0.0) and not geo.usable_coords(None, 1.0) and not geo.usable_coords("x", 1)
    assert geo.usable_coords("36.17", "-115.14")
    by_zip = geo.distance_from_zip("84020", None, None, "89101")
    assert 300 < by_zip < 400 and geo.distance_from_zip("84020", 0.0, 0.0, "89101") == by_zip


def test_clear_zero_coords_repair(conn, settings):
    v = vin(713)
    pipeline.import_listings(conn, [listing(vin=v, zip="89101", city="Las Vegas", state="NV")], "manual_entry")
    conn.execute("UPDATE listings SET lat=0, lon=0")
    conn.execute("DELETE FROM preferences WHERE key='repair:2026-10-zero-coords'")
    assert repairs.clear_zero_coords(conn) == {"cleared": 1}
    assert tuple(conn.execute("SELECT lat, lon FROM listings").fetchone()) == (None, None)
    assert 300 < row_for(conn, settings, v)["distance_mi"] < 400


def test_self_contradicting_spec_text_keeps_both_packs():
    from rivian_finder.extract import extract_attributes
    text = "Dual Standard Pickup 4D · Adventure w/Performance Dual-Motor, Max Pack (electric DD)"
    assert {c.value for c in extract_attributes(text, "spec", structured=True) if c.field == "battery"} == {"Max", "Standard"}
    assert [c.value for c in extract_attributes(text, "desc") if c.field == "battery"] == ["Max"]
    assert [c.value for c in extract_attributes("Dual Large+ Pickup", "spec", structured=True)
            if c.field == "battery"] == ["Large+"]


def test_warranty_ends_text():
    assert warranty.ends_text("2028-04-01", 60000) == "Apr 2028 · 60k mi"
    assert warranty.ends_text("2028-04-15", None) == "Apr 2028"
    assert warranty.ends_text("", 50000) == "" and warranty.ends_text(None, None) == ""
    r = warranty.remaining("2024-04-15", 1000, motor="Dual", today=date(2026, 10, 20))
    assert (r["comprehensive_expires"], r["comprehensive_miles_limit"]) == ("2028-04-15", 50000)


def test_fast_comparables_match_the_definition():
    import numpy as np
    import pandas as pd
    from rivian_finder import deals
    rng = np.random.default_rng(7)
    n = 60
    df = pd.DataFrame({"year": rng.choice([2023, 2024, np.nan], n), "miles": rng.integers(5000, 40000, n).astype(float),
                       "motor": rng.choice(["Dual", "Quad", "Unknown"], n), "price": rng.integers(50000, 70000, n)},
                      index=range(100, 100 + n))
    pool = pd.Series(rng.random(n) > 0.3, index=df.index)
    for i in df.index:
        r = df.loc[i]
        got = deals.comparables(df, pool, i)
        if pd.isna(r["year"]):
            assert got == (0, None, "")
            continue
        m = pool & (df.index != i) & (df["year"] == r["year"]) & ((df["miles"] - r["miles"]).abs() <= 10000)
        if r["motor"] != "Unknown":
            m &= df["motor"] == r["motor"]
        assert got[0] == int(m.sum())
        assert got[1] == (float(df.loc[m, "price"].median()) if m.any() else None)


def test_manual_tonneau_means_no_powered_tonneau():
    from rivian_finder.extract import classify_tonneau
    status, evidence, _ = classify_tonneau("* OEM manual tonneau cover with storage bag * OEM field kit")
    assert status == "no" and "Manual" in evidence
    assert classify_tonneau("Soft roll-up tonneau, tow package")[0] == "no"
    assert classify_tonneau("Powered tonneau with manual release")[0] == "yes"


def test_distance_falls_back_to_city_when_no_zip():
    near = geo.distance_from_zip("84020", None, None, None, "Encinitas", "CA")
    assert 550 < near < 650          # straight line; AutoTempest shows 592 mi for neighbouring Carlsbad
    assert geo.distance_from_zip("84020", None, None, None, "Nowhereville", "CA") is None
