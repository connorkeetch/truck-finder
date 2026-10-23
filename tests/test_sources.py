"""Connector parsing, pagination, error handling, and credential redaction (no network)."""
import pytest
from conftest import load_json

from rivian_finder import credentials, enrich, pipeline, queries
from rivian_finder.models import RateLimited, SourceError
from rivian_finder.sources import autodev, marketcheck
from rivian_finder.sources.demo import DemoAdapter, demo_listings
from rivian_finder.sources import base


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("requests").HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {})})
        return self.responses.pop(0)


def adapter(cls, responses, key="test-key-123456"):
    return cls(key, session=FakeSession(responses), sleep=lambda s: None)


def test_autodev_parses_and_follows_next_link():
    a = adapter(autodev.AutoDevAdapter, [FakeResponse(200, load_json("autodev_page1.json")),
                                         FakeResponse(200, load_json("autodev_page2.json"))])
    res = a.fetch({"year_min": 2022, "year_max": 2026, "max_price": 90000, "max_miles": 80000})
    assert res.complete
    assert res.api_calls == 2
    vins = [l.vin for l in res.listings]
    assert len(vins) == 3   # new-vehicle and wholesale-only rows are skipped
    first = res.listings[0]
    assert (first.price, first.miles, first.state, first.seller_name) == (58990, 14250, "UT", "Example EV Dealer")
    assert first.lat == pytest.approx(40.5046) and first.lon == pytest.approx(-111.881)
    claims = {c.field: (c.value, c.confidence) for c in first.attributes}
    assert claims["battery"] == ("Large", "medium")
    assert claims["motor"] == ("Dual", "medium")
    call = a.session.calls[0]
    assert call["headers"]["Authorization"] == "Bearer test-key-123456"
    assert call["params"]["vehicle.make"] == "Rivian" and call["params"]["vehicle.model"] == "R1T"
    assert a.session.calls[1]["params"]["page"] == "2"
    assert any("Skipped 1 new-vehicle" in n for n in res.notes)


def test_autodev_page_cap_marks_scan_incomplete():
    a = adapter(autodev.AutoDevAdapter, [FakeResponse(200, load_json("autodev_page1.json"))])
    res = a.fetch({"max_pages_per_run": 1})
    assert not res.complete


def test_autodev_competitor_filters_are_sent_before_pagination():
    competitor = load_json("autodev_page1.json")["data"][0]
    competitor["vehicle"].update(make="Ford", model="F-150 Lightning", trim="Lariat")
    a = adapter(autodev.AutoDevAdapter, [
        FakeResponse(200, {"data": [competitor], "links": {"next": "/listings?cursor=opaque"}}),
        FakeResponse(200, {"data": []}), FakeResponse(200, {"data": []})])
    res = a.fetch({"include_other_brands": True, "home_zip": "80202", "other_max_price": 58000,
                   "max_price": 75000, "max_miles": 60000, "other_max_miles": 45000,
                   "other_max_distance": 650})
    assert res.complete and res.api_calls == 3
    first, following, rivian = [c["params"] for c in a.session.calls]
    assert first["vehicle.make"] == "Ford,Chevrolet,GMC"
    assert first["vehicle.model"] == "F-150 Lightning,Silverado EV,Sierra EV"
    for p in (first, following):
        assert (p["retailListing.price"], p["retailListing.miles"]) == ("1-58000", "0-45000")
        assert (p["zip"], p["distance"], p["retailListing.used"]) == ("80202", 650, "true")
    assert following["cursor"] == "opaque" and "page" not in following
    assert rivian["vehicle.make"] == "Rivian" and rivian["vehicle.model"] == "R1T"
    assert "distance" not in rivian and rivian["retailListing.price"] == "1-75000"


@pytest.mark.parametrize("cls", [autodev.AutoDevAdapter, marketcheck.MarketCheckAdapter])
def test_excluded_trims_do_not_stop_pagination_or_hide_unknown_trims(cls):
    excluded = [("Ford", "F-150 Lightning", "Pro"), ("Chevrolet", "Silverado EV", "3WT")]
    allowed = [("Ford", "F-150 Lightning", "XLT"), ("Chevrolet", "Silverado EV", "LT"),
               ("Ford", "F-150 Lightning", None), ("Chevrolet", "Silverado EV", "RST"),
               ("GMC", "Sierra EV", "Denali")]

    def page(trucks, more=False):
        rows = [{"make": make, "model": model, "trim": trim} for make, model, trim in trucks]
        if cls is autodev.AutoDevAdapter:
            return {"data": [{"vehicle": row, "retailListing": {"used": True}} for row in rows],
                    "links": {"next": "/listings?cursor=opaque"} if more else {}}
        return {"listings": [{"build": row} for row in rows], "num_found": 51 if more else 54}

    a = adapter(cls, [FakeResponse(200, page(excluded, more=True)),
                      FakeResponse(200, page(allowed)), FakeResponse(200, page([]))])
    result = a.fetch({"include_other_brands": True, "max_pages_per_run": 8,
                      "excluded_trims": {"Ford": ["Pro"], "Chevrolet": ["WT"]}})
    assert result.complete and result.api_calls == len(a.session.calls) == 3
    assert [(nl.make, nl.model, nl.trim) for nl in result.listings] == allowed
    assert any("Skipped 2 excluded-trim" in note for note in result.notes)
    assert all("vehicle.trim" not in call["params"] and "trim" not in call["params"]
               for call in a.session.calls)  # Providers document positive trim filters only.


