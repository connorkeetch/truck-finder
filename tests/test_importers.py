"""Email alerts, paste capture, the localhost capture receiver, and CSV/JSON import."""
import json
import urllib.error
import urllib.request

import pytest
from conftest import FIXTURES

from rivian_finder import db, pipeline
from rivian_finder.importers import capture, email_alerts, manual
from rivian_finder.importers.capture_server import CaptureServer


def test_unwrap_tracking_redirect():
    url = "https://click.example/track?u=https%3A%2F%2Fwww.autotrader.com%2Fcars-for-sale%2Fvehicle%2F711000001"
    assert email_alerts.unwrap_url(url) == "https://www.autotrader.com/cars-for-sale/vehicle/711000001"


def test_autotrader_style_alert():
    meta, items = email_alerts.parse_eml_bytes((FIXTURES / "synthetic_autotrader_alert.eml").read_bytes())
    assert "SYNTHETIC" in meta["subject"]
    by_id = {i.source_listing_id: i for i in items}
    assert len(items) == 3                                          # photo + title links collapse to one listing
    assert set(by_id) == {"711000001", "711000002", "711000003"}
    first = by_id["711000001"]
    assert first.source_key == "autotrader" and first.import_method == "email"
    assert (first.year, first.price, first.miles) == (2024, 58990, 14250)
    assert first.vin == "7FCTGBAL2RN900101"
    assert (first.city, first.state) == ("Draper", "UT")
    assert first.seller_name == "Example EV Dealer"
    assert by_id["711000002"].seller_name == "Example Motors"
    assert {c.field: c.value for c in first.attributes}["tonneau"] == "yes"
    assert not email_alerts.looks_like_rivian(by_id["711000003"])   # the F-150 gets unticked for review
    assert email_alerts.looks_like_rivian(by_id["711000002"])


def test_cars_com_alert_uses_current_price():
    _, items = email_alerts.parse_eml_bytes((FIXTURES / "synthetic_cars_com_alert.eml").read_bytes())
    assert len(items) == 1
    it = items[0]
    assert it.source_key == "cars_com"
    assert it.price == 64900 and it.miles == 6100 and it.state == "CO"


def test_pasted_plain_text_alert():
    items = email_alerts.parse_pasted((FIXTURES / "synthetic_ksl_alert.txt").read_text())
    assert [i.source_listing_id for i in items] == ["9900001", "9900002"]
    assert items[0].price == 52000 and items[0].source_key == "ksl"
    # values must not bleed from the first listing into the second
    assert (items[1].year, items[1].price, items[1].miles, items[1].city) == (2024, 59500, 12400, "Lehi")


def test_plain_text_listings_sharing_a_paragraph_stay_separate():
    text = ("2023 Rivian R1T $50,000 30,000 miles https://cars.ksl.com/listing/1111111\n"
            "2024 Rivian R1T $60,000 10,000 miles https://cars.ksl.com/listing/2222222\n")
    a, b = email_alerts.parse_pasted(text)
    assert (a.price, b.price) == (50000, 60000)


def test_email_import_saves_without_marking_missing(conn):
    _, items = email_alerts.parse_eml_bytes((FIXTURES / "synthetic_autotrader_alert.eml").read_bytes())
    s = pipeline.import_listings(conn, [i for i in items if email_alerts.looks_like_rivian(i)], "email_import")
    assert s["counts"]["new_listing"] == 2
    # re-importing the same alert updates instead of duplicating
    pipeline.import_listings(conn, [i for i in items if email_alerts.looks_like_rivian(i)], "email_import")
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 2


def test_paste_capture_draft():
    d = capture.draft_from_text("2024 Rivian R1T Adventure Quad-Motor Max Pack. $62,900. 14,250 miles. "
                                "Powered tonneau cover. Located in Provo, UT 84601. Seller: Example Private Party.",
                                "https://cars.ksl.com/listing/1234567")
    assert (d["source"], d["source_listing_id"], d["price"], d["miles"], d["year"]) == ("ksl", "1234567", 62900, 14250, 2024)
    assert d["seller_name"] == "Example Private Party"
    nl = capture.listing_from_draft(d)
    assert nl.import_method == "capture"
    assert {c.field for c in nl.attributes} >= {"battery", "motor", "tonneau"}


def test_facebook_capture_is_blocked():
    assert capture.capture_blocked("https://www.facebook.com/marketplace/item/123")
    assert not capture.capture_blocked("https://cars.ksl.com/listing/1")


