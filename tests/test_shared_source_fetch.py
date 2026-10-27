"""Both providers preserve collection identity, call accounting and failure behavior."""
import pytest

from test_custom_search_sources import provider_page
from test_sources import FakeResponse, adapter
from rivian_finder.models import RateLimited, SourceError
from rivian_finder.sources import autodev, marketcheck


TARGETS = [{"make": "Toyota", "model": "Camry"}, {"make": "Honda", "model": "CR-V"}]


@pytest.mark.parametrize("cls,hashes", [
    (autodev.AutoDevAdapter, {"custom": "c47c24334a137b98", "legacy": "34c9abb1004c083b", "empty": "5f451db2ae4e8a6a"}),
    (marketcheck.MarketCheckAdapter, {"custom": "0c9c02b10e27cb68", "legacy": "3d3193222c3b781f", "empty": "7bcc962e81a2c287"}),
])
@pytest.mark.parametrize("kind,selection,expected_calls", [
    ("custom", {"searches": TARGETS}, 2),
    ("legacy", {"include_other_brands": True}, 2),
    ("empty", {"brands": []}, 0),
])
def test_public_scope_hash_and_call_delta_keep_existing_contract(cls, hashes, kind, selection, expected_calls):
    scope = {"year_min": 2020, "year_max": 2027, "max_price": 40000, "max_miles": 60000,
             "home_zip": "80202", "max_distance": 0, "marketcheck_radius": 100,
             "excluded_trims": {"Ford": ["Pro"]}, "exclude_standard_range": True, **selection}
    source = adapter(cls, [FakeResponse(200, provider_page(cls, []))] * expected_calls)
    source.calls = 7
    result = source.fetch(scope)
    assert result.scope_hash == hashes[kind]  # Recorded before the shared-fetch refactor.
    assert result.complete and result.error is None and result.listings == []
    assert result.api_calls == len(source.session.calls) == expected_calls
    assert source.calls == 7 + expected_calls


@pytest.mark.parametrize("cls", [autodev.AutoDevAdapter, marketcheck.MarketCheckAdapter])
def test_one_custom_query_failure_preserves_other_query_results(cls):
    source = adapter(cls, [FakeResponse(401), FakeResponse(200, provider_page(cls, [TARGETS[1]]))])
    result = source.fetch({"searches": TARGETS, "max_pages_per_run": 4})
    assert not result.complete and "rejected the API key" in result.error
    assert [(row.make, row.model) for row in result.listings] == [("Honda", "CR-V")]
    assert result.api_calls == len(source.session.calls) == 2


@pytest.mark.parametrize("cls", [autodev.AutoDevAdapter, marketcheck.MarketCheckAdapter])
def test_all_custom_query_failures_raise_aggregate_error(cls):
    source = adapter(cls, [FakeResponse(401), FakeResponse(401)])
    with pytest.raises(SourceError) as error:
        source.fetch({"searches": TARGETS, "max_pages_per_run": 4})
    assert str(error.value).count("rejected the API key") == 2 and "; " in str(error.value)
    assert source.calls == len(source.session.calls) == 2


@pytest.mark.parametrize("cls", [autodev.AutoDevAdapter, marketcheck.MarketCheckAdapter])
def test_single_query_preserves_specific_exception_after_retries(cls):
    source = adapter(cls, [FakeResponse(429)] * 4)
    with pytest.raises(RateLimited):
        source.fetch({"searches": TARGETS[:1], "max_pages_per_run": 4})
    assert source.calls == len(source.session.calls) == 4