@pytest.mark.parametrize("cls,body", [
    (autodev.AutoDevAdapter, {"data": []}),
    (marketcheck.MarketCheckAdapter, {"listings": [], "num_found": 0}),
])
def test_trim_exclusions_change_scan_identity_without_changing_provider_query(cls, body):
    a = adapter(cls, [FakeResponse(200, body), FakeResponse(200, body), FakeResponse(200, body)])
    baseline = a.fetch({})
    empty = a.fetch({"excluded_trims": {}})
    excluded = a.fetch({"excluded_trims": {"Ford": ["Pro"], "Chevrolet": ["WT"]}})
    assert baseline.scope_hash == empty.scope_hash != excluded.scope_hash
    assert a.session.calls[0]["params"] == a.session.calls[1]["params"] == a.session.calls[2]["params"]


@pytest.mark.parametrize("cls", [autodev.AutoDevAdapter, marketcheck.MarketCheckAdapter])
@pytest.mark.parametrize("variant_field", ["trim", "title", "version", "battery"])
def test_standard_range_is_excluded_from_specific_listing_fields_only(cls, variant_field):
    vehicle = {"make": "GMC", "model": "Sierra EV", "trim": "Elevation"}
    item = {"heading": "2026 GMC Sierra EV Elevation", "description": "Also available in Standard Range."}
    if variant_field == "title":
        item["heading"] += " Standard-Range"
    else:
        vehicle[variant_field] = "Elevation Standard Range" if variant_field == "trim" else "Standard Range"
    if cls is autodev.AutoDevAdapter:
        item.update(vehicle=vehicle, retailListing={"used": True})
        body = {"data": [item]}
    else:
        item["build"] = vehicle
        body = {"listings": [item], "num_found": 1}
    a = adapter(cls, [FakeResponse(200, body), FakeResponse(200, body)])
    allowed = a.fetch({"exclude_standard_range": False})
    excluded = a.fetch({"exclude_standard_range": True})
    assert len(allowed.listings) == 1 and not excluded.listings
    assert allowed.complete and excluded.complete and excluded.api_calls == 1
    assert allowed.scope_hash != excluded.scope_hash
    assert a.session.calls[0]["params"] == a.session.calls[1]["params"]
    assert any("Skipped 1 Standard Range" in note for note in excluded.notes)


@pytest.mark.parametrize("cls", [autodev.AutoDevAdapter, marketcheck.MarketCheckAdapter])
def test_standard_range_in_marketing_description_does_not_exclude_listing(cls, conn, settings):
    vehicle = {"make": "GMC", "model": "Sierra EV", "trim": "Elevation Max Range"}
    item = {"heading": "2026 GMC Sierra EV Elevation Max Range",
            "description": "Other Sierra EVs come in Standard Range or Extended Range. EPA range: 410 miles. Towing capacity: 10000 lbs."}
    if cls is autodev.AutoDevAdapter:
        item.update(vehicle=vehicle, retailListing={"used": True})
        body = {"data": [item]}
    else:
        item["build"] = vehicle
        body = {"listings": [item], "num_found": 1}
    result = adapter(cls, [FakeResponse(200, body)]).fetch({"exclude_standard_range": True})
    assert len(result.listings) == 1 and result.complete
    nl = result.listings[0]
    assert {c.value for c in nl.attributes if c.field == "battery"} == {"Max Range"}
    assert {c.value for c in nl.attributes if c.field == "epa_range"} == {"410"}
    assert {c.value for c in nl.attributes if c.field == "tow_capacity_lbs"} == {"10000"}
    nl.price, nl.miles, nl.zip = 60000, 1000, "84020"
    pipeline.import_listings(conn, [nl], "manual_entry")
    assert len(queries.apply_filters(queries.inventory_frame(conn, settings), settings["filters"])) == 1


@pytest.mark.parametrize("location,field", [("item", "heading"), ("item", "title"),
                                             ("vehicle", "title"), ("retailListing", "title")])
