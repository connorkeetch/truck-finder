"""Side-by-side comparison table: one column per truck, best value per row highlighted."""
from __future__ import annotations

import pandas as pd

from .config import ACCIDENT_STATUSES, TITLE_STATUSES, TONNEAU_STATUSES

BATTERY_RANK = {"Max": 4, "Large": 3, "Standard+": 2, "Standard": 1}
TONNEAU_RANK = {"yes": 2, "unknown": 1, "no": 0}
TITLE_RANK = {"clean": 2, "unknown": 1, "branded": 0}
ACCIDENT_RANK = {"none_reported": 2, "unknown": 1, "reported": 0}

# (label, column, format, best): best is "low", "high", a rank dict, ("col", "low"/"high") to rank by another
# column, or None for no highlight.
ROWS: list[tuple] = [
    ("My requirements", "match_status", "text", None),
    ("Personal score", "match_score", "int", None),
    ("Requirements not met", "match_failures", "items", None),
    ("Needs proof", "match_missing", "items", None),
    ("Preferences", "match_preferred", "items", None),
    ("Legacy fit score", "fit_score", "int", None),
    ("Price", "price", "money", "low"),
    ("Market estimate", "market_price", "money", None),
    ("vs. market", "deal_delta", "money", "low"),
    ("Deal rating", "deal_label", "text", {"Great deal": 5, "Good deal": 4, "Fair price": 3, "Above market": 2,
                                           "Overpriced": 1}),
    ("Change since first seen", "price_change", "money", "low"),
    ("Days listed", "days_listed", "int", "high"),
    ("Price drops", "price_drops", "int", "high"),
    ("Negotiation leverage", "leverage", "text", {"High": 3, "Medium": 2, "Low": 1}),
    ("Mileage", "miles", "miles", "low"),
    ("Year", "year", "year", None),
    ("Generation", "generation", "text", None),
    ("Trim", "trim", "text", None),
    ("Battery", "battery", "text", BATTERY_RANK),
    ("Motor", "motor", "text", None),
    ("Powered tonneau", "tonneau", "tonneau", TONNEAU_RANK),
    ("Warranty left", "warranty", "text", ("warranty_months_left", "high")),
    ("EPA range", "epa_range", "range", "high"),
    ("Tow capacity", "tow_capacity_lbs", "lbs", "high"),
    ("Tow source", "tow_src", "text", None),
    ("Tow confidence", "tow_conf", "text", None),
    ("Exterior color", "color", "text", None),
    ("Wheels", "wheels", "text", None),
    ("Title", "title_status", "title", TITLE_RANK),
    ("Accidents", "accident_history", "accident", ACCIDENT_RANK),
    ("Owners", "owners", "text", None),
    ("Recalls for model year", "recall_count", "int", "low"),
    ("Sold by", "sold_by", "text", None),
    ("Location", "location", "text", None),
    ("Distance from home", "distance_mi", "miles", "low"),
    ("Transport", "transport_cost", "money", "low"),
    ("Transport basis", "transport_basis", "text", None),
    ("Est. monthly", "est_monthly", "money", "low"),
    ("Cash for target payment", "cash_to_target", "money", "low"),
    ("Total acquisition cost", "total_cost", "money", "low"),
    ("History flags", "flags", "text", None),
    ("Checklist", "checklist", "text", None),
    ("Last contact", "last_contact", "text", None),
    ("Found on", "found_on", "text", None),
    ("VIN", "vin", "text", None),
]


def _fmt(value, kind: str) -> str:
    if kind == "items":
        return " · ".join(value) if isinstance(value, (list, tuple)) and value else "—"
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        return "—"
    if kind == "money":
        return f"-${abs(value):,.0f}" if value < 0 else f"${value:,.0f}"
    if kind == "miles":
        return f"{value:,.0f} mi"
    if kind == "range":
        return f"{value:,.0f} mi range"
    if kind == "lbs":
        return f"{value:,.0f} lb"
    if kind == "int":
        return f"{value:,.0f}"
    if kind == "year":
        return str(int(value))
    if kind == "tonneau":
        return TONNEAU_STATUSES.get(value, value)
    if kind == "title":
        return TITLE_STATUSES.get(value, value)
    if kind == "accident":
        return ACCIDENT_STATUSES.get(value, value)
    return str(value)


def _score(row: pd.Series, col: str, best):
    """Numeric score where higher is better, or None if this cell can't be ranked."""
    if best is None:
        return None
    if isinstance(best, tuple):
        col, best = best
    v = row.get(col)
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    if isinstance(best, dict):
        return best.get(v)
    return -float(v) if best == "low" else float(v)


def vehicle_name(row) -> str:
    year = str(int(row["year"])) if pd.notna(row.get("year")) else ""
    return " ".join(str(v) for v in (year, row.get("make"), row.get("model") or "Truck", row.get("trim"))
                    if v is not None and pd.notna(v) and str(v).strip())


def column_names(trucks: pd.DataFrame) -> list[str]:
    names, seen = [], {}
    for _, r in trucks.iterrows():
        name = vehicle_name(r)
        if r.get("price") and pd.notna(r.get("price")):
            name += f" · ${r['price'] / 1000:.1f}k"
        seen[name] = seen.get(name, 0) + 1
        names.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return names


def build(trucks: pd.DataFrame, rows: list[tuple] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (display table, boolean 'best' mask) with one column per truck."""
    rows = rows or ROWS
    names = column_names(trucks)
    table = pd.DataFrame(index=[r[0] for r in rows], columns=names, dtype=object)
    best = pd.DataFrame(False, index=table.index, columns=names)
    for label, col, kind, rule in rows:
        scores = []
        for name, (_, t) in zip(names, trucks.iterrows()):
            table.at[label, name] = _fmt(t.get(col), kind)
            scores.append(_score(t, col, rule))
        ranked = [s for s in scores if s is not None]
        if len(ranked) >= 2 and len(set(ranked)) > 1:
            top = max(ranked)
            for name, s in zip(names, scores):
                best.at[label, name] = s == top
    return table, best
