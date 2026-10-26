"""Personal fit separates verified requirements, advertised preferences and common shopping limits."""
import copy

import numpy as np
import pandas as pd
import pytest

from conftest import listing, vin
from rivian_finder import attributes, config, matching, pipeline, queries
from rivian_finder.attributes import Resolved
from rivian_finder.models import AttributeClaim


@pytest.fixture
def preferences():
    return {"filters": {"max_price": 50000, "max_miles": 45000, "max_distance": 650, "count_discounts": True},
            "shopping_profile": copy.deepcopy(config.default_settings()["shopping_profile"])}


@pytest.fixture
def row():
    return {"make": "Ford", "model": "F-150 Lightning", "price": 25000, "miles": 22500,
            "distance_mi": 325, "epa_range": 320, "tow_capacity_lbs": 10000}


def claim(field, value, verified=False, **kwargs):
    return Resolved(field, value, source="user" if verified else "dealer", confidence="verified" if verified else "medium",
                    method="Window sticker" if verified else "Listing description", **kwargs)


def test_saved_settings_receive_a_neutral_profile_and_outputs_are_lists(row):
    stored = {"filters": {"max_price": 50000}}
    before = copy.deepcopy(stored)
    settings = config.merge_settings(stored)
    assert settings["shopping_profile"] == {"range_min": 0, "range_priority": "prefer", "tow_min": 0,
                                             "tow_priority": "must", "must_have": [], "prefer": []}
    assert settings["filters"]["match_statuses"] == [] and stored == before
    result = matching.evaluate(row, {"filters": {"max_price": 50000}})
    assert result["match_status"] == "Meets requirements"
    assert all(isinstance(result[key], list) for key in ("match_reasons", "match_missing", "match_failures", "match_preferred"))
    assert "condition and title" in " ".join(result["match_reasons"])


@pytest.mark.parametrize("make,model", [("Rivian", "R1T"), ("Ford", "F-150 Lightning"),
                                       ("Chevrolet", "Silverado EV"), ("GMC", "Sierra EV")])
def test_common_score_has_no_brand_pack_motor_or_tonneau_bias(row, preferences, make, model):
    result = matching.evaluate({**row, "make": make, "model": model, "battery": "Max", "motor": "Quad", "tonneau": "yes"}, preferences)
    assert result["match_status"] == "Meets requirements" and result["match_score"] == 50


@pytest.mark.parametrize("field,limit,value", [("price", "max_price", 50001), ("miles", "max_miles", 45001),
                                              ("distance_mi", "max_distance", 651)])
def test_known_advertised_limit_failures_are_definitive(row, preferences, field, limit, value):
    result = matching.evaluate({**row, field: value}, preferences)
    assert result["match_status"] == "Does not qualify" and result["match_failures"]
    assert 0 <= result["match_score"] <= 100


@pytest.mark.parametrize("field", ["price", "miles", "distance_mi"])
@pytest.mark.parametrize("value", [None, np.nan, pd.NA])
def test_required_missing_basics_need_verification(row, preferences, field, value):
    result = matching.evaluate({**row, field: value}, preferences)
    assert result["match_status"] == "Needs verification" and result["match_missing"]


def test_zero_limits_are_ignored_and_zero_miles_distance_are_known(row, preferences):
    preferences["filters"].update(max_price=0, max_miles=0, max_distance=0)
    assert matching.evaluate({}, preferences)["match_status"] == "Meets requirements"
    preferences["filters"].update(max_price=50000, max_miles=45000, max_distance=650)
    assert matching.evaluate({**row, "miles": 0, "distance_mi": 0}, preferences)["match_status"] == "Meets requirements"
    assert matching.evaluate({**row, "price": 0}, preferences)["match_status"] == "Needs verification"


def test_price_uses_discounted_price_only_when_enabled(row, preferences):
    truck = {**row, "price": 51000, "your_price": 49000}
    assert matching.evaluate(truck, preferences)["match_status"] == "Meets requirements"
    preferences["filters"]["count_discounts"] = False
    assert matching.evaluate(truck, preferences)["match_status"] == "Does not qualify"
    preferences["filters"]["count_discounts"] = True
    assert matching.evaluate({**truck, "your_price": np.nan}, preferences)["match_status"] == "Does not qualify"


@pytest.mark.parametrize("name,field,target,low,high", [("range", "epa_range", 301, 280, 320),
                                                       ("tow", "tow_capacity_lbs", 7500, 5000, 10000)])
