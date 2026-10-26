"""Personal requirements and preferences, kept separate from market price ratings."""
from __future__ import annotations

import math

FEATURES = {
    "heated_seats": "Heated seats",
    "ventilated_seats": "Ventilated seats",
    "heated_steering_wheel": "Heated steering wheel",
    "surround_camera": "Surround-view camera",
    "adaptive_cruise": "Adaptive cruise control",
    "hands_free_driving": "Hands-free driving",
    "tow_package": "Tow package",
    "trailer_brake_controller": "Trailer brake controller",
    "air_suspension": "Air suspension",
    "rear_steering": "Rear steering",
    "midgate": "Midgate",
    "tonneau": "Powered tonneau",
}
MATCH_STATUSES = ("Meets requirements", "Needs verification", "Does not qualify")


def _text(value) -> str:
    value = "" if value is None else str(value).strip()
    return "" if value.casefold() in ("", "unknown", "none", "nan", "<na>", "nat") else value


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


def _yes_no(value) -> bool | None:
    value = _text(value).casefold()
    return True if value in ("yes", "true", "1") else False if value in ("no", "false", "0") else None


def _features(profile: dict, key: str) -> list[str]:
    values = profile.get(key) or []
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value in FEATURES)) if isinstance(values, list) else []


def _claim(row, resolved: dict | None, field: str) -> dict:
    claim = (resolved or {}).get(field)
    get = claim.get if isinstance(claim, dict) else lambda key, default=None: getattr(claim, key, default)
    fallback = row.get(field)
    if field == "epa_range" and field not in row:
        fallback = row.get("range_mi")
    value = _text(get("value")) or _text(fallback)
    if field in ("epa_range", "tow_capacity_lbs") and not _number(value):
        value = ""
    flag = {"epa_range": "epa_range_verified", "tow_capacity_lbs": "tow_verified"}.get(field, field + "_verified")
    verified = get("confidence") == "verified" or (claim is None and _yes_no(row.get(flag)) is True)
    conflict = bool(get("conflict", False)) and not verified
    status = "Unknown" if not value else "Verified" if verified else "Conflicting" if conflict else "Advertised"
    evidence = " · ".join(dict.fromkeys(part for part in
                         (value, _text(get("source")), _text(get("method")), _text(get("evidence"))) if part))
    return {"value": value, "verified": verified and bool(value), "status": status, "evidence": evidence}


def evaluate(row, settings: dict, resolved: dict | None = None) -> dict:
    """Check saved advertised limits, require proof for must-haves, and score common preferences equally."""
    profile, filters = settings.get("shopping_profile") or {}, settings.get("filters") or {}
    reasons, missing, failures, preferred, scores = [], [], [], [], []
    needs_proof = False
    price = _number(row.get("your_price")) if filters.get("count_discounts", True) else None
    if price is None:
        price = _number(row.get("price"))
    if price == 0:
        price = None
    basics = (("Price", price, "max_price", "$"),
              ("Mileage", _number(row.get("miles")), "max_miles", "mi"),
              ("Distance", _number(row.get("distance_mi")), "max_distance", "mi"))
    for label, value, key, unit in basics:
        limit = _number(filters.get(key)) or 0
        if not limit:
            continue
        bound = f"${limit:,.0f}" if unit == "$" else f"{limit:,.0f} {unit}"
        if value is None:
            missing.append(f"{label} unknown; confirm it is within {bound}")
            needs_proof = True
            scores.append(0)
        elif value > limit:
            actual = f"${value:,.0f}" if unit == "$" else f"{value:,.0f} {unit}"
            failures.append(f"{label} {actual} exceeds your {bound} limit")
            scores.append(0)
        else:
            reasons.append(f"{label} within your {bound} limit")
            scores.append(1 - value / limit)
    for name, field, label, unit, default_priority in (
        ("range", "epa_range", "Range", "mi", "prefer"),
        ("tow", "tow_capacity_lbs", "Tow capacity", "lb", "must"),
    ):
        limit = _number(profile.get(name + "_min")) or 0
        priority = profile.get(name + "_priority", default_priority)
        if not limit or priority not in ("prefer", "must"):
            continue
        claim = _claim(row, resolved, field)
        value = _number(claim["value"])
        value = value if value and value > 0 else None
        detail = f"{claim['status'].lower()} {value:,.0f} {unit}" if value is not None else "unknown"
        description = f"{label}: {detail}; target at least {limit:,.0f} {unit}"
        if priority == "must":
            if not claim["verified"] or value is None:
                missing.append(description + " — verify")
                needs_proof = True
            elif value < limit:
                failures.append(description)
            else:
                reasons.append(description)
        else:
            preferred.append(description)
            scores.append(float(value is not None and value >= limit and claim["status"] != "Conflicting"))
            if not claim["verified"] or value is None:
                missing.append(description + " — verify preferred specification")
    must = _features(profile, "must_have")
    for field in dict.fromkeys(must + _features(profile, "prefer")):
        claim = _claim(row, resolved, field)
        value = _yes_no(claim["value"])
        detail = f"{claim['status'].lower()} {'yes' if value else 'no'}" if value is not None else "unknown"
        description = f"{FEATURES[field]}: {detail}"
        if field in must:
            if not claim["verified"] or value is None:
                missing.append(description + " — verify required equipment")
                needs_proof = True
            elif value:
                reasons.append(description)
            else:
                failures.append(description)
        else:
            preferred.append(description)
            scores.append(float(value is True and claim["status"] != "Conflicting"))
            if not claim["verified"] or value is None:
                missing.append(description + " — verify preferred equipment")
    score = round(100 * sum(scores) / len(scores)) if scores else 0
    reasons.insert(0, "Score uses equally weighted budget, mileage and distance margins plus selected preferred "
                      "matches. Advertised preferences can earn credit; proof status is separate.")
    reasons.insert(1, "Status checks saved price, mileage and distance limits and selected must-haves; "
                      "condition and title need separate review.")
    return {
        "match_status": MATCH_STATUSES[2] if failures else MATCH_STATUSES[1] if needs_proof else MATCH_STATUSES[0],
        "match_score": max(0, min(100, score)), "match_reasons": reasons, "match_missing": missing,
        "match_failures": failures, "match_preferred": preferred,
    }


def proof_items(row, settings: dict, resolved: dict | None = None) -> list[dict]:
    """Evidence to check on a shortlist; inferred manufacturer specifications do not count as proof."""
    profile = settings.get("shopping_profile") or {}
    fields = {"battery": "Battery configuration", "epa_range": "Range", "tow_capacity_lbs": "Tow capacity",
              "warranty_expiration": "Warranty expiration", "title_status": "Title history"}
    fields.update({field: FEATURES[field] for field in
                   dict.fromkeys(_features(profile, "must_have") + _features(profile, "prefer"))})
    return [{"field": field, "label": label, **{key: claim[key] for key in ("status", "evidence")}}
            for field, label in fields.items() for claim in [_claim(row, resolved, field)]]
