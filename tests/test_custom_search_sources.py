"""Configurable make/model searches keep requests narrow and retain the legacy truck configuration."""
import copy

import pytest

from conftest import FakeAdapter
from test_sources import FakeResponse, adapter

from rivian_finder import services
from rivian_finder.sources import autodev, marketcheck
from rivian_finder.sources.base import (
    EV_TRUCK_PRESET, SUPPORTED_BRANDS, collection_scopes, configured_brands, matches_target, search_targets,
)


def test_search_targets_normalize_deduplicate_and_preserve_input():
    scope = {"searches": [{"make": "  Tesla ", "model": "Model   3"},
                           {"make": "TESLA", "model": " model 3 "},
                           {"make": "tesla", "model": "Model Y"},
                           {"make": "Toyota", "model": "Camry"}]}
    before = copy.deepcopy(scope)
    assert search_targets(scope) == [{"make": "Tesla", "model": "Model 3"},
                                      {"make": "tesla", "model": "Model Y"},
                                      {"make": "Toyota", "model": "Camry"}]
    assert configured_brands(scope) == ["Tesla", "Toyota"]
    assert scope == before
    assert matches_target(" TESLA ", "Model   3", search_targets(scope)[0])
    assert not matches_target("Tesla", "Model Y", search_targets(scope)[0])


@pytest.mark.parametrize("searches", [
    [], {}, "Tesla Model 3", [None], ["Tesla"], [{}], [{"make": "Tesla"}],
    [{"make": "", "model": "Model 3"}], [{"make": "Tesla", "model": "   "}],
    [{"make": True, "model": "Model 3"}], [{"make": "Tesla", "model": 3}],
    [{"make": "Tesla,Ford", "model": "Model 3"}], [{"make": "Tesla", "model": "Model 3,Model Y"}],
    [{"make": "Tesla\nFord", "model": "Model 3"}], [{"make": "Tesla", "model": "Model 3\r\nModel Y"}],
])
def test_invalid_targets_fail_before_any_adapter_is_created(conn, settings, monkeypatch, searches):
    settings["collection"]["searches"] = searches
    monkeypatch.setattr(services, "make_adapter", lambda *args: pytest.fail("invalid search created an adapter"))
    with pytest.raises(ValueError):
        search_targets(settings["collection"])
    result = services.run_sources(conn, ["autodev"], settings)
    assert result["status"] == "failed" and result["sources"] == []
    assert conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0] == 0


def test_unconfigured_or_none_searches_preserve_legacy_behavior():
    for scope in ({}, {"searches": None}):
        assert search_targets(scope) == EV_TRUCK_PRESET
        assert configured_brands(scope) == list(SUPPORTED_BRANDS)
        assert collection_scopes(scope, "autodev") == [scope]
    targets = search_targets({})
    targets[0]["make"] = "Changed"
    assert EV_TRUCK_PRESET[0]["make"] == "Rivian"
    assert len(collection_scopes({"include_other_brands": True}, "autodev")) == 2


def test_custom_scopes_share_global_constraints_without_cross_product_queries():
    scope = {"searches": [{"make": "Tesla", "model": "Model 3"}, {"make": "Toyota", "model": "Camry"}],
             "max_price": 35000, "max_miles": 50000, "year_min": 2020, "year_max": 2025,
             "used_only": False, "max_distance": 500, "home_zip": "80202", "marketcheck_radius": 100,
             "other_max_price": 90000, "other_max_miles": 100000, "other_max_distance": 2000}
    for source in ("autodev", "marketcheck"):
        queries = collection_scopes(scope, source)
        assert [(q["make"], q["model"]) for q in queries] == [("Tesla", "Model 3"), ("Toyota", "Camry")]
        for q in queries:
            assert (q["max_price"], q["max_miles"], q["year_min"], q["year_max"], q["used_only"]) == (
                35000, 50000, 2020, 2025, False)
            assert (q["zip"], q["distance"]) == ("80202", 500)
            if source == "marketcheck":
                assert (q["marketcheck_zip"], q["marketcheck_radius"]) == ("80202", 100)
    for radius, expected in ((0, 500), (50, 50), (1000, 500)):
        assert collection_scopes({**scope, "marketcheck_radius": radius}, "marketcheck")[0]["marketcheck_radius"] == expected


