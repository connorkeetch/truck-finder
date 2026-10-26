"""Recorded price-cut summaries keep the source, observation window and sparse evidence visible."""
import copy

import pytest

from rivian_finder.ui import common, price_insights


def example(make="Rivian"):
    return {"vehicle": {"vehicle_id": 1, "vin": "TESTVIN", "make": make, "model": "R1T" if make == "Rivian" else "F-150 Lightning",
                        "year": 2024, "listing_id": 4, "source": "autodev", "source_url": "https://rivian.com/pre-owned/TESTVIN",
                        "seller_name": "Rivian" if make == "Rivian" else "Ford dealer", "listing_status": "removed",
                        "first_observed": "2026-10-20T12:00:00Z", "latest_observed": "2026-10-25T12:00:00Z",
                        "priced_observations": 5, "observation_days": 5, "history_status": "Repeat-day history",
                        "drops_count": 3, "increases_count": 1, "total_reductions": 4500, "net_change": -3000,
                        "mean_cut": 1500, "median_cut": 1500, "interval_count": 2, "mean_interval_days": 1.5,
                        "cuts": [{"previous_observed_at": "2026-10-20T12:00:00Z", "detected_at": "2026-10-21T12:00:00Z",
                                  "old_price": 60000, "new_price": 58500, "amount": 1500}]},
            "rivian_seller": {"vehicle_count": 53, "cut_bearing_vehicles": 25, "repeat_day_vehicles": 26,
                               "total_cuts": 26, "mean_cut": 2125.1923, "mean_interval_days": 1.41430556,
                               "interval_count": 1, "interval_vehicles": 1, "first_observed": "2026-10-19T12:00:00Z",
                               "latest_observed": "2026-10-25T12:00:00Z"},
            "caveat": "These observations do not reveal the seller's actual change time."}


@pytest.fixture
def render_app(conn, monkeypatch):
    from streamlit.testing.v1 import AppTest
    calls = []
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common.services, "run_sources", lambda *args, **kwargs: pytest.fail("Rendering must not search."))
    monkeypatch.setattr(common, "inventory", lambda *args: pytest.fail("This panel does not need inventory."))

    def run(result):
        def summary(c, vid):
            calls.append((c, vid))
            return copy.deepcopy(result)
        monkeypatch.setattr(price_insights.insights, "for_vehicle", summary)
        before = conn.total_changes
        app = AppTest.from_string("""
from rivian_finder.ui import common, price_insights
price_insights.render(common.conn(), 1)
""").run(timeout=10)
        assert not app.exception
        assert conn.total_changes == before
        assert calls[-1] == (conn, 1)
        return app

    return run


def test_cut_amounts_net_change_source_and_cohort_support_are_explicit(render_app):
    app = render_app(example())
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Observed cuts"] == "3"
    assert metrics["Average cut"] == "$1,500"
    assert metrics["Total reductions"] == "$4,500"
    assert metrics["Net price change"] == "-$3,000"
    assert metrics["Rivian seller: average cut"] == "$2,125"
    assert metrics["Rivian seller: observed gap"] == "1.4 days"
    assert any("26 observed cuts across 25 trucks" in item.value and "53 trucks tracked" in item.value for item in app.caption)
    assert any("1 interval(s) from 1 truck(s)" in item.value for item in app.caption)
    assert any("Insufficient history for a typical schedule" in item.value for item in app.info)
    assert any("recorded status removed" in item.value for item in app.caption)
    assert any("distinct UTC dates" in item.value for item in app.caption)
    assert any("provider-reported seller identities" in item.value and "regardless of Inventory filters" in item.value
               and "not complete nationwide inventory or a live availability check" in item.value for item in app.caption)
    table = app.dataframe[0].value
    assert table.iloc[0]["Before"] == 60000 and table.iloc[0]["After"] == 58500 and table.iloc[0]["Cut amount"] == 1500
    assert table.iloc[0]["Source"] == "Auto.dev" and table.iloc[0]["Listing"] == "https://rivian.com/pre-owned/TESTVIN"


def test_other_makes_show_their_own_history_without_rivian_benchmark(render_app):
    result = example("Ford")
    result["vehicle"].update(interval_count=1, mean_interval_days=2.0)
    app = render_app(result)
    assert not any(metric.label.startswith("Rivian seller:") for metric in app.metric)
    assert not any("Official Rivian" in item.value for item in app.markdown)
    assert any("Only one observed interval" in item.value for item in app.info)
    assert any("seller's actual change time is unknown" in item.value for item in app.caption)


@pytest.mark.parametrize("days", [1, 3])
def test_no_observed_cuts_do_not_imply_zero_day_schedule(render_app, days):
    result = example("Ford")
    result["vehicle"].update(drops_count=0, mean_cut=None, total_reductions=0, net_change=1000,
                              observation_days=days, interval_count=0, mean_interval_days=None, cuts=[])
    app = render_app(result)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Average cut"] == "—"
    assert metrics["Net price change"] == "+$1,000"
    assert metrics["Observed gap between cuts"] == "Not enough history"
    assert any("Not enough history" in item.value for item in app.info)
    assert not app.dataframe


def test_no_priced_history_renders_cleanly(render_app):
    result = example("Ford")
    result["vehicle"].update(priced_observations=0, first_observed=None, latest_observed=None)
    app = render_app(result)
    assert any("No priced observations yet" in item.value for item in app.info)
    assert not app.metric and not app.dataframe


def test_missing_or_merged_vehicle_has_no_fabricated_stats(render_app):
    app = render_app({"vehicle": None, "rivian_seller": {}, "caveat": ""})
    assert any("No usable recorded price history" in item.value for item in app.info)
    assert not app.metric and not app.dataframe
