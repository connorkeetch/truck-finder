"""Card view data: price-tag colors, combined fields, warning chips."""
from conftest import listing, vin

from rivian_finder import attributes, pipeline, queries
from rivian_finder.ui import cards


def test_deal_colors():
    assert cards.deal_color("Great deal") == "#2ea043"
    assert cards.deal_color("Good deal (accident reported)") == "#7bc96f"
    assert cards.deal_color("Overpriced") == "#e5534b"
    assert cards.deal_color("⚠ Check title") == "#e3b341"
    assert cards.deal_color("Not rated (branded title)") == cards.NOT_RATED == cards.deal_color(None)


def _cards(conn, settings, f=None, picks=()):
    inv = queries.inventory_frame(conn, settings)
    f = f or {**settings["filters"], "max_price": 65000, "max_miles": 40000}
    df = inv.assign(photo="", _near=False)
    return {c["vid"]: c for c in cards.payload(df, set(picks), f)}, inv


def test_card_fields_and_discount(conn, settings):
    v = vin(901)
    pipeline.import_listings(conn, [listing(vin=v, price=65590, miles=19607, url="https://www.carvana.com/vehicle/4596079",
                                            seller_name="Carvana", city="Las Vegas", state="NV", zip="89101")],
                             "manual_entry")
    out, inv = _cards(conn, settings)
    vid = int(inv.loc[inv["vin"] == v, "vehicle_id"].iloc[0])
    c = out[vid]
    assert c["price"] == "$64,590" and c["list_price"] == "$65,590"            # Carvana trade-in discount
    assert c["miles"] == "19,607 mi" and c["location"] == "Las Vegas, NV" and c["distance"].endswith("mi away")
    assert c["shipping"] == "$290 ship" and c["seller"] == "Carvana"          # Carvana's fee from Las Vegas
    assert c["warranty"] == "Warranty: add in-service date" and not c["selected"]


def test_card_chips(conn, settings):
    v = vin(902)
    pipeline.import_listings(conn, [listing(vin=v, price=66000, miles=12000, url="https://d.example/vdp/1")], "manual_entry")
    inv = queries.inventory_frame(conn, settings)
    vid = int(inv.loc[inv["vin"] == v, "vehicle_id"].iloc[0])
    attributes.set_override(conn, vid, "title_status", "branded")
    inv = queries.inventory_frame(conn, settings)
    df = inv.assign(photo="", _near=inv["vehicle_id"] == vid)
    c = {x["vid"]: x for x in cards.payload(df, {vid}, {"max_price": 65000, "max_miles": 40000, "count_discounts": True})}[vid]
    labels = [t for t, _ in c["chips"]]
    assert "Branded title" in labels and "Near miss: $1,000 over max" in labels and c["selected"]


def test_payload_is_strict_json_even_with_blank_fields(conn, settings):
    """A hand-added truck has no photo URL, location or seller link; NaN must never reach the browser."""
    import json
    from rivian_finder.importers.manual import listing_from_fields
    pipeline.import_listings(conn, [listing_from_fields({"url": "https://www.facebook.com/marketplace/item/1106055491858372/",
                                                         "year": "2023", "price": "59500", "miles": "29000"})],
                             "manual_entry")
    inv = queries.inventory_frame(conn, settings)
    df = inv.assign(photo=float("nan"), _near=False)                 # what add_photo_column yields with no photo
    out = cards.payload(df, set(), settings["filters"])
    json.dumps(out, allow_nan=False)                                   # raises on NaN / Infinity
    assert out[0]["photo"] == "" and out[0]["distance"] == ""


def test_shipping_text():
    assert cards._shipping_text(290.0, "Carvana delivery fee est. ($290 within 450 mi…)") == "$290 ship"
    assert cards._shipping_text(0.0, "Local pickup (within 150 mi)") == "local pickup"
    assert cards._shipping_text(0.0, "Included by Vroom (confirm any transfer fee)") == "ship included"
    assert cards._shipping_text(0.0, "Distance unknown — default from Settings") == "shipping unknown"
    assert cards._shipping_text(float("nan"), "") == ""
