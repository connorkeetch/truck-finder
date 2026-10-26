"""Local deal/seller/drop filters and deterministic inventory sorting require no provider calls."""
import numpy as np
import pandas as pd
import pytest

from conftest import listing, vin
from rivian_finder import config, deals, pipeline, queries
from test_deals import market


@pytest.fixture
def inventory_factory(conn, settings):
    pipeline.import_listings(conn, [listing(vin=vin(950))], "manual_entry")
    base = queries.inventory_frame(conn, settings).iloc[0].to_dict()

    def make(rows):
        return pd.DataFrame([{**base, "vehicle_id": i + 1, **row} for i, row in enumerate(rows)])

    return make


@pytest.mark.parametrize("label,expected", [
    *((label, label) for label in deals.DEAL_TYPES),
    ("Great deal (accident reported)", "Great deal"),
    ("⚠ Check title (accident reported)", "⚠ Check title"),
    (None, "Not rated"), (np.nan, "Not rated"), (pd.NA, "Not rated"),
    ("Unknown rating", "Not rated"), (" Great deal", "Not rated"),
])
def test_deal_types_keep_warnings_and_handle_missing_labels(label, expected):
    assert deals.deal_type(label) == expected


def test_small_stock_branded_titles_have_their_own_unrated_category():
    stock = market(n=5)
    stock.loc[0, "title_status"] = "branded"
    labels = deals.annotate(stock)["deal_label"]
    assert labels.iloc[0] == "Not rated (branded title)"
    assert labels.iloc[1:].eq("Not rated").all()


def test_new_filters_default_to_unrestricted_and_preserve_saved_preferences():
    fresh = config.default_settings()["filters"]
    assert fresh["deal_types"] == fresh["seller_types"] == [] and not fresh["price_drops_only"]
    saved = config.merge_settings({"filters": {"deal_types": ["Good deal"], "seller_types": ["private"],
                                                "price_drops_only": True}})["filters"]
    assert saved["deal_types"] == ["Good deal"] and saved["seller_types"] == ["private"] and saved["price_drops_only"]


@pytest.mark.parametrize("category", deals.DEAL_TYPES)
def test_deal_filter_matches_only_the_selected_category(inventory_factory, settings, category):
    rows = inventory_factory([{"deal_label": label} for label in deals.DEAL_TYPES])
    f = {**settings["filters"], "near_misses": False, "hide_branded_title": False, "deal_types": [category]}
    assert queries.apply_filters(rows, f)["deal_label"].tolist() == [category]


def test_accident_suffix_and_unrated_values_filter_consistently(inventory_factory, settings):
    rows = inventory_factory([{"deal_label": "Good deal (accident reported)"}, {"deal_label": "Good deal"},
                              {"deal_label": "Not rated (branded title)"}, {"deal_label": pd.NA},
                              {"deal_label": "Unexpected rating"}])
    f = {**settings["filters"], "near_misses": False, "deal_types": ["Good deal"]}
    assert queries.apply_filters(rows, f)["vehicle_id"].tolist() == [1, 2]
    assert queries.apply_filters(rows, {**f, "deal_types": ["Not rated"]})["vehicle_id"].tolist() == [4, 5]
    assert queries.apply_filters(rows, {**f, "deal_types": ["Not rated (branded title)"]})["vehicle_id"].tolist() == [3]


def test_seller_and_price_drop_filters_treat_missing_values_as_unknown(inventory_factory, settings):
    rows = inventory_factory([{"seller_type": "dealer", "price_drops": 2},
                              {"seller_type": " Private ", "price_drops": 1},
                              {"seller_type": "", "price_drops": None},
                              {"seller_type": pd.NA, "price_drops": 0},
                              {"seller_type": "unrecognized", "price_drops": "3"}])
    f = {**settings["filters"], "near_misses": False, "seller_types": ["private"], "price_drops_only": True}
    assert queries.apply_filters(rows, f)["vehicle_id"].tolist() == [2]
    assert queries.apply_filters(rows, {**f, "seller_types": ["unknown"]})["vehicle_id"].tolist() == [5]
    assert queries.apply_filters(rows, {**f, "seller_types": ["unknown"], "price_drops_only": False})["vehicle_id"].tolist() == [3, 4, 5]


@pytest.mark.parametrize("overrides,failing", [
    ({"deal_label": "Fair price"}, "deal type"),
    ({"seller_type": "private"}, "seller type"),
    ({"price_drops": 0}, "price drops"),
])
def test_near_misses_never_bypass_the_new_filters(inventory_factory, settings, overrides, failing):
    rows = inventory_factory([{"price": 66000, "deal_label": "Good deal", "seller_type": "dealer", "price_drops": 1},
                              {"price": 66000, "deal_label": "Good deal", "seller_type": "dealer", "price_drops": 1, **overrides}])
    f = {**settings["filters"], "max_price": 65000, "near_misses": True,
         "deal_types": ["Good deal"], "seller_types": ["dealer"], "price_drops_only": True}
    assert queries.apply_filters(rows, f)["vehicle_id"].tolist() == [1]
    assert not queries.filter_checks(rows, f)[failing].iloc[1]


def test_lookup_explains_each_new_filter(inventory_factory, settings):
    row = inventory_factory([{"deal_label": "Fair price", "seller_type": "dealer", "price_drops": 0}]).iloc[0]
    f = {**settings["filters"], "deal_types": ["Good deal"], "seller_types": ["private"], "price_drops_only": True}
    reasons = queries.why_hidden(row, f)
    assert any("deal type is Fair price" in reason for reason in reasons)
    assert any("seller type is dealer" in reason for reason in reasons)
    assert any("no recorded price drops" in reason for reason in reasons)


