"""Your adjusted price: what a truck effectively costs you once shipping and the features you care about count.

adjusted = your price (after seller discounts) + shipping − what each matching feature is worth to you

A rule like "color contains white → $1,000" means a white truck is worth $1,000 more to you, so its adjusted price
is $1,000 lower. Negative amounts work too (e.g. welded front subframe → −$2,000 makes it look more expensive).

Unconfirmed data never costs a truck money: a rule never matches an "unsure"/"unknown" value (a front subframe
that could be either), and when the range is only an estimate (wheels unknown, battery disputed) only the best case
counts. to_confirm() lists what to check so the full adjustment can apply.

Warranty value: each month of comprehensive warranty beyond (or short of) a baseline date is worth a set amount.
"Months" are effective months — the date or the mileage cap, whichever runs out first at your driving pace. Unknown
warranties are estimated from the model year (in service mid-year + Rivian's terms) and marked "est.".
"""
from __future__ import annotations

import math
from datetime import date

from . import epa, warranty

FIELDS = {"color": "Exterior color", "tonneau": "Powered tonneau", "battery": "Battery", "motor": "Motor",
          "wheels": "Wheels", "subframe": "Front subframe", "generation": "Generation", "year": "Model year"}
CONTAINS = {"color", "wheels"}           # "white" matches "Glacier White"; other fields must match exactly
UNCONFIRMED = {"unsure", "unknown"}      # never priced — tagged "confirm" instead


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or v == ""


def matches(rule: dict, row: dict) -> bool:
    field, want = rule.get("field"), str(rule.get("match") or "").strip().lower()
    if field not in FIELDS or not want:
        return False
    if field == "battery" and row.get("battery_uncertain"):
        return False                         # don't credit a pack the sources disagree on
    value = row.get(field)
    if _blank(value):
        return False
    value = str(int(value) if field == "year" and isinstance(value, float) else value).strip().lower()
    if value in UNCONFIRMED:
        return False
    return want in value if field in CONTAINS else value == want


def label(rule: dict) -> str:
    field, m = rule.get("field"), str(rule.get("match") or "").strip()
    if field == "tonneau":
        return "powered tonneau" if m.lower() == "yes" else f"tonneau {m}"
    if field in ("battery", "motor"):
        return f"{m} {field}"
    if field == "subframe":
        return f"{m} subframe"
    return m.lower() if field == "color" else f"{FIELDS.get(field, field).lower()} {m}"


def warranty_months(row: dict, annual_miles: float, terms: dict | None = None,
                    today: date | None = None) -> tuple[float | None, bool]:
    """(effective months of comprehensive warranty left, estimated?) — None when even the year is unknown."""
    today = today or date.today()
    end, limit, est = warranty._date(row.get("warranty_expires") or None), row.get("warranty_miles_limit"), False
    if end is None:
        if (row.get("make", "Rivian").lower() != "rivian"
                or row.get("model", "R1T").upper() != "R1T"):
            return None, False
        year = row.get("year")
        if _blank(year):
            return None, False
        t = warranty.terms_for(row.get("motor"), row.get("battery"), terms)
        end, limit, est = date(int(year) + t["comp_years"], 7, 1), t["comp_miles"], True
    months = max(warranty._months_between(today, end), 0) if end > today else 0
    miles = row.get("miles")
    if not _blank(limit) and not _blank(miles) and annual_miles:
        months = min(months, max(float(limit) - float(miles), 0) / (float(annual_miles) / 12))
    return float(months), est


def effective_range(row: dict) -> tuple[float | None, str]:
    """(range in miles, how we know): your number → exact EPA rating → listed range → middle of the EPA span."""
    listed, low, high = row.get("epa_range"), row.get("epa_est_low"), row.get("epa_est_high")
    if row.get("epa_range_verified") and not _blank(listed):
        return float(listed), "your range"
    if not _blank(low) and not _blank(high) and low == high:
        return float(low), "EPA"
    span = not _blank(low) and not _blank(high)
    if row.get("battery_uncertain") and span:      # sources disagree on the pack: don't bet the penalty on either
        return (float(low) + float(high)) / 2, "est."
    # a listed range outside every EPA rating for this year/motor/battery is a listing mistake — don't trust it
    if not _blank(listed) and (not span or float(low) - 10 <= float(listed) <= float(high) + 10):
        return float(listed), "listed"
    if span:
        return (float(low) + float(high)) / 2, "est."
    if not _blank(listed):
        return float(listed), "listed"
    return None, ""