def test_numeric_requirements_need_proof_even_for_advertised_below_target(row, preferences, name, field, target, low, high):
    preferences["shopping_profile"].update({name + "_min": target, name + "_priority": "must"})
    for value in (low, high):
        result = matching.evaluate(row, preferences, {field: claim(field, str(value))})
        assert result["match_status"] == "Needs verification"
        assert "advertised" in " ".join(result["match_missing"]) and not result["match_failures"]
    assert matching.evaluate(row, preferences, {field: claim(field, str(low), True)})["match_status"] == "Does not qualify"
    assert matching.evaluate(row, preferences, {field: claim(field, str(high), True)})["match_status"] == "Meets requirements"


def test_conflicting_advertised_claims_need_proof_but_verified_override_wins(row, preferences):
    preferences["shopping_profile"].update(range_min=301, range_priority="must")
    result = matching.evaluate(row, preferences, {"epa_range": claim("epa_range", "320", conflict=True)})
    assert result["match_status"] == "Needs verification" and "conflicting" in " ".join(result["match_missing"])
    assert matching.evaluate(row, preferences, {"epa_range": claim("epa_range", "320", True, conflict=True)})["match_status"] == "Meets requirements"


@pytest.mark.parametrize("feature", matching.FEATURES)
def test_required_features_distinguish_verified_yes_no_and_unverified_claims(row, preferences, feature):
    preferences["shopping_profile"]["must_have"] = [feature]
    assert matching.evaluate(row, preferences)["match_status"] == "Needs verification"
    for value in ("yes", "no"):
        result = matching.evaluate(row, preferences, {feature: claim(feature, value)})
        assert result["match_status"] == "Needs verification" and not result["match_failures"]
    assert matching.evaluate(row, preferences, {feature: claim(feature, "yes", True)})["match_status"] == "Meets requirements"
    assert matching.evaluate(row, preferences, {feature: claim(feature, "no", True)})["match_status"] == "Does not qualify"


def test_preferred_equipment_changes_bonus_without_blocking_requirements(row, preferences):
    preferences["shopping_profile"]["prefer"] = ["ventilated_seats"]
    at_limits = {**row, "price": 50000, "miles": 45000, "distance_mi": 650}
    yes = matching.evaluate(at_limits, preferences, {"ventilated_seats": claim("ventilated_seats", "yes")})
    no = matching.evaluate(at_limits, preferences, {"ventilated_seats": claim("ventilated_seats", "no", True)})
    unknown = matching.evaluate(at_limits, preferences)
    assert yes["match_score"] == 25 and no["match_score"] == unknown["match_score"] == 0
    assert {r["match_status"] for r in (yes, no, unknown)} == {"Meets requirements"}
    assert yes["match_missing"] and unknown["match_missing"] and not no["match_missing"]
    assert "advertised yes" in " ".join(yes["match_preferred"])


def test_preferred_numeric_targets_and_ignore_priority(row, preferences):
    preferences["shopping_profile"].update(range_min=301, range_priority="prefer", tow_min=11000, tow_priority="prefer")
    result = matching.evaluate(row, preferences)
    assert result["match_status"] == "Meets requirements" and len(result["match_missing"]) == 2
    preferences["shopping_profile"].update(range_priority="ignore", tow_priority="ignore")
    ignored = matching.evaluate(row, preferences)
    assert not ignored["match_missing"] and not ignored["match_preferred"]


def test_conflicting_preferred_claims_earn_no_credit_until_verified(row, preferences):
    preferences["shopping_profile"].update(range_min=301, range_priority="prefer", prefer=["ventilated_seats"])
    at_limits = {**row, "price": 50000, "miles": 45000, "distance_mi": 650}
    values = {"epa_range": "320", "ventilated_seats": "yes"}
    conflicting = {field: claim(field, value, conflict=True) for field, value in values.items()}
    assert matching.evaluate(at_limits, preferences, conflicting)["match_score"] == 0
    for field, value in values.items():
        verified = {**conflicting, field: claim(field, value, True, conflict=True)}
        result = matching.evaluate(at_limits, preferences, verified)
        assert result["match_score"] == 20 and result["match_status"] == "Meets requirements"
    advertised = {field: claim(field, value) for field, value in values.items()}
    assert matching.evaluate(at_limits, preferences, advertised)["match_score"] == 40


