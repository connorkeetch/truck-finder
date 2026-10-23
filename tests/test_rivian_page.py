"""Synthetic Rivian page text tests parsing, splitting, and updates without real vehicle identifiers."""
from conftest import FIXTURES, listing

from rivian_finder import attributes, pipeline, queries
from rivian_finder.importers import rivian_page

TEXT = (FIXTURES / "rivian_pages.txt").read_text(encoding="utf-8")


def test_split_and_detect():
    pages = rivian_page.split_pages(TEXT)
    assert len(pages) == 2 and all(rivian_page.looks_like(p) for p in pages)
    assert not rivian_page.looks_like("2023 Rivian R1T, 29k miles, title in hand")
    assert rivian_page.split_pages("random text") == []


def test_parse_quad_page():
    p = rivian_page.parse(rivian_page.split_pages(TEXT)[0])
    assert (p["vin"], p["year"], p["miles"], p["price"]) == ("7FCTGAAA9PN900201", 2023, 21234, 60500)
    assert (p["motor"], p["battery"], p["tonneau"], p["epa_range"]) == ("Quad", "Large", "no", 328)
    assert (p["city"], p["state"], p["exterior_color"], p["wheels"]) == ("Salt Lake City", "UT", "El Cap Granite",
                                                                        '21" Road Wheels')
    assert p["warranty"] == {"warranty_expiration": "2028-04-01", "warranty_miles": 60000,
                             "battery_warranty_expiration": "2031-04-01", "battery_warranty_miles": 175000}
    assert "Rivian Elevation Audio" in p["options"]


def test_parse_performance_dual_and_tonneau():
    page = rivian_page.split_pages(TEXT)[1]
    p = rivian_page.parse(page)
    assert (p["motor"], p["tonneau"], p["city"]) == ("Performance Dual", "no", "Boise")   # not in Rivian's build list
    with_cover = page.replace("Reinforced Underbody Shield\nTotal",
                              "Reinforced Underbody Shield\nTonneau\nPowered Tonneau Cover\nTotal")
    assert rivian_page.parse(with_cover)["tonneau"] == "yes"
    assert {"All-Terrain Upgrade", "All-Terrain Package", "Reinforced Underbody Shield"} <= set(p["options"])
    assert p["warranty"]["battery_warranty_miles"] == 150000


def test_apply_adds_then_updates_with_verified_values(conn, settings):
    page = rivian_page.split_pages(TEXT)[1]
    first = rivian_page.apply(conn, page)
    assert first["added"]
    res = attributes.resolve(conn, first["vehicle_id"])
    assert (res["motor"].value, res["battery"].value, res["tonneau"].value) == ("Performance Dual", "Large", "no")
    assert res["tonneau"].confidence == "verified" and res["warranty_expiration"].value == "2028-09-01"
    row = queries.inventory_frame(conn, settings).iloc[0]
    assert row["warranty_basis"] == "the truck's warranty dates" and row["location"] == "Boise, ID"
    again = rivian_page.apply(conn, page.replace("$59,400", "$58,900"))           # Rivian cut the price
    assert not again["added"] and again["vehicle_id"] == first["vehicle_id"]
    assert conn.execute("SELECT current_price FROM listings WHERE vehicle_id=? AND source_key='rivian'",
                        (first["vehicle_id"],)).fetchone()[0] == 58900


def test_apply_reuses_existing_rivian_link(conn):
    vin = "7FCTGAAA9PN900201"
    url = "https://rivian.com/configurations/inventory/pre-owned/00000000000000000000000000000001"
    pipeline.import_listings(conn, [listing("marketcheck", vin=vin, url=url, price=61000, miles=21234)], "manual_entry")
    rivian_page.apply(conn, rivian_page.split_pages(TEXT)[0])
    rows = conn.execute("SELECT url, current_price FROM listings l JOIN vehicles v ON v.id=l.vehicle_id WHERE v.vin=?",
                        (vin,)).fetchall()
    assert [tuple(r) for r in rows] == [(url, 60500)]                             # updated in place, no duplicate
