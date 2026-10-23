"""A refresh selection scopes requests and leaves every unselected listing untouched."""
import pytest

from conftest import FakeAdapter, listing, load_json, vin
from test_sources import FakeResponse, adapter

from rivian_finder import db, pipeline
from rivian_finder.models import FetchResult
from rivian_finder.sources import autodev, marketcheck
from rivian_finder.sources.base import SUPPORTED_BRANDS, collection_scopes
from rivian_finder.sources.demo import DemoAdapter


MODELS = {"Rivian": "R1T", "Ford": "F-150 Lightning", "Chevrolet": "Silverado EV", "GMC": "Sierra EV"}


@pytest.mark.parametrize("cls,body,make_field,model_field", [
    (autodev.AutoDevAdapter, {"data": []}, "vehicle.make", "vehicle.model"),
    (marketcheck.MarketCheckAdapter, {"listings": [], "num_found": 0}, "make", "model"),
])
@pytest.mark.parametrize("brands,expected", [
    (["Rivian"], [("Rivian", "R1T")]),
    (["Ford"], [("Ford", "F-150 Lightning")]),
    (["Chevrolet"], [("Chevrolet", "Silverado EV")]),
    (["GMC"], [("GMC", "Sierra EV")]),
    (["GMC", "Chevrolet"], [("Chevrolet,GMC", "Silverado EV,Sierra EV")]),
    (["Rivian", "Ford"], [("Ford", "F-150 Lightning"), ("Rivian", "R1T")]),
    (list(SUPPORTED_BRANDS), [("Ford,Chevrolet,GMC", "F-150 Lightning,Silverado EV,Sierra EV"), ("Rivian", "R1T")]),
])
def test_only_selected_brands_cost_requests(cls, body, make_field, model_field, brands, expected):
    a = adapter(cls, [FakeResponse(200, body) for _ in expected])
    result = a.fetch({"brands": brands, "include_other_brands": False,
                      "home_zip": "80202", "other_max_price": 54000})
    assert result.complete and result.api_calls == len(expected)
    params = [call["params"] for call in a.session.calls]
    assert [(p[make_field], p[model_field]) for p in params] == expected
    for p in params:
        if p[make_field] == "Rivian":
            continue
        if cls is autodev.AutoDevAdapter:
            assert (p["retailListing.price"], p["retailListing.miles"], p["zip"], p["distance"]) == (
                "1-54000", "0-45000", "80202", 650)
        else:
            assert (p["price_range"], p["miles_range"], p["zip"], p["radius"]) == (
                "1-54000", "0-45000", "80202", 100)


def test_absent_selection_preserves_scheduled_collection_settings():
    assert collection_scopes({}, "autodev") == [{}]
    assert len(collection_scopes({"include_other_brands": True}, "autodev")) == 2
    assert [s["make"] for s in collection_scopes({"brands": ["Ford"], "include_other_brands": False}, "autodev")] == ["Ford"]


@pytest.mark.parametrize("cls", [autodev.AutoDevAdapter, marketcheck.MarketCheckAdapter])
def test_empty_explicit_selection_never_falls_back_to_a_query(cls):
    a = adapter(cls, [])
    assert a.fetch({"brands": [], "include_other_brands": True}).api_calls == 0
    assert not a.session.calls


def test_competitor_only_refresh_gets_the_full_shared_request_budget():
    more = load_json("autodev_page1.json")
    a = adapter(autodev.AutoDevAdapter, [FakeResponse(200, more)] * 3 + [FakeResponse(200, {"data": []})])
    result = a.fetch({"brands": ["Ford"], "max_pages_per_run": 4})
    assert result.complete and result.api_calls == 4
    assert all(call["params"]["vehicle.make"] == "Ford" for call in a.session.calls)


@pytest.mark.parametrize("selected", SUPPORTED_BRANDS)
def test_selected_complete_scan_preserves_every_unselected_listing_field(conn, selected):
    trucks = [listing(vin=vin(810 + i), make=make, model=model) for i, (make, model) in enumerate(MODELS.items())]
    initial = FakeAdapter("autodev", [FetchResult(trucks, complete=True, scope_hash="all")])
    pipeline.run_search(conn, [initial], {"brands": list(SUPPORTED_BRANDS)})
    before = [dict(row) for row in conn.execute(
        "SELECT l.* FROM listings l JOIN vehicles v ON v.id=l.vehicle_id WHERE v.make!=? ORDER BY l.id", (selected,))]
    single = FakeAdapter("autodev", [FetchResult([], True, f"only-{selected}")] * 2)
    scope = {"brands": [selected]}
    first = pipeline.run_search(conn, [single], scope)
    second = pipeline.run_search(conn, [single], scope)
    assert first["counts"]["disappeared"] == 0  # The collection scope changed.
    assert second["counts"]["disappeared"] == 1
    after = [dict(row) for row in conn.execute(
        "SELECT l.* FROM listings l JOIN vehicles v ON v.id=l.vehicle_id WHERE v.make!=? ORDER BY l.id", (selected,))]
    assert before == after


def test_switching_refresh_brands_does_not_update_unselected_provider_rows(conn):
    trucks = [listing(vin=vin(820 + i), make=make, model=model) for i, (make, model) in enumerate(MODELS.items())]
    pipeline.run_search(conn, [FakeAdapter("autodev", [FetchResult(trucks, True, "all")])],
                        {"brands": list(SUPPORTED_BRANDS)})
    changed = [listing(vin=nl.vin, make=nl.make, model=nl.model, price=50000) for nl in trucks]
    for make in ("Ford", "GMC", "Ford"):
        summary = pipeline.run_search(conn, [FakeAdapter("autodev", [FetchResult(changed, True, make)])], {"brands": [make]})
        assert summary["sources"][0]["listings_seen"] == 1
        assert summary["counts"]["disappeared"] == 0
    prices = dict(conn.execute("SELECT v.make, l.current_price FROM listings l JOIN vehicles v ON v.id=l.vehicle_id"))
    assert prices == {"Rivian": 60000, "Ford": 50000, "Chevrolet": 60000, "GMC": 50000}


def test_competitor_selection_does_not_advance_or_remove_rivian_demo_inventory(conn):
    demo = DemoAdapter(conn)
    pipeline.run_search(conn, [demo], {})
    step = db.get_pref(conn, "demo_run_index")
    before = [dict(row) for row in conn.execute("SELECT * FROM listings WHERE source_key='demo' ORDER BY id")]
    for _ in range(2):
        result = pipeline.run_search(conn, [demo], {"brands": ["Ford"]})
        assert result["sources"][0]["listings_seen"] == result["counts"]["disappeared"] == 0
    assert db.get_pref(conn, "demo_run_index") == step
    assert before == [dict(row) for row in conn.execute("SELECT * FROM listings WHERE source_key='demo' ORDER BY id")]