@pytest.fixture
def server(tmp_path):
    path = tmp_path / "cap.db"
    db.connect(path).close()
    srv = CaptureServer(path, port=0).start()
    yield srv, path
    srv.stop()


def _post(port, payload, origin=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/capture", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **({"Origin": origin} if origin else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_capture_server_accepts_extension_and_rejects_web_pages(server):
    srv, path = server
    status, body = _post(srv.port, {"url": "https://dealer.example/r1t", "title": "R1T", "text": "$60,000"},
                         origin="chrome-extension://abc")
    assert status == 200 and body["ok"]
    assert _post(srv.port, {"url": "x", "text": "y"}, origin="https://evil.example")[0] == 403
    assert _post(srv.port, {"url": "https://www.facebook.com/marketplace/item/1", "text": "y"})[0] == 422
    c = db.connect(path)
    rows = capture.pending(c)
    assert len(rows) == 1 and rows[0]["origin"] == "extension"


def test_capture_server_refuses_non_localhost_bind(tmp_path):
    with pytest.raises(ValueError):
        CaptureServer(tmp_path / "x.db", host="0.0.0.0")


def test_csv_import_round_trip(conn):
    items = manual.parse_csv(manual.csv_template())
    assert len(items) == 1
    it = items[0]
    assert (it.year, it.price, it.miles, it.state) == (2024, 59990, 18000, "UT")
    fields = {c.field: c.value for c in it.attributes}
    assert fields["battery"] == "Large" and fields["tonneau"] == "yes"
    s = pipeline.import_listings(conn, items, "csv_import")
    assert s["counts"]["new_listing"] == 1


def test_csv_cannot_claim_verified_tonneau():
    csv_text = "url,price,tonneau\nhttps://x.example/1,50000,yes\n"
    tonneau = {c.field: c.value for c in manual.parse_csv(csv_text)[0].attributes}["tonneau"]
    assert tonneau == "yes"


def test_json_import():
    data = json.dumps({"listings": [{"url": "https://www.carvana.com/vehicle/3456789", "price": "$57,500",
                                     "mileage": "20,100", "description": "Quad-Motor, Max Pack"}]})
    it = manual.parse_json(data)[0]
    assert it.source_key == "carvana" and it.source_listing_id == "3456789"
    assert it.price == 57500 and it.miles == 20100


@pytest.mark.parametrize("name,make,model", [
    ("Ford F-150 Lightning Lariat", "Ford", "F-150 Lightning"),
    ("Chevrolet Silverado EV RST", "Chevrolet", "Silverado EV"),
    ("GMC Sierra EV Denali", "GMC", "Sierra EV"),
])
def test_new_electric_pickups_import_through_each_path(name, make, model):
    text = f"2024 {name}. $54,000. 21,000 miles. Range: 320 miles; towing capacity: 10,000 lbs."
    draft = capture.draft_from_text(text, "https://dealer.example/truck")
    captured = capture.listing_from_draft(draft)
    imported = manual.listing_from_fields({"description": text})
    email = email_alerts.parse_pasted(text + " https://cars.ksl.com/listing/1234567")[0]
    for item in (captured, imported, email):
        assert (item.make, item.model) == (make, model)
        assert (item.price, item.miles) == (54000, 21000)
        fields = {a.field: a.value for a in item.attributes}
        assert (fields["epa_range"], fields["tow_capacity_lbs"]) == ("320", "10000")
    assert email_alerts.looks_like_truck(email)


def test_capture_does_not_assume_unrecognized_vehicle_is_rivian():
    draft = capture.draft_from_text("2024 Ford F-150 gasoline 3.5L EcoBoost. $45,000. 15,000 miles")
    assert not draft["make"] and not draft["model"]
    assert not email_alerts.looks_like_truck(capture.listing_from_draft(draft))


def test_explicit_imported_ratings_are_normalized_and_invalid_units_are_ignored():
    imported = manual.listing_from_fields({"make": "Ford", "model": "F-150 Lightning", "epa_range": "320 miles",
                                           "tow_capacity_lbs": "10,000 lbs", "battery": "Extended Range"})
    assert {a.field: a.value for a in imported.attributes} == {
        "battery": "Extended Range", "epa_range": "320", "tow_capacity_lbs": "10000"}
    imported = manual.listing_from_fields({"epa_range": "460 km", "tow_capacity_lbs": "4500 kg"})
    assert not imported.attributes
