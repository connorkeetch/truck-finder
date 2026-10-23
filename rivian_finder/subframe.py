"""Front subframe: welded (early R1T) or cast (later), estimated from the VIN.

Rivian built early R1Ts with a multi-piece welded front subframe that could crack at the welds, and switched to a
single-piece cast subframe in early 2023. There is no official VIN cutoff. For the R1T the last six VIN digits
are a build-order serial, and owner reports put the switch around serial 19,000: a truck with serial 0189xx
(delivered late March 2023) was welded, while a 019xxx truck built in February 2023 was cast. So:

* 2022 model year: welded · 2024 and later: cast
* 2023: serial below 18,000 welded, above 20,500 cast, in between unsure.

Rivian replaced many welded subframes with the cast one under warranty, so a 'welded' truck may have been fixed.
Ask the seller or check the service history, then record what you learn (Quick verify) — that always wins.
"""
from __future__ import annotations

LABELS = {"cast": "Cast", "welded": "Welded", "unsure": "Unsure", "unknown": "Unknown"}
WELDED_BELOW = 18000          # 2023 R1T serials below this: welded
CAST_ABOVE = 20500            # 2023 R1T serials above this: cast
YEAR_CODES = {"N": 2022, "P": 2023, "R": 2024, "S": 2025, "T": 2026, "V": 2027}


def estimate(vin: str | None) -> tuple[str, str]:
    """(status, why) — status is 'cast', 'welded', 'unsure' or 'unknown'."""
    v = (vin or "").strip().upper()
    if len(v) != 17 or not v[11:].isdigit():
        return "unknown", "no VIN"
    if not v.startswith("7FCT"):
        return "unknown", "not an R1T VIN"
    year, serial = YEAR_CODES.get(v[9]), int(v[11:])
    if year is None:
        return "unknown", "unrecognised model year in VIN"
    if year <= 2022:
        return "welded", "2022 model year — built with the welded subframe (may have been replaced with cast)"
    if year >= 2024:
        return "cast", f"{year} model year — built after the switch to the cast subframe"
    if serial < WELDED_BELOW:
        return "welded", f"2023 built before the switch (serial {serial:,}) — may have been replaced with cast"
    if serial > CAST_ABOVE:
        return "cast", f"2023 built after the switch (serial {serial:,})"
    return "unsure", f"2023 built around the switch (serial {serial:,}, early 2023) — ask the seller"