def test_autodev_preserves_the_supplied_vehicle_title(location, field):
    item = {"vehicle": {"make": "GMC", "model": "Sierra EV", "trim": "Elevation"},
            "retailListing": {"used": True}}
    title = "2026 GMC Sierra EV Elevation Standard Range"
    (item if location == "item" else item[location])[field] = title
    assert autodev.parse_item(item).title == title


@pytest.mark.parametrize("cls,empty,more", [
    (autodev.AutoDevAdapter, {"data": []}, load_json("autodev_page1.json")),
    (marketcheck.MarketCheckAdapter, {"listings": [], "num_found": 0},
     {"listings": load_json("marketcheck_page1.json")["listings"], "num_found": 1000}),
])
def test_shared_request_limit_includes_other_brands_and_retries(cls, empty, more):
    a = adapter(cls, [FakeResponse(200, empty), FakeResponse(429), FakeResponse(200, more)])
    res = a.fetch({"include_other_brands": True, "max_pages_per_run": 3})
    assert not res.complete and len(res.listings) == 2
    assert res.api_calls == len(a.session.calls) == 3
    assert any("per-run request limit" in n for n in res.notes)


def test_monthly_budget_is_shared_across_adapter_instances_and_retries(conn, monkeypatch):
    monkeypatch.setitem(base.API_CAPS, "autodev", 2)
    a = autodev.AutoDevAdapter("test-key", conn=conn,
                              session=FakeSession([FakeResponse(429), FakeResponse(429)]), sleep=lambda s: None)
    res = a.fetch({"include_other_brands": True})
    assert not res.complete and res.api_calls == 2
    assert conn.execute("SELECT COUNT(*) FROM api_usage WHERE source_key='autodev'").fetchone()[0] == 2
    second = autodev.AutoDevAdapter("test-key", conn=conn, session=FakeSession([]), sleep=lambda s: None)
    assert second.fetch({}).api_calls == 0
    assert not second.session.calls


def test_network_failures_count_against_the_request_budget(conn):
    import requests

    class OfflineSession(FakeSession):
        def get(self, *args, **kwargs):
            self.calls.append(kwargs)
            raise requests.ConnectionError("offline")

    a = autodev.AutoDevAdapter("test-key", conn=conn, session=OfflineSession([]), sleep=lambda s: None)
    res = a.fetch({"max_pages_per_run": 2})
    assert not res.complete and res.api_calls == len(a.session.calls) == 2
    assert conn.execute("SELECT COUNT(*) FROM api_usage WHERE status_code IS NULL").fetchone()[0] == 2


def test_marketcheck_other_brands_preserve_free_plan_radius():
    a = adapter(marketcheck.MarketCheckAdapter, [FakeResponse(200, {"listings": [], "num_found": 0})] * 2)
    res = a.fetch({"include_other_brands": True, "other_max_distance": 650, "marketcheck_radius": 100,
                   "home_zip": "84020", "other_max_price": 65000})
    assert res.complete
    first, rivian = [c["params"] for c in a.session.calls]
    assert first["make"] == "Ford,Chevrolet,GMC" and first["radius"] == 100
    assert first["model"] == "F-150 Lightning,Silverado EV,Sierra EV"
    assert (first["price_range"], first["miles_range"], first["car_type"]) == ("1-65000", "0-45000", "used")
    assert rivian["make"] == "Rivian"


@pytest.mark.parametrize("cls,empty,more,make_field", [
    (autodev.AutoDevAdapter, {"data": []}, load_json("autodev_page1.json"), "vehicle.make"),
    (marketcheck.MarketCheckAdapter, {"listings": [], "num_found": 0},
     {"listings": load_json("marketcheck_page1.json")["listings"], "num_found": 1000}, "make"),
])
def test_competitor_pagination_leaves_request_budget_for_rivians(cls, empty, more, make_field):
    a = adapter(cls, [FakeResponse(200, more), FakeResponse(200, more), FakeResponse(200, empty)])
    res = a.fetch({"include_other_brands": True, "max_pages_per_run": 8})
    assert not res.complete and res.api_calls == 3
    assert [c["params"][make_field] for c in a.session.calls] == ["Ford,Chevrolet,GMC"] * 2 + ["Rivian"]


@pytest.mark.parametrize("cls,body", [
    (autodev.AutoDevAdapter, {**load_json("autodev_page1.json"), "links": {}}),
    (marketcheck.MarketCheckAdapter, load_json("marketcheck_page1.json")),
])
def test_competitor_query_failure_does_not_block_rivian_feed(cls, body):
    a = adapter(cls, [FakeResponse(422, {"error": "unsupported model filter"}), FakeResponse(200, body)])
    res = a.fetch({"include_other_brands": True, "max_pages_per_run": 4})
    assert not res.complete and len(res.listings) == 2
    assert res.api_calls == 2 and "HTTP 422" in res.error
    assert all(nl.make == "Rivian" for nl in res.listings)


