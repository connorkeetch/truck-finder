import pytest

from rivian_finder.extract import (canonical_url, classify_tonneau, extract_attributes, identify_site, parse_location,
                                   parse_miles, parse_price, parse_truck_identity, parse_year, structured_truck_specs)


def claims(text):
    return {c.field: c.value for c in extract_attributes(text, "test")}


@pytest.mark.parametrize("text,expected", [
    ("Price: $58,990", 58990),
    ("$61500 OBO", 61500),
    ("Est. $899/mo  then $54,000 cash", 54000),
    ("Only $59.9k!", 59900),
    ("no price here", None),
    ("$1,200 deposit", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("18,412 miles", 18412),
    ("Mileage: 22,100", 22100),
    ("12k miles, one owner", 12000),
    ("Odometer 9,870", 9870),
    ("314 miles of range, 21,500 mi on the clock", 21500),
    ("EPA est. 352 mi range", None),
    ("21,000 miles. Range: 320 miles", 21000),
    ("EPA-estimated range of 320 miles", None),
    ("450 miles of electric range", None),
])
def test_parse_miles(text, expected):
    assert parse_miles(text) == expected


def test_parse_year():
    assert parse_year("Clean 2024 Rivian R1T Adventure") == 2024


def test_full_listing_text():
    c = claims('2023 Rivian R1T Adventure Dual-Motor AWD Large Pack, powered tonneau cover, Launch Green, '
               'clean title, no accidents. EPA est. 352 mi range. 20" All-Terrain wheels. In-service date: 03/15/2023')
    assert c["battery"] == "Large"
    assert c["motor"] == "Dual"
    assert c["tonneau"] == "yes"
    assert c["epa_range"] == "352"
    assert c["wheels"].startswith('20"')
    assert c["exterior_color"] == "Launch Green"
    assert c["title_status"] == "clean"
    assert c["accident_history"] == "none_reported"
    assert c["in_service_date"] == "2023-03-15"


@pytest.mark.parametrize("text,motor", [
    ("Quad-Motor AWD", "Quad"),
    ("Performance Dual-Motor", "Performance Dual"),
    ("Dual Motor Performance upgrade", "Performance Dual"),
    ("Tri-Motor", "Tri"),
    ("Dual-Motor AWD", "Dual"),
])
def test_motor_variants(text, motor):
    assert claims(text)["motor"] == motor


def test_dual_zone_climate_is_not_a_motor():
    assert "motor" not in claims("Heated seats, dual-zone climate control")


@pytest.mark.parametrize("text,battery", [("Max Pack", "Max"), ("Large battery pack", "Large"),
                                          ("Standard+ pack", "Standard+"), ("Standard Pack", "Standard")])
def test_battery_variants(text, battery):
    assert claims(text)["battery"] == battery


@pytest.mark.parametrize("text,status", [
    ("Powered tonneau cover", "yes"),
    ("Electric tonneau", "yes"),
    ("No tonneau cover", "no"),
    ("does not have the powered tonneau", "no"),
    ("Power tonneau not working", "yes"),
    ("Nothing about the bed", "unknown"),
])
def test_tonneau_classification(text, status):
    assert classify_tonneau(text)[0] == status


def test_plain_tonneau_mention_is_not_assumed_powered():
    c = claims("Tonneau cover included")
    assert "tonneau" not in c
    assert c["tonneau_mention"] == "mentioned (type unclear)"


def test_trim_or_year_alone_never_implies_tonneau():
    assert "tonneau" not in claims("2023 Rivian R1T Launch Edition")


def test_reported_accident():
    assert claims("CARFAX: 1 accident reported")["accident_history"] == "reported"


def test_location():
    assert parse_location("Located in Draper, UT 84020") == ("Draper", "UT", "84020")


def test_canonical_url_drops_tracking_and_www():
    a = canonical_url("https://www.cars.com/vehicledetail/abc-123/?utm_source=email&utm_medium=x")
    b = canonical_url("https://cars.com/vehicledetail/abc-123")
    assert a == b


@pytest.mark.parametrize("url,site,lid", [
    ("https://www.autotrader.com/cars-for-sale/vehicle/712345678?zip=84020", "autotrader", "712345678"),
    ("https://www.carvana.com/vehicle/3456789", "carvana", "3456789"),
    ("https://www.carmax.com/car/27612345", "carmax", "27612345"),
    ("https://cars.ksl.com/listing/9876543", "ksl", "9876543"),
    ("https://www.facebook.com/marketplace/item/1234567890/", "facebook", "1234567890"),
    ("https://www.cars.com/vehicledetail/0f7c2f6a-1234-4cde-9abc-1234567890ab/", "cars_com",
     "0f7c2f6a-1234-4cde-9abc-1234567890ab"),
    ("https://some-dealer.example/used/2024-rivian-r1t", "dealer", None),
])
def test_identify_site(url, site, lid):
    assert identify_site(url) == (site, lid)


@pytest.mark.parametrize("text,expected", [
    ("2023 Rivian R1T Adventure", ("Rivian", "R1T")),
    ("2024 Ford F-150 Lightning Lariat", ("Ford", "F-150 Lightning")),
    ("2025 F150 Lightning XLT", ("Ford", "F-150 Lightning")),
    ("2024 Chevy Silverado EV RST", ("Chevrolet", "Silverado EV")),
    ("2025 GMC Sierra EV Denali", ("GMC", "Sierra EV")),
    ("2024 Ford F-150 3.5L EcoBoost", (None, None)),
    ("2024 Chevrolet Silverado 1500 LT diesel", (None, None)),
    ("2025 GMC Sierra 1500 Denali Duramax", (None, None)),
    ("2025 GMC Hummer EV SUV", (None, None)),
    ("2024 Rivian R1S", (None, None)),
])
def test_supported_electric_pickup_identity(text, expected):
    assert parse_truck_identity(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Ford F-150 Lightning Extended Range, EPA-estimated range of 320 miles; tow capacity: 10,000 lbs.",
     {"battery": "Extended Range", "epa_range": "320", "tow_capacity_lbs": "10000"}),
    ("Silverado EV, 450 miles of electric range, 10,000 lbs towing capacity and 1,500 lbs payload.",
     {"epa_range": "450", "tow_capacity_lbs": "10000"}),
    ("Sierra EV Max Range battery pack, GM-estimated 460 miles; max trailering: 10,500 pounds",
     {"battery": "Max Range", "epa_range": "460", "tow_capacity_lbs": "10500"}),
    ("F-150 Lightning towing up to 10k lbs; range: 320 mi; mileage: 21,000",
     {"epa_range": "320", "tow_capacity_lbs": "10000"}),
    ("F-150 Lightning has an electric range of 320 miles; maximum towing capacity of up to 7,700 pounds",
     {"epa_range": "320", "tow_capacity_lbs": "7700"}),
])
def test_electric_pickup_advertised_specs(text, expected):
    actual = claims(text)
    assert {key: actual[key] for key in expected} == expected
    assert "tonneau" not in actual


