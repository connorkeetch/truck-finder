"""Personal saved limits keep API queries narrow and unknown stored mileage eligible."""
import copy

import pandas as pd
import pytest

from conftest import listing
from rivian_finder import pipeline, queries
from rivian_finder.sources import autodev, marketcheck
from rivian_finder.sources.base import collection_scopes


@pytest.fixture
def personal_settings(settings):
    saved = copy.deepcopy(settings)
    saved["collection"].update(searches=[{"make": "Rivian", "model": "R1T"}],
                               make="Rivian", model="R1T", year_min=2023, year_max=2026,
                               max_miles=44999, include_other_brands=False)
    saved["filters"].update(brands=["Rivian"], models=["R1T"], year_min=2023,
                            max_miles=44999, max_price=65000, near_misses=True,
                            near_miss_miles_pct=0, near_miss_price_pct=5)
    return saved


@pytest.mark.parametrize("provider, builder, miles_key, year_key, expected_years", [
    ("autodev", autodev.build_params, "retailListing.miles", "vehicle.year", "2023-2026"),
    ("marketcheck", marketcheck.build_params, "miles_range", "year", "2023,2024,2025,2026"),
])
def test_personal_collection_has_one_r1t_query_with_inclusive_44999_cap(
        personal_settings, provider, builder, miles_key, year_key, expected_years):
    scope = {**personal_settings["collection"], "home_zip": personal_settings["home_zip"]}
    scopes = collection_scopes(scope, provider)
    assert len(scopes) == 1
    assert (scopes[0]["make"], scopes[0]["model"], scopes[0]["year_min"], scopes[0]["max_miles"]) == (
        "Rivian", "R1T", 2023, 44999)
    params = builder(scopes[0])
    assert params[miles_key] == "0-44999" and params[year_key] == expected_years
    prefix = "vehicle." if provider == "autodev" else ""
    assert params[prefix + "make"] == "Rivian" and params[prefix + "model"] == "R1T"


def test_stored_inventory_enforces_strict_mileage_while_preserving_price_near_misses(conn, personal_settings):
    cases = [
        ("boundary", {"year": 2023, "miles": 44999}),
        ("unknown", {"miles": None}),
        ("exactly_45000", {"miles": 45000}),
        ("above_45000", {"miles": 45001}),
        ("older_year", {"year": 2022, "miles": 10000}),
        ("other_model", {"model": "R1S", "miles": 10000}),
        ("other_make", {"make": "Ford", "model": "F-150 Lightning", "miles": 10000}),
        ("price_near", {"miles": 44999, "price": 66000}),
        ("price_near_unknown_miles", {"miles": None, "price": 66000}),
        ("price_and_mileage_over", {"miles": 45000, "price": 66000}),
    ]
    # Manual imports deliberately preserve all cases; these assertions exercise display eligibility.
    pipeline.import_listings(conn, [listing("dealer", sid=name, import_method="manual", vin=None,
                                           url=f"https://dealer.example/{name}", **values)
                                    for name, values in cases], "manual_entry")
    inventory = queries.inventory_frame(conn, personal_settings)
    assert len(inventory) == len(cases)
    inventory["case"] = inventory["url"].str.rsplit("/", n=1).str[-1]
    filtered = queries.apply_filters(inventory, personal_settings["filters"])
    assert set(filtered["case"]) == {"boundary", "unknown", "price_near", "price_near_unknown_miles"}
    checks = pd.DataFrame(queries.filter_checks(inventory, personal_settings["filters"])).set_axis(inventory["case"])
    keyed = inventory.set_index("case")
    for case in ("exactly_45000", "above_45000", "price_and_mileage_over"):
        assert not checks.loc[case, "miles"]
    assert not checks.loc["older_year", "year"]
    assert not checks.loc["other_model", "selected model"]
    assert not checks.loc["other_make", "brand"]
    assert pd.isna(keyed.loc["unknown", "miles"])
    near = inventory.loc[queries.near_miss_mask(inventory, personal_settings["filters"])]
    assert set(near["case"]) == {"price_near", "price_near_unknown_miles"}