@pytest.mark.parametrize("label,column,values", [
    ("Fit score", "fit_score", [50, 90, None]),
    ("Adjusted price ↑", "adjusted_price", [60000, 40000, None]),
    ("Price ↑", "price", [60000, 40000, None]),
    ("Price ↓", "price", [40000, 60000, None]),
    ("Miles ↑", "miles", [30000, 10000, None]),
    ("Miles ↓", "miles", [10000, 30000, None]),
    ("Distance ↑", "distance_mi", [600, 100, None]),
    ("Distance ↓", "distance_mi", [100, 600, None]),
    ("Lowest monthly payment", "est_monthly", [900, 600, None]),
    ("Longest range", "range_mi", [250, 400, None]),
    ("Highest towing capacity", "tow_capacity_lbs", [7000, 10000, None]),
    ("Newest model year", "year", [2023, 2025, None]),
    ("Biggest savings vs market", "deal_delta", [-1000, -5000, None]),
    ("Biggest price drop", "price_change", [-1000, -5000, None]),
    ("Longest listed", "days_listed", [10, 90, None]),
    ("Newest", "first_seen", ["2026-10-24T12:00:00Z", "2026-10-25T12:00:00Z", None]),
    ("Recently changed price", "last_price_change_at", ["2026-10-24T12:00:00Z", "2026-10-25T12:00:00Z", None]),
    ("Link problems first", "link_result", ["ok", "gone", ""]),
])
def test_sort_orders_keep_unknowns_last_and_preserve_statuses(label, column, values):
    rows = pd.DataFrame({"vehicle_id": [30, 10, 20], "price": [50000, 45000, 10000],
                         "status": ["active", "missing", "removed"], column: values})
    original = rows.copy(deep=True)
    sorted_rows = queries.sort_inventory(rows, label)
    assert sorted_rows["vehicle_id"].tolist() == [10, 30, 20]
    assert sorted_rows["status"].tolist() == ["missing", "active", "removed"]
    pd.testing.assert_frame_equal(rows, original)
    assert list(sorted_rows.columns) == list(rows.columns)


def test_best_deals_keep_title_warnings_and_unrated_stock_after_valid_ratings():
    rows = pd.DataFrame({"vehicle_id": list(range(8)), "deal_label": list(deals.DEAL_TYPES),
                         "deal_pct": [-0.1, -0.05, 0, 0.05, 0.2, -0.8, np.nan, -0.9],
                         "price": [50000, 51000, 52000, 53000, 54000, 20000, 30000, 10000]})
    for label in ("Best deal", "Deal rating"):
        result = queries.sort_inventory(rows.iloc[::-1], label)
        assert result["vehicle_id"].tolist()[:5] == [0, 1, 2, 3, 4]
        assert set(result["vehicle_id"].tolist()[5:]) == {5, 6, 7}


def test_best_deal_and_deal_rating_have_their_distinct_tie_breakers():
    rows = pd.DataFrame({"vehicle_id": [1, 2, 3], "deal_label": ["Great deal", "Great deal", "Great deal (accident reported)"],
                         "deal_pct": [-0.09, -0.085, -0.1], "price": [50000, 45000, 48000]})
    assert queries.sort_inventory(rows, "Best deal")["vehicle_id"].tolist() == [3, 1, 2]
    assert queries.sort_inventory(rows, "Deal rating")["vehicle_id"].tolist() == [2, 3, 1]


def test_sort_ties_use_price_then_id_and_handle_duplicate_indices():
    rows = pd.DataFrame({"vehicle_id": [3, 2, 1], "fit_score": [80, 80, 80], "price": [50000, 45000, 45000]}, index=[0, 0, 1])
    result = queries.sort_inventory(rows, "Fit score")
    assert result["vehicle_id"].tolist() == [1, 2, 3] and len(result) == 3


def test_sort_minimal_frames_numeric_strings_and_missing_columns():
    rows = pd.DataFrame({"vehicle_id": [2, 1, 3], "price": ["60000", "9000", None]})
    assert queries.sort_inventory(rows, "Price ↑")["vehicle_id"].tolist() == [1, 2, 3]
    for label in queries.SORT_OPTIONS:
        assert len(queries.sort_inventory(rows, label)) == 3
    assert queries.sort_inventory(rows, "Old saved option")["vehicle_id"].tolist() == [1, 2, 3]
    assert queries.sort_inventory(rows.iloc[:0], "Price ↓").empty


def test_recent_price_sort_includes_increases_and_excludes_unchanged_observations(conn, settings):
    entries = [listing(vin=vin(i), price=60000) for i in (960, 961, 962)]
    pipeline.import_listings(conn, entries, "manual_entry")
    pipeline.import_listings(conn, [listing(vin=vin(960), price=58000), listing(vin=vin(961), price=61000),
                                    listing(vin=vin(962), price=60000)], "manual_entry")
    conn.execute("UPDATE change_events SET created_at='2026-10-24T12:00:00Z' WHERE event_type='price_drop'")
    conn.execute("UPDATE change_events SET created_at='2026-10-25T12:00:00Z' WHERE event_type='price_increase'")
    frame = queries.inventory_frame(conn, settings)
    assert queries.sort_inventory(frame, "Recently changed price")["vin"].tolist() == [vin(961), vin(960), vin(962)]
    assert pd.isna(frame.set_index("vin").loc[vin(962), "last_price_change_at"])