@pytest.mark.parametrize("text", [
    "Not rated for 10,000 lbs towing capacity.",
    "Cannot tow 10,000 pounds.",
    "Towing capacity 10,000 lbs with the optional Max Trailer Tow Package.",
    "Tows 10,000 lbs when properly equipped.",
    "Max Trailer Tow package available; 2,000 lbs payload.",
    "No EPA range: 320 miles.",
    "Adds 150 miles of range in 10 minutes.",
    "150 miles of range while towing.",
    "EPA range: 320-460 miles.",
])
def test_uncertain_or_unrelated_numbers_are_not_ratings(text):
    assert not (claims(text).keys() & {"epa_range", "tow_capacity_lbs"})


def test_rivian_pack_names_and_colors_do_not_leak_to_other_brands():
    c = extract_attributes("Large battery pack. Midnight. Max pack.", "test", make="Ford", model="F-150 Lightning")
    assert not ({a.field for a in c} & {"battery", "exterior_color"})


def test_advertised_ratings_preserve_source_evidence():
    text = "EPA range: 320 miles; towing capacity 7,700 lbs"
    c = extract_attributes(text, "dealer text", make="Ford", model="F-150 Lightning")
    assert {a.field for a in c} == {"epa_range", "tow_capacity_lbs"}
    assert all(a.method == "dealer text" and a.confidence == "low" and a.evidence for a in c)


def test_structured_specs_require_units_or_unit_specific_field_names():
    c = structured_truck_specs({"epaRange": 320, "max_towing_capacity_lbs": "10,000 lbs",
                                "payload_lbs": 2200, "range": 640, "towingCapacity": 15000}, "API specs")
    assert {a.field: a.value for a in c} == {"epa_range": "320", "tow_capacity_lbs": "10000"}
    assert all(a.method == "API specs" and a.evidence and a.confidence == "medium" for a in c)
    for value in ("460 km", "320-460 miles", True, -320, 32000):
        assert not structured_truck_specs({"epa_range": value}, "API specs")
    for value in ("4,500 kg", "7,700-10,000 lbs", True, -10000, 150000):
        assert not structured_truck_specs({"tow_capacity_lbs": value}, "API specs")
