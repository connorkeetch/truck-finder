"""A named Standard Range package is excluded even when its numeric range is missing."""
import pytest

from conftest import listing
from rivian_finder import pipeline, queries
from rivian_finder.models import AttributeClaim
from rivian_finder.trims import standard_range


@pytest.mark.parametrize("make,model", [
    ("GMC", "Sierra EV"), ("Ford", "F-150 Lightning"), ("Chevrolet", "Silverado EV"),
])
@pytest.mark.parametrize("text", ["Elevation Standard Range", "STANDARD-RANGE", "Standard_Range", "StandardRange"])
def test_explicit_standard_range_labels(make, model, text):
    assert standard_range(make, model, text)


@pytest.mark.parametrize("text", ["Elevation Extended Range", "Max Range", "standard equipment; Extended Range", "", None])
def test_other_or_unknown_packages_stay_eligible(text):
    assert not standard_range("GMC", "Sierra EV", text)


def test_label_is_scoped_to_comparable_ev_trucks():
    assert not standard_range("Rivian", "R1T", "Standard Range")
    assert not standard_range("GMC", "Sierra 1500", "Standard Range")
    assert not standard_range("Ford", "F-150", "Standard Range")


@pytest.mark.parametrize("field", ["title", "trim", "battery"])
def test_standard_range_hidden_from_saved_inventory_and_not_a_near_miss(conn, settings, field):
    attrs = [AttributeClaim("battery", "Standard Range", "medium", "listing")] if field == "battery" else []
    kw = {field: "2026 GMC Sierra EV Elevation Standard Range"} if field != "battery" else {}
    pipeline.import_listings(conn, [listing(make="GMC", model="Sierra EV", year=2026,
        url="https://dealer.example/sierra", attributes=attrs, **kw)], "manual_entry")
    frame = queries.inventory_frame(conn, settings)
    assert frame.iloc[0].range_text == ""
    assert queries.apply_filters(frame, settings["filters"]).empty
    assert not queries.near_miss_mask(frame, settings["filters"]).any()
    assert any("Standard Range" in why for why in queries.why_hidden(frame.iloc[0], settings["filters"]))
    assert conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 1
    settings["collection"]["exclude_standard_range"] = False
    assert len(queries.apply_filters(queries.inventory_frame(conn, settings), settings["filters"])) == 1


def test_extended_max_and_genuinely_unknown_packages_still_show(conn, settings):
    pipeline.import_listings(conn, [listing(sid=str(i), make="GMC", model="Sierra EV", year=2026,
        trim=trim, url=f"https://dealer.example/sierra/{i}")
        for i, trim in enumerate(["Elevation Extended Range", "Denali Max Range", "Elevation"])], "manual_entry")
    frame = queries.inventory_frame(conn, settings)
    assert len(queries.apply_filters(frame, settings["filters"])) == 3


def test_numeric_range_does_not_override_explicit_standard_range_package(conn, settings):
    pipeline.import_listings(conn, [listing(make="GMC", model="Sierra EV", trim="Elevation Standard Range",
        url="https://dealer.example/sierra", attributes=[AttributeClaim("epa_range", "350", "medium", "listing")])],
        "manual_entry")
    assert queries.apply_filters(queries.inventory_frame(conn, settings), settings["filters"]).empty
