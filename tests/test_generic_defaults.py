"""Fresh workspaces are generic; saved shopping preferences keep their behavior."""
from copy import deepcopy
from dataclasses import asdict

from rivian_finder import config
from rivian_finder.finance import FinanceAssumptions


def test_fresh_defaults_have_no_personal_or_ev_only_preferences():
    settings = config.merge_settings({})
    assert settings["home_zip"] == ""
    assert settings["priority_states"] == []
    assert settings["collection"]["searches"] == [{"make": "Rivian", "model": "R1T"}]
    assert settings["filters"]["make"] == settings["filters"]["model"] == ""
    assert settings["collection"]["excluded_trims"] == {}
    assert settings["collection"]["other_min_range"] == 0
    assert not settings["collection"]["exclude_standard_range"]
    finance = settings["finance"]
    assert finance["current_vehicle"] == ""
    assert finance["discounts"] == []
    assert all(finance[key] == 0 for key in (
        "trade_payoff", "trade_in_low", "trade_in_high", "cash_offer", "sales_tax_rate", "dmv_fees", "doc_fee"))
    assert settings["adjustments"]["rules"] == []
    assert not settings["adjustments"]["range_value"]["enabled"]
    assert not settings["adjustments"]["warranty_value"]["enabled"]
    assert not settings["shipping"]["fly_drive"]["enabled"]
    assert asdict(FinanceAssumptions()) == settings["finance"]


def test_legacy_collection_and_saved_values_are_preserved():
    stored = {
        "home_zip": "10001", "priority_states": ["NY"],
        "collection": {"make": "Rivian", "model": "R1T", "include_other_brands": True,
                       "other_min_range": 301, "excluded_trims": {"Ford": ["Pro"], "Chevrolet": ["WT"]}},
        "finance": {"current_vehicle": "Saved vehicle", "trade_payoff": 1234.0, "sales_tax_rate": 8.0},
        "adjustments": {"rules": [{"field": "color", "match": "blue", "amount": 250.0}],
                        "range_value": {"enabled": True, "ok_at": 300}},
        "shipping": {"fly_drive": {"enabled": True, "max_road_miles": 450}},
    }
    before = deepcopy(stored)
    merged = config.merge_settings(stored)
    assert stored == before
    assert merged["collection"]["searches"] is None
    for section, values in stored.items():
        if isinstance(values, dict):
            assert all(merged[section][key] == value for key, value in values.items())
        else:
            assert merged[section] == values


def test_explicit_searches_survive_settings_merge_without_sharing_defaults():
    searches = [{"make": "Toyota", "model": "Tacoma"}, {"make": "Honda", "model": "Civic"}]
    assert config.merge_settings({"collection": {"searches": searches}})["collection"]["searches"] == searches
    first = config.default_settings()
    first["collection"]["searches"].append({"make": "Honda", "model": "Civic"})
    assert config.default_settings()["collection"]["searches"] == [{"make": "Rivian", "model": "R1T"}]
