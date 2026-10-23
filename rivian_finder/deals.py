"""Deal rating: how a truck's price compares with similar trucks in your own collected data.

A small ridge regression (price ~ model year + miles + battery + motor + tonneau listed) is fit on active,
priced trucks without branded titles or reported accidents. Each training truck's estimate is leave-one-out,
so a truck never vouches for its own price. A plain "comparables" median is reported alongside for intuition.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_TRAINING = 20
SUSPICIOUS_PCT = -0.15     # this far under market has meant branded/rebuilt titles in practice
RIDGE = 1.0
BANDS = [(-0.08, "Great deal"), (-0.03, "Good deal"), (0.03, "Fair price"), (0.08, "Above market")]
BATTERY_LEVELS = ["Max", "Large", "Standard+", "Standard"]          # baseline: Unknown
MOTOR_LEVELS = ["Quad", "Tri", "Performance Dual", "Dual"]          # baseline: Unknown


def label_for(pct: float | None) -> str:
    if pct is None or pd.isna(pct):
        return "Not rated"
    for limit, label in BANDS:
        if pct <= limit:
            return label
    return "Overpriced"


def _design(df: pd.DataFrame, years: list[int]) -> np.ndarray:
    cols = [np.ones(len(df))]
    cols += [(df["year"] == y).to_numpy(dtype=float) for y in years[1:]]   # first year is the baseline
    cols.append(df["miles"].to_numpy(dtype=float) / 10000.0)
    battery = df["battery"].where(~df.get("battery_uncertain", False), "Unknown") if "battery_uncertain" in df else df["battery"]
    cols += [(battery == b).to_numpy(dtype=float) for b in BATTERY_LEVELS]
    cols += [(df["motor"] == m).to_numpy(dtype=float) for m in MOTOR_LEVELS]
    cols.append(df["tonneau"].eq("yes").to_numpy(dtype=float))
    return np.column_stack(cols)


def _training_mask(df: pd.DataFrame) -> pd.Series:
    m = (df["status"] == "active") & df["price"].between(15000, 150000) & df["miles"].notna() & df["year"].notna()
    m &= df["title_status"] != "branded"
    m &= df["accident_history"] != "reported"
    real = m & ~df["is_demo"]
    return real if real.sum() >= MIN_TRAINING else m   # demo-only databases still get a (demo) rating


def comparables(df: pd.DataFrame, pool_mask: pd.Series, i, miles_window: int = 10000) -> tuple[int, float | None, str]:
    """Same model year (and motor, when known) within ±miles_window in the pool, excluding the truck itself."""
    pos = df.index.get_loc(i)
    return _comparables_at(_comp_arrays(df, pool_mask), pos, miles_window)


def _comp_arrays(df: pd.DataFrame, pool_mask: pd.Series) -> dict:
    # plain numpy arrays: comparing 400 trucks against each other with pandas row lookups took ~0.7 s
    return {"year": df["year"].to_numpy(dtype=float), "miles": df["miles"].to_numpy(dtype=float),
            "motor": df["motor"].astype(str).to_numpy(), "price": df["price"].to_numpy(dtype=float),
            "model": (df["make"].fillna("").str.lower() + " " + df["model"].fillna("").str.lower()).to_numpy()
            if "make" in df and "model" in df else np.full(len(df), ""),
            "pool": pool_mask.reindex(df.index, fill_value=False).to_numpy(dtype=bool)}


def _comparables_at(a: dict, pos: int, miles_window: int = 10000) -> tuple[int, float | None, str]:
    year, miles, motor = a["year"][pos], a["miles"][pos], a["motor"][pos]
    if np.isnan(year) or np.isnan(miles):
        return 0, None, ""
    m = a["pool"] & (a["year"] == year) & (np.abs(a["miles"] - miles) <= miles_window)
    m &= a["model"] == a["model"][pos]
    m[pos] = False
    desc = f"{int(year)}"
    if motor != "Unknown":
        m &= a["motor"] == motor
        desc += f" {motor}"
    n = int(m.sum())
    if not n:
        return 0, None, f"no comparable {desc} trucks within ±{miles_window // 1000}k mi"
    median = float(np.median(a["price"][m]))
    lo, hi = max(int(miles) - miles_window, 0), int(miles) + miles_window
    return n, median, f"{n} comparable {desc} truck{'s' if n != 1 else ''} ({lo // 1000}–{hi // 1000}k mi): median ${median:,.0f}"


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    """Add market_price, deal_delta, deal_pct, deal_label, comps_n, comps_median, comps_text, deal_note."""
    if not df.empty and "make" in df and "model" in df:
        groups = df.groupby([df["make"].fillna("").str.lower(), df["model"].fillna("").str.lower()], sort=False)
        if groups.ngroups > 1:
            return pd.concat([annotate(group) for _, group in groups]).reindex(df.index)
    out = df.copy()
    for col in ("market_price", "deal_delta", "deal_pct", "comps_median"):
        out[col] = np.nan
    out["deal_label"] = "Not rated"
    out["comps_n"] = 0
    out["comps_text"] = ""
    out["deal_note"] = ""
    if out.empty:
        return out
    train = _training_mask(out)
    years = sorted(int(y) for y in out.loc[train, "year"].dropna().unique())
    n = int(train.sum())
    if n < MIN_TRAINING or not years:
        out["deal_note"] = f"Needs at least {MIN_TRAINING} priced trucks to rate deals (have {n})."
        return out
    X = _design(out.loc[train], years)
    if n < 3 * X.shape[1]:
        out["deal_note"] = f"Not enough trucks for a reliable estimate ({n} for {X.shape[1]} factors)."
        return out
    y = out.loc[train, "price"].to_numpy(dtype=float)
    penalty = RIDGE * np.eye(X.shape[1])
    penalty[0, 0] = 0.0                                   # don't shrink the intercept
    inv = np.linalg.inv(X.T @ X + penalty)
    beta = inv @ X.T @ y
    resid = y - X @ beta
    hat = np.einsum("ij,jk,ik->i", X, inv, X)
    loo_pred = y - resid / np.clip(1 - hat, 1e-6, None)    # leave-one-out estimate for each training truck
    typical = float(np.sqrt(np.mean(((y - loo_pred) / loo_pred) ** 2)))

    can_predict = out["year"].notna() & out["miles"].notna() & out["price"].notna()
    can_predict &= out["year"].isin(years)              # don't extrapolate to model years with no data
    pred = pd.Series(np.nan, index=out.index)
    if can_predict.any():
        pred[can_predict] = _design(out.loc[can_predict], years) @ beta
    pred[train] = loo_pred
    out["market_price"] = pred.round(-2)
    out["deal_delta"] = (out["price"] - pred).round(0)
    out["deal_pct"] = (out["price"] - pred) / pred
    out["deal_label"] = out["deal_pct"].map(label_for)
    # A branded/accident truck is "cheap" for a reason; don't advertise it as a deal.
    branded = out["title_status"] == "branded"
    out.loc[branded, "deal_label"] = "Not rated (branded title)"
    suspicious = (out["deal_pct"] <= SUSPICIOUS_PCT) & ~branded & (out["title_status"] != "clean")
    out.loc[suspicious, "deal_label"] = "⚠ Check title"
    accident = (out["accident_history"] == "reported") & ~branded & out["deal_pct"].notna()
    out.loc[accident, "deal_label"] = out.loc[accident, "deal_label"] + " (accident reported)"
    note = f"Estimated from {n} similar trucks; typical estimate error ±{typical:.0%}."
    out.loc[can_predict, "deal_note"] = note
    out.loc[suspicious, "deal_note"] = (note + f" Priced {SUSPICIOUS_PCT:.0%} or more under similar trucks — that has "
                                        "usually meant a branded/rebuilt title or damage. Check the Carfax; if it's "
                                        "branded, use Not interested → Branded title.")
    out.loc[~can_predict & out["price"].notna(), "deal_note"] = "Not rated: model year or mileage unknown or outside the data."
    arrays = _comp_arrays(out, train)
    results = {i: _comparables_at(arrays, pos) for pos, i in enumerate(out.index) if not np.isnan(arrays["price"][pos])}
    if results:
        idx = list(results)
        out.loc[idx, "comps_n"] = [r[0] for r in results.values()]
        out.loc[idx, "comps_median"] = [np.nan if r[1] is None else r[1] for r in results.values()]
        out.loc[idx, "comps_text"] = [r[2] for r in results.values()]
    return out
