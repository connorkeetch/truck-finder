"""Trim exclusions stay consistent across older fleet labels and newer trim families."""
import pytest

from conftest import FakeAdapter, listing
from rivian_finder import pipeline, queries
from rivian_finder.models import FetchResult
from rivian_finder.trims import excluded_trim, trim_label, trim_name


EXCLUSIONS = {"Ford": ["Pro"], "Chevrolet": ["WT"]}


@pytest.mark.parametrize("make,model,trim,expected", [
    ("Ford", "F-150 Lightning", "Pro", True),
    ("FORD", "F-150 Lightning", "PRO Extended Range", True),
    ("Ford", "F-150 Lightning", "Ford F-150 Lightning Pro", True),
    ("Ford", "F-150 Lightning", "XLT", False),
    ("Ford", "F-150 Lightning", "Lariat with Pro Power Onboard", False),
    ("Ford", "F-150 Lightning", "Pro Power Onboard", False),
    ("Ford", "F-150", "Pro", False),
    ("Chevrolet", "Silverado EV", "Work Truck w/4WT", True),
    ("Chevrolet", "Silverado EV", "Work Truck Extended Range Fleet", True),
    ("Chevrolet", "Silverado EV", "WT - Extended Range", True),
    ("Chevrolet", "Silverado EV", "3WT", True),
    ("Chevrolet", "Silverado EV", "LT Extended Range", False),
    ("Chevrolet", "Silverado EV", "Standard Range LT", False),
    ("Chevrolet", "Silverado EV", "RST", False),
    ("Chevrolet", "Silverado EV", None, False),
    ("GMC", "Sierra EV", "Elevation Standard Range", False),
    ("Rivian", "R1T", "Adventure", False),
])
def test_lowest_trim_only(make, model, trim, expected):
    assert excluded_trim(make, model, trim, EXCLUSIONS) == expected


def test_normalized_trim_labels():
    assert trim_label("Chevrolet", "Silverado EV", "Standard Range LT") == "Chevrolet · LT"
    assert trim_label("Ford", "F-150 Lightning", "XLT Extended Range") == "Ford · XLT"
    assert trim_name("GMC", "Sierra EV", "Denali Edition 1") == "Denali"
    assert not excluded_trim("Ford", "F-150 Lightning", "Pro", {})


def test_existing_base_trucks_hidden_without_deleting_and_positive_trim_filter(conn, settings):
    trucks = [listing(sid=str(i), make=make, model=model, trim=trim, url=f"https://dealer.example/{i}")
              for i, (make, model, trim) in enumerate([
                  ("Ford", "F-150 Lightning", "Pro"), ("Ford", "F-150 Lightning", "XLT"),
                  ("Chevrolet", "Silverado EV", "Work Truck Fleet"),
                  ("Chevrolet", "Silverado EV", "LT Extended Range"),
                  ("Chevrolet", "Silverado EV", "LT Max Range"),
              ])]
    pipeline.import_listings(conn, trucks, "manual_entry")
    frame = queries.inventory_frame(conn, settings)
    eligible = queries.apply_filters(frame, settings["filters"])
    assert set(eligible.trim) == {"XLT", "LT Extended Range", "LT Max Range"}
    assert conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 5
    filtered = queries.apply_filters(frame, {**settings["filters"], "trims": ["Chevrolet · LT"]})
    assert set(filtered.trim) == {"LT Extended Range", "LT Max Range"}
    assert "excluded trim" in queries.why_hidden(frame[frame.trim.eq("Pro")].iloc[0], settings["filters"])[0]
    settings["collection"]["excluded_trims"] = {}
    assert len(queries.apply_filters(queries.inventory_frame(conn, settings), settings["filters"])) == 5


def test_complete_scan_does_not_mark_excluded_existing_trucks_missing(conn):
    low = listing(sid="base-pro", make="Ford", model="F-150 Lightning", trim="Pro")
    adapter = FakeAdapter("autodev", [FetchResult([low], True, "same"), FetchResult([], True, "same")])
    scope = {"include_other_brands": True, "excluded_trims": EXCLUSIONS}
    pipeline.run_search(conn, [adapter], scope)
    result = pipeline.run_search(conn, [adapter], scope)
    assert result["counts"]["disappeared"] == 0
    assert conn.execute("SELECT status FROM listings").fetchone()[0] == "active"
