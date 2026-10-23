"""Generic searches retain vehicle identity and never borrow EV-truck assumptions."""
import pytest

from conftest import FakeAdapter, listing
from rivian_finder import adjust, dedup, pipeline, queries
from rivian_finder.extract import parse_year
from rivian_finder.importers import manual
from rivian_finder.models import AttributeClaim, FetchResult


def generic(settings):
    settings["collection"].update(searches=[{"make": "Toyota", "model": "Tacoma"}],
                                  exclude_standard_range=False, excluded_trims={}, max_distance=0)
    settings["filters"].update(year_min=1990, year_max=2027, max_miles=100000, max_price=65000,
                               brands=[], models=[], near_misses=False)
    return settings


def add(conn, make="Toyota", model="Tacoma", **kw):
    nl = listing("dealer", import_method="manual", make=make, model=model,
                 url=f"https://dealer.example/{conn.total_changes}", **kw)
    pipeline.import_listings(conn, [nl], "manual_entry")


def test_generic_inventory_accepts_non_ev_and_model_filter(conn, settings):
    generic(settings)
    add(conn, year=2015, zip=None, city=None, state=None)
    add(conn, "Honda", "Civic", year=2008)
    frame = queries.inventory_frame(conn, settings)
    assert len(queries.apply_filters(frame, settings["filters"])) == 2
    selected = queries.apply_filters(frame, {**settings["filters"], "models": ["civic"]})
    assert selected["make"].tolist() == ["Honda"]
    assert queries.apply_filters(frame, {**settings["filters"], "brands": ["Toyota"]})["model"].tolist() == ["Tacoma"]
    assert frame["epa_est_low"].isna().all() and frame["recall_count"].isna().all()
    assert not frame["warranty_expires"].any()
    assert all("frame" not in value for value in frame["to_confirm"])


def test_custom_search_keeps_explicit_ev_exclusions(conn, settings):
    generic(settings)
    settings["collection"]["exclude_standard_range"] = True
    add(conn, "Chevrolet", "Silverado EV", trim="LT Standard Range")
    assert queries.apply_filters(queries.inventory_frame(conn, settings), settings["filters"]).empty


def test_generic_ranking_does_not_reward_rivian_equipment(conn, settings):
    generic(settings)
    add(conn, attributes=[AttributeClaim("battery", "Max", "medium", "test"),
                          AttributeClaim("motor", "Quad", "medium", "test"),
                          AttributeClaim("tonneau", "yes", "medium", "test")])
    add(conn, "Honda", "Civic")
    frame = queries.inventory_frame(conn, settings)
    assert frame["fit_score"].nunique() == 1
    assert all("tonneau" not in text for text in frame["fit_breakdown"])


def test_custom_search_only_ingests_exact_pairs(conn):
    candidates = [listing(sid="ok", make="Toyota", model="Tacoma"),
                  listing(sid="wrong-model", make="Toyota", model="Camry"),
                  listing(sid="wrong-make", make="Ford", model="Tacoma")]
    adapter = FakeAdapter("autodev", [FetchResult(candidates, True, "custom")])
    summary = pipeline.run_search(conn, [adapter], {"searches": [{"make": "Toyota", "model": "Tacoma"}]})
    assert summary["sources"][0]["listings_seen"] == 1
    assert [r[0] for r in conn.execute("SELECT model FROM vehicles")] == ["Tacoma"]


def test_custom_scan_does_not_mark_unsearched_model_missing(conn):
    pipeline.import_listings(conn, [listing(sid="one", make="Toyota", model="Tacoma"),
                                    listing(sid="two", make="Toyota", model="Camry")], "manual_entry")
    adapter = FakeAdapter("autodev", [FetchResult([], True, "custom")])
    pipeline.run_search(conn, [adapter], {"searches": [{"make": "Toyota", "model": "Tacoma"}]})
    states = dict(conn.execute("SELECT source_listing_id, status FROM listings"))
    assert states == {"one": "missing", "two": "active"}


@pytest.mark.parametrize("year", [1997, 2010, 2020, 2026])
def test_older_models_import_without_year_or_brand_replacement(year):
    nl = manual.listing_from_fields({"make": "Honda", "model": "Civic", "description": f"{year} Honda Civic"})
    assert (nl.make, nl.model, nl.year) == ("Honda", "Civic", year)
    assert parse_year(str(year)) == year


def test_non_rivian_confirmation_does_not_request_subframe():
    assert adjust.to_confirm({"make": "Toyota", "model": "Tacoma", "subframe": "unknown"}) == []


def test_r1s_does_not_use_r1t_warranty_valuation():
    assert adjust.warranty_months({"make": "Rivian", "model": "R1S", "year": 2025}, 12000) == (None, False)


def test_same_model_name_from_different_makes_is_not_a_duplicate_candidate(conn):
    add(conn, "Ram", "1500")
    add(conn, "Chevrolet", "1500")
    assert conn.execute("SELECT COUNT(*) FROM match_candidates").fetchone()[0] == 0
    assert dedup.score_pair({"v_make": "Ram"}, {"v_make": "Chevrolet"}) == (0.0, ["different makes"])


def test_generic_gas_vehicle_does_not_use_ev_fly_drive_costs(conn, settings):
    generic(settings)
    settings["shipping"]["fly_drive"]["enabled"] = True
    add(conn, zip="89101", city="Las Vegas", state="NV")
    row = queries.inventory_frame(conn, settings).iloc[0]
    assert row["transport_basis"].startswith("Shipping est.")