def range_penalty(rng: float, cfg: dict) -> float:
    ok_at, floor = float(cfg.get("ok_at", 320)), float(cfg.get("floor", 300))
    return (max(ok_at - rng, 0) * float(cfg.get("per_mile", 40))
            + max(floor - rng, 0) * float(cfg.get("per_mile_below_floor", 60)))


def penalty_range(row: dict) -> tuple[float | None, str]:
    """The range the penalty uses: the effective range, but only the best case when it's an estimate."""
    rng, how = effective_range(row)
    if how == "est." and not _blank(row.get("epa_est_high")):
        return float(row["epa_est_high"]), "best case"
    return rng, how


def to_confirm(row: dict, cfg: dict | None = None) -> list[str]:
    """What isn't confirmed yet, so isn't priced: 'frame', 'battery', 'wheels' (only when it could change the range
    penalty). Confirm these in the truck's Quick verify."""
    out = []
    if (row.get("make", "Rivian").lower() == "rivian" and row.get("model", "R1T").upper() == "R1T"
            and row.get("subframe") in UNCONFIRMED):
        out.append("frame")
    if row.get("battery_uncertain"):
        out.append("battery")
    rv = (cfg or {}).get("range_value") or {}
    low = row.get("epa_est_low")
    if (rv.get("enabled") and effective_range(row)[1] == "est." and epa._wheel_size(row.get("wheels")) is None
            and not _blank(low) and range_penalty(float(low), rv) > range_penalty(penalty_range(row)[0], rv)):
        out.append("wheels")
    return out


def baseline_months(baseline: str | None, today: date | None = None) -> float | None:
    end = warranty._date(baseline) if baseline else None
    if end is None:
        return None
    today = today or date.today()
    return float(warranty._months_between(today, end)) if end > today else 0.0


def adjusted(row: dict, cfg: dict | None, warranty_terms: dict | None = None,
             today: date | None = None) -> tuple[float | None, str]:
    """(adjusted price, breakdown like '+$990 shipping · −$1,000 white'); (None, '') without a price."""
    cfg = cfg or {}
    base = row.get("your_price")
    if _blank(base):
        base = row.get("price")
    if _blank(base):
        return None, ""
    parts: list[tuple[str, float]] = []
    ship = row.get("transport_cost")
    if cfg.get("include_shipping", True) and not _blank(ship) and float(ship) > 0:
        parts.append(("fly & drive" if str(row.get("transport_basis") or "").startswith("Fly & drive") else "shipping",
                      float(ship)))
    for rule in cfg.get("rules") or []:
        try:
            amount = float(rule.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if amount and matches(rule, row):
            parts.append((label(rule), -amount))
    rv = cfg.get("range_value") or {}
    if rv.get("enabled"):
        rng, how = penalty_range(row)
        if rng is not None:
            penalty = round(range_penalty(rng, rv))
            if penalty:
                parts.append((f"range ({rng:.0f} mi {how})", float(penalty)))
    wv = cfg.get("warranty_value") or {}
    if wv.get("enabled") and wv.get("per_month"):
        months, est = warranty_months(row, wv.get("annual_miles", 12000), warranty_terms, today)
        base_m = baseline_months(wv.get("baseline"), today)
        if months is not None and base_m is not None:
            diff = months - base_m
            value = round(diff * float(wv["per_month"]))
            if value:
                end_txt = warranty._date(wv["baseline"]).strftime("%b %Y")
                parts.append((f"warranty ({'+' if diff > 0 else '−'}{abs(diff):.0f} mo vs {end_txt}"
                              f"{', est.' if est else ''})", -value))
    total = float(base) + sum(a for _, a in parts)
    note = " · ".join(f"{'+' if a > 0 else '−'}${abs(a):,.0f} {name}" for name, a in parts)
    return round(total), note
