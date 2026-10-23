"""Brand selection scopes enrichment as well as inventory requests."""
import copy

import pytest

from conftest import FakeAdapter, listing, vin
from rivian_finder import enrich, photos, pipeline, services
from rivian_finder.models import FetchResult
from test_photos import ImageSession


@pytest.mark.parametrize("brands", [[], ["Tesla"], [123], ["Ford", "Tesla"]])
def test_invalid_brand_selection_does_not_start_any_work(conn, settings, monkeypatch, brands):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid selection started work")

    monkeypatch.setattr(services, "make_adapter", unexpected)
    monkeypatch.setattr(services, "available_sources", unexpected)
    monkeypatch.setattr(services.backup, "daily_backup", unexpected)
    result = services.run_sources(conn, settings=settings, brands=brands)
    assert result["status"] == "failed"
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


@pytest.mark.parametrize("brands,keys,want_mc", [
    (["Ford"], ["autodev", "marketcheck"], False),
    (["Chevrolet", "GMC"], ["marketcheck"], False),
    (["Rivian"], ["autodev"], False),
    (["Rivian"], ["marketcheck"], True),
    (["Rivian", "Ford", "Chevrolet", "GMC"], ["marketcheck"], True),
])
def test_enrichment_stays_with_selected_brands_and_connectors(conn, settings, monkeypatch, brands, keys, want_mc):
    calls = {}
    original_settings = copy.deepcopy(settings)
    def adapter(c, key):
        result = FakeAdapter(key, [FetchResult([], True, "s")])
        result.calls = 0
        return result
    monkeypatch.setattr(services, "make_adapter", adapter)
    monkeypatch.setattr(services.backup, "daily_backup", lambda c: None)
    monkeypatch.setattr(services.photos, "cache_missing", lambda c, **kw: calls.setdefault("photos", kw))
    monkeypatch.setattr(services.enrich, "enrich_vehicles", lambda c, **kw: calls.setdefault("vpic", kw))
    monkeypatch.setattr(services.recalls, "refresh", lambda c: calls.setdefault("recalls", {}))
    monkeypatch.setattr(services.enrich, "auto_second_opinions", lambda c, s, **kw: calls.setdefault("mc", kw))
    result = services.run_sources(conn, keys, settings, brands=brands)
    assert result["status"] == "success"
    assert set(calls["photos"]["brands"]) == set(brands)
    assert set(calls["vpic"]["brands"]) == set(brands)
    assert ("recalls" in calls) == ("Rivian" in brands)
    assert ("mc" in calls) == want_mc
    assert settings == original_settings


def test_brand_selection_is_normalized_before_request(conn, settings, monkeypatch):
    scopes = []

    class Capture(FakeAdapter):
        def fetch(self, scope):
            scopes.append(scope)
            return super().fetch(scope)

    monkeypatch.setattr(services, "make_adapter", lambda c, key: Capture(key, [FetchResult([], True, "s")]))
    monkeypatch.setattr(services.backup, "daily_backup", lambda c: None)
    monkeypatch.setattr(services.photos, "cache_missing", lambda *a, **kw: {})
    monkeypatch.setattr(services.enrich, "enrich_vehicles", lambda *a, **kw: {})
    services.run_sources(conn, ["autodev"], settings, brands=[" ford ", "FORD", "gmc"])
    assert scopes[0]["brands"] == ["Ford", "GMC"]


def test_vpic_only_decodes_selected_brand(conn, monkeypatch):
    rivian_vin, ford_vin = vin(501), vin(502)
    pipeline.import_listings(conn, [listing(vin=rivian_vin),
        listing(vin=ford_vin, make="Ford", model="F-150 Lightning")], "manual_entry")
    seen = []

    def decode(vins, **kwargs):
        seen.extend(vins)
        return {value: {"ModelYear": "2024"} for value in vins}

    monkeypatch.setattr(enrich, "decode_batch", decode)
    assert enrich.enrich_vehicles(conn, brands=["Ford"])["decoded"] == 1
    assert seen == [ford_vin]
    assert enrich.enrich_vehicles(conn, brands=[])["decoded"] == 0
    assert seen == [ford_vin]


def test_photo_downloads_only_selected_brand(conn):
    pipeline.import_listings(conn, [
        listing("dealer", sid="r", vin=vin(503), photo_url="https://img.example/rivian.jpg"),
        listing("dealer", sid="f", vin=vin(504), make="Ford", model="F-150 Lightning",
                photo_url="https://img.example/ford.jpg"),
    ], "manual_entry")
    session = ImageSession()
    assert photos.cache_missing(conn, brands=["Ford"], session=session) == {"cached": 1, "failed": 0}
    assert session.urls == ["https://img.example/ford.jpg"]
    assert photos.cache_missing(conn, brands=[], session=session) == {"cached": 0, "failed": 0}