def test_brand_selection_intersects_custom_targets_case_insensitively():
    scope = {"searches": [{"make": "Tesla", "model": "Model 3"}, {"make": "Tesla", "model": "Model Y"},
                           {"make": "Toyota", "model": "Camry"}], "brands": ["TESLA"]}
    assert [(q["make"], q["model"]) for q in collection_scopes(scope, "autodev")] == [
        ("Tesla", "Model 3"), ("Tesla", "Model Y")]


def provider_page(cls, targets, more=False):
    if cls is autodev.AutoDevAdapter:
        return {"data": [{"vehicle": target, "retailListing": {"used": True, "price": 30000}}
                          for target in targets], "links": {"next": "/listings?page=2"} if more else {}}
    return {"listings": [{"build": target, "price": 30000} for target in targets],
            "num_found": 1000 if more else len(targets)}


@pytest.mark.parametrize("cls", [autodev.AutoDevAdapter, marketcheck.MarketCheckAdapter])
def test_custom_requests_are_exact_pairs_and_ignore_off_pair_provider_results(cls):
    targets = [{"make": "Tesla", "model": "Model 3"}, {"make": "Toyota", "model": "Camry"}]
    wrong_model = {"make": "Tesla", "model": "Model Y"}
    wrong_make = {"make": "Honda", "model": "Camry"}
    a = adapter(cls, [FakeResponse(200, provider_page(cls, [targets[0], wrong_model, targets[1]])),
                      FakeResponse(200, provider_page(cls, [targets[1], wrong_make]))])
    result = a.fetch({"searches": targets, "home_zip": "80202", "max_distance": 650,
                      "max_price": 35000, "max_miles": 50000})
    assert result.complete and result.api_calls == 2
    assert [(nl.make, nl.model) for nl in result.listings] == [("Tesla", "Model 3"), ("Toyota", "Camry")]
    fields = ("vehicle.make", "vehicle.model") if cls is autodev.AutoDevAdapter else ("make", "model")
    assert [tuple(call["params"][field] for field in fields) for call in a.session.calls] == [
        ("Tesla", "Model 3"), ("Toyota", "Camry")]


@pytest.mark.parametrize("cls", [autodev.AutoDevAdapter, marketcheck.MarketCheckAdapter])
def test_custom_queries_split_one_request_allowance_evenly_including_rivian(cls):
    targets = [{"make": "Tesla", "model": "Model 3"}, {"make": "Toyota", "model": "Camry"},
               {"make": "Rivian", "model": "R1T"}]
    a = adapter(cls, [FakeResponse(200, provider_page(cls, [target], more=True))
                      for target in targets for _ in range(2)])
    result = a.fetch({"searches": targets, "max_pages_per_run": 6})
    make_field = "vehicle.make" if cls is autodev.AutoDevAdapter else "make"
    assert not result.complete and result.api_calls == len(a.session.calls) == 6
    assert [call["params"][make_field] for call in a.session.calls] == ["Tesla", "Tesla", "Toyota", "Toyota", "Rivian", "Rivian"]


@pytest.mark.parametrize("cls", [autodev.AutoDevAdapter, marketcheck.MarketCheckAdapter])
def test_custom_query_budget_includes_retry_attempts(cls):
    targets = [{"make": "Tesla", "model": "Model 3"}, {"make": "Toyota", "model": "Camry"}]
    a = adapter(cls, [FakeResponse(429), FakeResponse(200, provider_page(cls, [targets[0]], more=True)),
                      FakeResponse(200, provider_page(cls, [targets[1]]))])
    result = a.fetch({"searches": targets, "max_pages_per_run": 3})
    make_field = "vehicle.make" if cls is autodev.AutoDevAdapter else "make"
    assert not result.complete and result.api_calls == len(a.session.calls) == 3
    assert [call["params"][make_field] for call in a.session.calls] == ["Tesla", "Tesla", "Toyota"]
    assert len(result.listings) == 2


