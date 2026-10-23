"""VIN cleaning, validation (ISO 3779 / North American check digit), and deterministic decoding."""
from __future__ import annotations

import re

_TRANSLIT = {
    **{str(d): d for d in range(10)},
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}
_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
_YEAR_CODES = "ABCDEFGHJKLMNPRSTVWXY123456789"  # 30-year cycle starting 1980 (A) / 2010 (A)

VIN_CANDIDATE_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
RIVIAN_R1T_PREFIX = "7FCT"   # WMI 7FC (Rivian trucks) + model letter T, confirmed against NHTSA vPIC


def clean_vin(raw: str | None) -> str:
    """Uppercase and strip spaces/dashes. Does not 'fix' ambiguous characters."""
    if not raw:
        return ""
    return re.sub(r"[\s\-]", "", str(raw)).upper()


def check_digit(vin: str) -> str:
    total = 0
    for i, ch in enumerate(vin):
        if ch not in _TRANSLIT:
            raise ValueError(f"invalid VIN character {ch!r}")
        total += _TRANSLIT[ch] * _WEIGHTS[i]
    rem = total % 11
    return "X" if rem == 10 else str(rem)


def validate_vin(raw: str | None) -> tuple[bool, str]:
    """Return (is_valid, reason). Valid means 17 legal chars and a correct check digit."""
    vin = clean_vin(raw)
    if len(vin) != 17:
        return False, f"VIN must be 17 characters (got {len(vin)})"
    bad = sorted({c for c in vin if c in "IOQ"})
    if bad:
        return False, f"VIN contains ambiguous character(s) {', '.join(bad)}"
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
        return False, "VIN contains invalid characters"
    expected = check_digit(vin)
    if vin[8] != expected:
        return False, f"check digit mismatch (position 9 is {vin[8]}, expected {expected})"
    return True, "ok"


def is_valid_vin(raw: str | None) -> bool:
    return validate_vin(raw)[0]


def model_year(vin: str) -> int | None:
    """Decode model year from position 10. Uses position 7 to pick the 30-year cycle (light vehicles)."""
    vin = clean_vin(vin)
    if len(vin) != 17 or vin[9] not in _YEAR_CODES:
        return None
    idx = _YEAR_CODES.index(vin[9])
    base = 2010 if vin[6].isalpha() else 1980
    return base + idx


def is_rivian_r1t(vin: str) -> bool:
    return clean_vin(vin).startswith(RIVIAN_R1T_PREFIX)


def find_vins(text: str | None) -> list[str]:
    """All checksum-valid VINs appearing in free text, in order, de-duplicated."""
    if not text:
        return []
    seen: list[str] = []
    for m in VIN_CANDIDATE_RE.finditer(text.upper()):
        v = m.group(0)
        if v not in seen and is_valid_vin(v):
            seen.append(v)
    return seen


def with_check_digit(vin16_or_17: str) -> str:
    """Return the VIN with position 9 set to its correct check digit (used to build test fixtures)."""
    v = clean_vin(vin16_or_17)
    if len(v) != 17:
        raise ValueError("need 17 characters (position 9 may be any placeholder)")
    v = v[:8] + "0" + v[9:]
    return v[:8] + check_digit(v) + v[9:]
