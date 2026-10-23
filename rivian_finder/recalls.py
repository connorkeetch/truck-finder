"""NHTSA safety recalls by model year (free API, no key): https://api.nhtsa.gov/recalls/recallsByVehicle

Recalls are issued per model year, not per VIN. Whether a specific truck's recall work was done can only be
checked with NHTSA's VIN lookup (reCAPTCHA-protected, so it's a link) or with Rivian.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import requests

from .db import utcnow

API = "https://api.nhtsa.gov/recalls/recallsByVehicle"
VIN_LOOKUP = "https://www.nhtsa.gov/recalls"
REFRESH_DAYS = 7


def _iso(ddmmyyyy: str | None) -> str | None:
    try:
        return datetime.strptime(ddmmyyyy or "", "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def fetch(model_year: int, model: str = "R1T", session: requests.Session | None = None) -> list[dict]:
    s = session or requests.Session()
    r = s.get(API, params={"make": "RIVIAN", "model": model, "modelYear": model_year}, timeout=30)
    r.raise_for_status()
    return r.json().get("results") or []


def refresh(conn: sqlite3.Connection, years: list[int] | None = None, model: str = "R1T",
            session: requests.Session | None = None, force: bool = False) -> dict:
    """Update cached recalls for the given model years (default: years of stored trucks). Weekly at most."""
    if years is None:
        years = sorted({r[0] for r in conn.execute(
            "SELECT DISTINCT year FROM vehicles WHERE year IS NOT NULL AND is_demo = 0 AND merged_into_id IS NULL"
            " AND UPPER(COALESCE(make, 'Rivian'))='RIVIAN' AND UPPER(COALESCE(model, 'R1T'))=?", (model.upper(),))})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=REFRESH_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fetched, errors = 0, []
    for year in years:
        if not force and conn.execute("SELECT 1 FROM recalls WHERE model=? AND model_year=? AND fetched_at > ? LIMIT 1",
                                      (model, year, cutoff)).fetchone():
            continue
        try:
            results = fetch(year, model, session)
        except (requests.RequestException, ValueError) as e:
            errors.append(f"{year}: {type(e).__name__}")
            continue
        now = utcnow()
        with conn:
            conn.execute("DELETE FROM recalls WHERE model=? AND model_year=?", (model, year))
            for x in results:
                conn.execute(
                    "INSERT OR REPLACE INTO recalls(campaign, model, model_year, report_date, component, summary,"
                    " consequence, remedy, ota, park_it, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (x.get("NHTSACampaignNumber"), model, year, _iso(x.get("ReportReceivedDate")), x.get("Component"),
                     x.get("Summary"), x.get("Consequence"), x.get("Remedy"), int(bool(x.get("overTheAirUpdate"))),
                     int(bool(x.get("parkIt"))), now))
            if not results:  # remember that we checked, so an empty year isn't re-fetched every run
                conn.execute("INSERT OR REPLACE INTO recalls(campaign, model, model_year, fetched_at) VALUES (?,?,?,?)",
                             ("(none)", model, year, now))
        fetched += 1
    return {"years_fetched": fetched, "errors": errors}


def for_year(conn: sqlite3.Connection, year: int | None, model: str = "R1T") -> list[dict]:
    if not year:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT * FROM recalls WHERE model=? AND model_year=? AND campaign != '(none)' ORDER BY report_date DESC",
        (model, int(year)))]


def counts_by_year(conn: sqlite3.Connection, model: str = "R1T") -> dict[int, int]:
    return {r[0]: r[1] for r in conn.execute(
        "SELECT model_year, COUNT(*) FROM recalls WHERE model=? AND campaign != '(none)' GROUP BY model_year", (model,))}