def test_duplicate_or_old_feature_preferences_are_safe_and_must_takes_precedence(row, preferences):
    preferences["shopping_profile"].update(must_have=["tonneau", "tonneau", "unknown feature", None, {}], prefer=["tonneau"])
    result = matching.evaluate(row, preferences, {"tonneau": claim("tonneau", "yes", True)})
    assert result["match_status"] == "Meets requirements" and not result["match_preferred"]
    assert sum("Powered tonneau" in reason for reason in result["match_reasons"]) == 1


def test_proof_items_preserve_evidence_and_do_not_accept_manufacturer_inferences(row, preferences):
    preferences["shopping_profile"].update(must_have=["ventilated_seats"], prefer=["ventilated_seats", "tonneau"])
    truck = {**row, "epa_range": None, "range_mi": 410, "battery": "Unknown", "warranty_expires": "2030-01-01",
             "trim": "Max Pack Platinum", "title_status": "clean"}
    resolved = {"ventilated_seats": claim("ventilated_seats", "yes", evidence="Seller description", conflict=True),
                "title_status": claim("title_status", "clean", True)}
    proof = matching.proof_items(truck, preferences, resolved)
    fields = {item["field"]: item for item in proof}
    assert len(proof) == len(fields) == 7
    assert fields["epa_range"]["status"] == fields["battery"]["status"] == fields["warranty_expiration"]["status"] == "Unknown"
    assert fields["tow_capacity_lbs"]["status"] == "Advertised"
    assert fields["title_status"]["status"] == "Verified"
    assert fields["ventilated_seats"]["status"] == "Conflicting" and "Seller description" in fields["ventilated_seats"]["evidence"]


def test_inventory_matching_updates_from_existing_claims_and_overrides(conn, settings):
    settings["shopping_profile"].update(range_min=301, range_priority="must", tow_min=7500,
                                        tow_priority="must", must_have=["ventilated_seats"])
    pipeline.import_listings(conn, [listing(vin=vin(980), make="Ford", model="F-150 Lightning", attributes=[
        AttributeClaim("epa_range", "320", "medium", "Listing"), AttributeClaim("tow_capacity_lbs", "10000", "medium", "Listing"),
        AttributeClaim("ventilated_seats", "yes", "medium", "Listing")])], "manual_entry")
    frame = queries.inventory_frame(conn, settings)
    assert frame.iloc[0]["match_status"] == "Needs verification"
    vehicle_id = int(frame.iloc[0]["vehicle_id"])
    for field, value in (("epa_range", "320"), ("tow_capacity_lbs", "10000"), ("ventilated_seats", "yes")):
        attributes.set_override(conn, vehicle_id, field, value, "Verified sticker / test drive")
    frame = queries.inventory_frame(conn, settings)
    assert frame.iloc[0]["match_status"] == "Meets requirements"
    attributes.set_override(conn, vehicle_id, "ventilated_seats", "no")
    assert queries.inventory_frame(conn, settings).iloc[0]["match_status"] == "Does not qualify"


def test_personal_sort_prioritizes_requirement_status_before_score():
    frame = pd.DataFrame({"vehicle_id": [1, 2, 3, 4, 5], "price": [50000] * 5,
                          "match_status": ["Meets requirements", "Needs verification", "Does not qualify", "Meets requirements", None],
                          "match_score": [10, 99, 100, 90, 100]})
    assert queries.SORT_OPTIONS[0] == "Personal match"
    assert queries.sort_inventory(frame, "Personal match")["vehicle_id"].tolist() == [4, 1, 2, 3, 5]


def test_personal_status_filter_is_optional_hard_and_explained(conn, settings):
    pipeline.import_listings(conn, [listing(vin=vin(981))], "manual_entry")
    base = queries.inventory_frame(conn, settings).iloc[0].to_dict()
    frame = pd.DataFrame([{**base, "vehicle_id": i, "price": 66000, "match_status": status}
                          for i, status in enumerate(matching.MATCH_STATUSES)])
    selected = {**settings["filters"], "max_price": 65000, "near_misses": True, "match_statuses": ["Meets requirements"]}
    assert queries.apply_filters(frame, selected)["match_status"].tolist() == ["Meets requirements"]
    assert any("personal match is Needs verification" in text for text in queries.why_hidden(frame.iloc[1], selected))
    no_column = frame.drop(columns="match_status")
    assert queries.apply_filters(no_column, selected).empty
    assert len(queries.apply_filters(no_column, {**selected, "match_statuses": []})) == 3
    assert any("not evaluated" in text for text in queries.why_hidden(no_column.iloc[0], selected))
    assert config.merge_settings({"filters": {"match_statuses": ["Needs verification"]}})["filters"]["match_statuses"] == ["Needs verification"]
