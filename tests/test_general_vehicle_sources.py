"""Cars and SUVs follow the same collection path as trucks without Rivian assumptions."""
from datetime import date

import pytest
import requests

from test_sources import FakeResponse, adapter
from rivian_finder import config, pipeline, queries, services
from rivian_finder.sources import autodev, marketcheck
from rivian_finder.sources.demo import DemoAdapter, demo_listings


TARGETS = [{"make": "Toyota", "model": "Camry"}, {"make": "Honda", "model": "CR-V"},
           {"make": "Ford", "model": "Mustang Mach-E"}]


def _page(cls, target):
    build = {**target, "year": date.today().year + 1, "trim": "Premium"}
    url = f"https://example.com/{target['make']}/{target['model']}"
    if cls is autodev.AutoDevAdapter:
        return {"data": [{"vehicle": build, "description": "Large cargo area with max storage.",
                          "retailListing": {"used": False, "price": 30000, "miles": 0, "vdp": url}}]}
    return {"listings": [{"id": target["make"], "build": build, "price": 30000, "miles": 0,
                          "vdp_url": url, "description": "Large cargo area with max storage."}], "num_found": 1}


@pytest.mark.parametrize("cls", [autodev.AutoDevAdapter, marketcheck.MarketCheckAdapter])
@pytest.mark.parametrize("brands", [["Toyota", "Honda", "Ford"], ["honda", "FORD"]])
def test_multiple_general_brands_reach_provider_ingest_and_inventory(conn, monkeypatch, cls, brands):
    def no_network(*args, **kwargs):
        pytest.fail("General-vehicle tests must not call external services")

    monkeypatch.setattr(requests.Session, "request", no_network)
    selected = [target for target in TARGETS if target["make"].casefold() in {b.casefold() for b in brands}]
    source = adapter(cls, [FakeResponse(200, _page(cls, target)) for target in selected])
    source.conn = conn
    monkeypatch.setattr(services, "make_adapter", lambda c, key: source)
    monkeypatch.setattr(services.backup, "daily_backup", lambda c: None)
    monkeypatch.setattr(services.photos, "cache_missing", lambda *args, **kwargs: {"cached": 0})
    monkeypatch.setattr(services.recalls, "refresh", no_network)
    monkeypatch.setattr(services.enrich, "auto_second_opinions", no_network)
    settings = config.default_settings()
    settings["collection"].update(searches=TARGETS, used_only=False, max_distance=0, marketcheck_radius=0,
                                   vpic_enrichment=False, mc_second_opinion=True, max_pages_per_run=3)
    result = services.run_sources(conn, [source.key], settings, brands=brands)
    assert result["status"] == "success" and result["matching"] == len(selected)
    assert result["sources"][0]["api_calls"] == len(source.session.calls) == len(selected)
    assert conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0] == len(selected)
    fields = ("vehicle.make", "vehicle.model") if cls is autodev.AutoDevAdapter else ("make", "model")
    assert [tuple(call["params"][key] for key in fields) for call in source.session.calls] == [
        (target["make"], target["model"]) for target in selected]
    for call in source.session.calls:
        if cls is autodev.AutoDevAdapter:
            assert "retailListing.used" not in call["params"]
        else:
            assert "car_type" not in call["params"]
    frame = queries.apply_filters(queries.inventory_frame(conn, settings), settings["filters"])
    assert set(zip(frame["make"], frame["model"])) == {(t["make"], t["model"]) for t in selected}
    assert set(frame["year"]) == {date.today().year + 1}
    assert set(frame["battery"]) == {"Unknown"}
    assert frame["epa_est_low"].isna().all() and frame["recall_count"].isna().all()
    assert not frame["warranty_expires"].any()
    assert all("subframe" not in text.casefold() for text in frame["to_confirm"])


def test_provider_fallback_years_include_older_and_next_model_years():
    expected_max = date.today().year + 1
    assert autodev.build_params({})["vehicle.year"] == f"2000-{expected_max}"
    assert marketcheck.build_params({})["year"].split(",") == [str(y) for y in range(2000, expected_max + 1)]


def test_mixed_demo_keeps_general_examples_visible_and_outside_rivian_timeline(conn):
    from rivian_finder.ui.inventory import clear_filter_values

    mixed = demo_listings(1, include_general=True)
    assert demo_listings(1) == [listing for listing in mixed if listing.make == "Rivian"]
    assert all(listing.is_demo and listing.url.startswith("https://example.com/") for listing in mixed)
    pipeline.import_listings(conn, mixed, "demo_import")
    settings = config.default_settings()
    frame = queries.apply_filters(queries.inventory_frame(conn, settings), clear_filter_values())
    pairs = set(zip(frame["make"], frame["model"]))
    assert {(t["make"], t["model"]) for t in TARGETS} <= pairs
    before = [dict(row) for row in conn.execute("SELECT * FROM listings WHERE import_method='manual'")]
    for _ in range(2):
        pipeline.run_search(conn, [DemoAdapter(conn)], {"brands": ["Rivian", "Toyota", "Honda", "Ford"]})
    assert before == [dict(row) for row in conn.execute("SELECT * FROM listings WHERE import_method='manual'")]
    assert services.purge_demo(conn) > 0
    assert conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 0
