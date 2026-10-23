"""Subframe thresholds use fabricated VIN descriptors and serials, never actual listings."""
import pytest
from conftest import listing

from rivian_finder import attributes, pipeline, queries, subframe
from rivian_finder.vin import with_check_digit


def synthetic_vin(year_code, serial):
    """Invented ZZZZ descriptor keeps threshold tests independent of real vehicle identifiers."""
    return with_check_digit(f"7FCTZZZZ0{year_code}N{serial:06d}")


@pytest.mark.parametrize("vin,status", [
    (synthetic_vin("N", 8000), "welded"),
    (synthetic_vin("P", 17000), "welded"),
    (synthetic_vin("P", 18000), "unsure"),
    (synthetic_vin("P", 19000), "unsure"),
    (synthetic_vin("P", 20500), "unsure"),
    (synthetic_vin("P", 27000), "cast"),
    (synthetic_vin("R", 32000), "cast"),
    (with_check_digit("7PDSZZZZ0SN900001"), "unknown"),  # non-R1T prefix
    ("", "unknown"),
])
def test_estimate(vin, status):
    assert subframe.estimate(vin)[0] == status


def _truck(conn, vin):
    pipeline.import_listings(conn, [listing(vin=vin, price=55000, miles=20000)], "manual_entry")
    return conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin,)).fetchone()[0]


def test_filter_and_override(conn, settings):
    welded = _truck(conn, synthetic_vin("P", 17000))
    cast = _truck(conn, synthetic_vin("P", 27000))
    f = {**settings["filters"], "subframes": ["cast"], "near_misses": False}
    inv = queries.inventory_frame(conn, settings)
    assert set(queries.apply_filters(inv, f)["vehicle_id"]) == {cast}
    why = queries.why_hidden(inv[inv["vehicle_id"] == welded].iloc[0], f)
    assert why == ["front subframe is welded (your filter: Cast)"]
    attributes.set_override(conn, welded, "front_subframe", "cast", "Seller: replaced under warranty")
    inv = queries.inventory_frame(conn, settings)
    row = inv[inv["vehicle_id"] == welded].iloc[0]
    assert (row["subframe"], row["subframe_note"]) == ("cast", "verified by you")
    assert set(queries.apply_filters(inv, f)["vehicle_id"]) == {cast, welded}


def test_default_filter_keeps_everything(conn, settings):
    _truck(conn, synthetic_vin("P", 17000))
    inv = queries.inventory_frame(conn, settings)
    assert "subframe" not in queries.filter_checks(inv, settings["filters"])