def test_collection_uses_saved_display_price_and_home_zip(conn, settings, monkeypatch):
    from conftest import FakeAdapter
    from rivian_finder import services
    seen = {}
    settings["filters"]["max_price"] = 54000
    settings["home_zip"] = "80202"
    monkeypatch.setattr(services, "make_adapter", lambda c, key: FakeAdapter(key, []))
    monkeypatch.setattr(services.backup, "daily_backup", lambda c: None)

    def capture(c, adapters, scope, enrich=None):
        seen.update(scope)
        return {"sources": [], "counts": {}, "status": "success"}

    monkeypatch.setattr(services.pipeline, "run_search", capture)
    services.run_sources(conn, ["autodev"], settings)
    assert (seen["other_max_price"], seen["home_zip"]) == (54000, "80202")
    assert seen["excluded_trims"] == {"Ford": ["Pro"], "Chevrolet": ["WT"]}
    assert "other_max_price" not in settings["collection"]


def test_providers_capture_explicit_competitor_range_and_tow_capacity():
    auto = autodev.parse_item({"vehicle": {"make": "Ford", "model": "F-150 Lightning", "year": 2024},
                              "retailListing": {"description": "EPA range: 320 miles. Towing capacity: 10000 lbs."}})
    mc = marketcheck.parse_item({"build": {"make": "Chevrolet", "model": "Silverado EV"},
                                 "extra": {"electric_range_miles": 440, "tow_capacity_lbs": 10000}})
    for nl, expected_range in ((auto, "320"), (mc, "440")):
        claims = {c.field: c.value for c in nl.attributes}
        assert claims["epa_range"] == expected_range and claims["tow_capacity_lbs"] == "10000"
        assert "battery" not in claims and "motor" not in claims


def test_autodev_auth_error_is_clear():
    a = adapter(autodev.AutoDevAdapter, [FakeResponse(401, {"status": 401, "error": {"message": "Authentication required"}})])
    with pytest.raises(SourceError, match="rejected the API key"):
        a.fetch({})


def test_rate_limit_retries_then_raises():
    a = adapter(autodev.AutoDevAdapter, [FakeResponse(429, {}, {"Retry-After": "1"})] * 4)
    with pytest.raises(RateLimited):
        a.fetch({})
    assert len(a.session.calls) == 4


def test_rate_limit_recovers():
    a = adapter(autodev.AutoDevAdapter, [FakeResponse(429, {}, {"Retry-After": "0"}),
                                         FakeResponse(200, load_json("autodev_page2.json"))])
    assert a.fetch({}).complete


def test_missing_key_is_not_configured():
    ok, why = autodev.AutoDevAdapter(None).is_configured()
    assert not ok and "API key" in why


def test_marketcheck_parses_options_and_private_sellers():
    a = adapter(marketcheck.MarketCheckAdapter, [FakeResponse(200, load_json("marketcheck_page1.json"))])
    res = a.fetch({"marketcheck_radius": 100, "marketcheck_zip": "84020"})
    assert res.complete and len(res.listings) == 2
    first, second = res.listings
    claims = {c.field: c for c in first.attributes}
    assert claims["tonneau"].value == "yes"   # listed in options, not verified
    assert claims["tonneau"].confidence == "medium"
    assert second.seller_type == "private" and second.vin == ""
    params = a.session.calls[0]["params"]
    assert params["radius"] == 100 and params["car_type"] == "used" and params["api_key"] == "test-key-123456"


def test_marketcheck_nationwide_omits_radius():
    params = marketcheck.build_params({"marketcheck_radius": 0})
    assert "radius" not in params and "zip" not in params


def test_redaction_hides_keys():
    msg = "GET https://api.marketcheck.com/v2/search?api_key=SECRET123&make=rivian Authorization: Bearer abc.def"
    out = credentials.redact(msg)
    assert "SECRET123" not in out and "abc.def" not in out


def test_vpic_claims_map_drive_unit():
    claims = {c.field: c for c in enrich.claims_from_vpic({"EVDriveUnit": "Quad Motor", "Trim": "Adventure",
                                                           "ModelYear": "2023", "PlantCity": "NORMAL",
                                                           "PlantState": "ILLINOIS"})}
    assert claims["motor"].value == "Quad" and claims["motor"].confidence == "high"
    assert "vpic_decoded" in claims


def test_demo_timeline_changes_between_runs(conn):
    assert len(demo_listings(1)) < len(demo_listings(2)) + 4
    a = DemoAdapter(conn)
    s1 = pipeline.run_search(conn, [a], {})
    s2 = pipeline.run_search(conn, [a], {})
    assert s1["counts"]["new_listing"] > 20
    assert s2["counts"]["price_drop"] > 0 and s2["counts"]["disappeared"] > 0
    assert all(l.is_demo and "example.com" in l.url for l in demo_listings(3))
