"""Remaining factory warranty — from the truck's actual warranty dates when known, else in-service date + rules.

Never guessed: with neither warranty dates nor an in-service date, the result is 'unknown'.
Rules (editable in Settings → Warranty): comprehensive coverage is 4 yr / 50k by default and longer for the
motors listed (Quad: 5 yr / 60k); battery & drivetrain 8 yr with a mileage cap by pack.
"""
from __future__ import annotations

from datetime import date

DEFAULT_TERMS = {
    "comprehensive_years": 4,
    "comprehensive_miles": 50000,
    "longer_motors": ["Quad"],
    "longer_years": 5,
    "longer_miles": 60000,
    "battery_years": 8,
    "battery_miles_large_max": 175000,
    "battery_miles_standard": 150000,
}


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + years, day=28)


def _date(iso: str | None) -> date | None:
    if not iso:
        return None
    try:
        return date.fromisoformat(str(iso)[:10]) if len(str(iso)) >= 10 else date.fromisoformat(str(iso)[:7] + "-01")
    except ValueError:
        return None


def terms_for(motor: str | None, battery: str | None, cfg: dict | None = None) -> dict:
    t = {**DEFAULT_TERMS, **(cfg or {})}
    longer = motor in (t.get("longer_motors") or [])
    comp_years = int(t["longer_years"] if longer else t["comprehensive_years"])
    comp_miles = int(t["longer_miles"] if longer else t["comprehensive_miles"])
    # Rivian's own pages: Quad (and Max pack) trucks get 175k battery miles; Dual trucks 150k even with the Large pack
    batt_miles = int(t["battery_miles_large_max"] if longer or battery == "Max" else t["battery_miles_standard"])
    label = f"{comp_years} yr / {comp_miles // 1000}k" + (f" ({motor})" if longer else "")
    return {"comp_years": comp_years, "comp_miles": comp_miles, "battery_years": int(t["battery_years"]),
            "battery_miles": batt_miles, "label": label}


def _months_between(today: date, end: date) -> int:
    return (end.year - today.year) * 12 + (end.month - today.month) - (1 if end.day < today.day else 0)


def remaining(in_service: str | None, miles: int | None, cfg: dict | None = None, battery: str | None = None,
              today: date | None = None, motor: str | None = None, comp_exp: str | None = None,
              comp_miles: int | None = None, batt_exp: str | None = None, batt_miles: int | None = None,
              use_rules: bool = True) -> dict:
    """Remaining comprehensive and battery/drivetrain coverage; ends at the date or mileage, whichever is first."""
    today = today or date.today()
    out = {"known": False, "comprehensive_expires": None, "comprehensive_miles_limit": None,
           "comprehensive_months_left": None,
           "comprehensive_miles_left": None, "battery_expires": None, "battery_miles_left": None,
           "basis": "", "summary": "Unknown (enter the in-service date or warranty dates)"}
    rule = terms_for(motor, battery, cfg)
    start = _date(in_service) if use_rules else None
    comp_end = _date(comp_exp) or (_add_years(start, rule["comp_years"]) if start else None)
    if comp_end is None:
        return out
    comp_limit = int(comp_miles) if comp_miles else (rule["comp_miles"] if use_rules else None)
    batt_end = _date(batt_exp) or (_add_years(start, rule["battery_years"]) if start else None)
    batt_limit = int(batt_miles) if batt_miles else (rule["battery_miles"] if use_rules else None)
    comp_miles_left = None if miles is None or comp_limit is None else max(comp_limit - int(miles), 0)
    batt_miles_left = None if miles is None or batt_limit is None else max(batt_limit - int(miles), 0)
    months_left = max(_months_between(today, comp_end), 0)
    expired = comp_end <= today or comp_miles_left == 0
    out.update(known=True, comprehensive_expires=comp_end.isoformat(), comprehensive_miles_limit=comp_limit,
               comprehensive_months_left=0 if expired else months_left,
               comprehensive_miles_left=0 if expired else comp_miles_left,
               battery_expires=batt_end.isoformat() if batt_end else None, battery_miles_left=batt_miles_left,
               basis=("the truck's warranty dates" if comp_exp else f"in-service {start:%b %Y} + {rule['label']}"))
    if expired:
        out["summary"] = "Comprehensive expired"
    else:
        miles_txt = f", {comp_miles_left:,} mi" if comp_miles_left is not None else ""
        out["summary"] = f"{months_left} mo{miles_txt} (to {comp_end:%b %Y})"
    return out


def ends_text(expires: str | None, miles_limit) -> str:
    """'Apr 2028 · 50k mi' — when comprehensive coverage ends (date or mileage, whichever first); '' if unknown."""
    end = _date(expires)
    if end is None:
        return ""
    try:
        cap = f" · {int(miles_limit) // 1000}k mi" if miles_limit and miles_limit == miles_limit else ""
    except (TypeError, ValueError):
        cap = ""
    return f"{end:%b %Y}{cap}"
