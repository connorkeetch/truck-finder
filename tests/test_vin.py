import pytest

from rivian_finder.vin import (check_digit, clean_vin, find_vins, is_rivian_r1t, is_valid_vin, model_year,
                               validate_vin, with_check_digit)

KNOWN_VALID = "1HGCM82633A004352"   # widely used Honda example VIN with a correct check digit


def test_known_vin_is_valid():
    assert is_valid_vin(KNOWN_VALID)
    assert check_digit(KNOWN_VALID) == "3"


def test_clean_vin_strips_spaces_dashes_and_case():
    assert clean_vin(" 1hg-cm826 33a004352 ") == KNOWN_VALID


@pytest.mark.parametrize("raw,reason", [
    ("1HGCM82633A00435", "17 characters"),
    ("1HGCM82633A0043O2", "ambiguous"),
    ("1HGCM82643A004352", "check digit"),
])
def test_invalid_vins_explain_why(raw, reason):
    ok, why = validate_vin(raw)
    assert not ok
    assert reason in why


def test_with_check_digit_round_trip():
    v = with_check_digit("7FCTGAAL0PN900001")
    assert is_valid_vin(v)
    assert v[8] == check_digit(v)


@pytest.mark.parametrize("code,year", [("N", 2022), ("P", 2023), ("R", 2024), ("S", 2025), ("T", 2026)])
def test_model_year_from_position_10(code, year):
    assert model_year(with_check_digit(f"7FCTGAAL0{code}N900001")) == year


def test_rivian_r1t_prefix():
    assert is_rivian_r1t("7FCTGAAL0PN900001")
    assert not is_rivian_r1t(KNOWN_VALID)


def test_find_vins_only_returns_checksum_valid():
    good = with_check_digit("7FCTGBAL0RN900123")
    bad = good[:8] + ("1" if good[8] != "1" else "2") + good[9:]
    text = f"VIN: {good}. Typo version {bad}. Again {good}."
    assert find_vins(text) == [good]