@pytest.mark.parametrize("keys,distance,mc_radius", [
    (["autodev"], 650, 100), (["marketcheck"], 0, 100), (["autodev", "marketcheck"], 0, 100),
])
@pytest.mark.parametrize("home_zip", ["", "00000", "abcde"])
def test_radius_searches_require_home_zip_before_adapter_creation(conn, settings, monkeypatch, keys, distance, mc_radius, home_zip):
    settings["home_zip"] = home_zip
    settings["collection"].update(searches=[{"make": "Tesla", "model": "Model 3"}],
                                   max_distance=distance, marketcheck_radius=mc_radius)
    monkeypatch.setattr(services, "make_adapter", lambda *args: pytest.fail("missing ZIP created an adapter"))
    result = services.run_sources(conn, keys, settings)
    assert result["status"] == "failed" and "Home ZIP" in result["text"]


@pytest.mark.parametrize("keys", [["autodev"], ["marketcheck"], ["demo"]])
def test_nationwide_or_demo_refresh_allows_blank_home_zip(conn, settings, monkeypatch, keys):
    settings["home_zip"] = ""
    settings["collection"].update(searches=[{"make": "Tesla", "model": "Model 3"},
                                             {"make": "tesla", "model": "Model Y"}], max_distance=0, marketcheck_radius=0,
                                   vpic_enrichment=False, mc_second_opinion=False)
    monkeypatch.setattr(services, "make_adapter", lambda c, key: FakeAdapter(key, []))
    monkeypatch.setattr(services.backup, "daily_backup", lambda c: None)
    seen = {}

    def capture(c, adapters, scope, enrich=None):
        seen.update(scope)
        return {"sources": [], "counts": {}, "status": "success"}

    monkeypatch.setattr(services.pipeline, "run_search", capture)
    result = services.run_sources(conn, keys, settings, brands=["tesla"])
    assert result["status"] == "success" and result["brands"] == ["Tesla"]
    assert seen["brands"] == ["Tesla"]


def test_configured_brands_control_service_validation(conn, settings, monkeypatch):
    settings["collection"]["searches"] = [{"make": "Toyota", "model": "Camry"}]
    monkeypatch.setattr(services, "make_adapter", lambda *args: pytest.fail("unconfigured brand created an adapter"))
    result = services.run_sources(conn, ["autodev"], settings, brands=["Ford"])
    assert result["status"] == "failed" and "configured brand" in result["text"]


def test_r1s_custom_search_does_not_trigger_r1t_recall_or_paid_enrichment(conn, settings, monkeypatch):
    settings["home_zip"] = "84020"
    settings["collection"].update(searches=[{"make": "Rivian", "model": "R1S"}], max_distance=0,
                                   vpic_enrichment=False, mc_second_opinion=True)
    monkeypatch.setattr(services, "make_adapter", lambda c, key: type("Adapter", (), {"key": key, "calls": 0})())
    monkeypatch.setattr(services.backup, "daily_backup", lambda c: None)
    monkeypatch.setattr(services.photos, "cache_missing", lambda c, **kwargs: {"cached": 0})
    monkeypatch.setattr(services.recalls, "refresh", lambda *args: pytest.fail("R1S requested R1T recalls"))
    monkeypatch.setattr(services.enrich, "auto_second_opinions", lambda *args, **kwargs: pytest.fail("R1S requested R1T VIN decoding"))

    def capture(c, adapters, scope, enrich=None):
        assert enrich(c) == {"photos": {"cached": 0}}
        return {"sources": [], "counts": {}, "status": "success"}

    monkeypatch.setattr(services.pipeline, "run_search", capture)
    assert services.run_sources(conn, ["marketcheck"], settings)["status"] == "success"
