"""Read-only price summaries from one observed listing timeline per vehicle."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite
from statistics import mean, median
from urllib.parse import urlsplit

from .dedup import norm_seller
from .links import listing_role

CAVEAT = ("Prices and dates are observations from stored listings or data feeds, not confirmed dealer "
          "price-change dates. One listing history per VIN is used; feeds are never stitched together. "
          "Observed intervals describe this sample and do not predict the next price cut.")


def _date(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _rivian_seller(name) -> bool:
    name = (name or "").strip().casefold()
    return name == "rivian" or name.startswith("rivian ")


def _official_authority(listing: dict) -> int:
    if listing["source_key"] == "rivian":
        return 3
    try:
        host = (urlsplit(listing["url"] or "").hostname or "").casefold()
    except ValueError:
        host = ""
    if host == "rivian.com" or host.endswith(".rivian.com"):
        return 2
    return int(_rivian_seller(listing["seller_name"]))


def _interval_status(count: int) -> str:
    return "Insufficient history" if not count else "One observed interval" if count == 1 else "Observed intervals"


def _timeline(listing: dict, observations: list[dict], *, official_only: bool = False) -> dict:
    priced = []
    seller = norm_seller(listing["seller_name"])
    for observation in observations:
        if official_only and observation["seller_name"] and not _rivian_seller(observation["seller_name"]):
            continue
        if (not official_only and seller and observation["seller_name"]
                and norm_seller(observation["seller_name"]) != seller):
            continue
        price, at = observation["price"], _date(observation["observed_at"])
        if (at is not None and isinstance(price, (int, float)) and not isinstance(price, bool)
                and isfinite(price) and price > 0):
            priced.append((at, observation["id"], price))
    priced.sort()
    cuts, increases = [], 0
    for previous, current in zip(priced, priced[1:]):
        delta = current[2] - previous[2]
        if delta < 0:
            cuts.append({"previous_observed_at": _iso(previous[0]), "detected_at": _iso(current[0]),
                         "old_price": previous[2], "new_price": current[2], "amount": -delta})
        elif delta > 0:
            increases += 1
    cut_dates = [_date(cut["detected_at"]) for cut in cuts]
    intervals = [(later - earlier).total_seconds() / 86400
                 for earlier, later in zip(cut_dates, cut_dates[1:])]
    amounts = [cut["amount"] for cut in cuts]
    days = len({at.date() for at, _, _ in priced})
    authority = _official_authority(listing)
    basis = {3: "official-source", 2: "official-seller-url", 1: "provider-reported Rivian seller identity"}.get(
        authority, "seller listing" if listing_role(listing["url"], listing["seller_type"])[0] == "seller"
        else "provider listing")
    return {"vehicle_id": listing["vehicle_id"], "vin": listing["vin"], "make": listing["make"],
            "model": listing["model"], "year": listing["year"], "listing_id": listing["id"],
            "source": listing["source_key"], "source_url": listing["url"] or "",
            "seller_name": listing["seller_name"] or "", "listing_status": listing["status"],
            "cohort_basis": basis, "first_observed": _iso(priced[0][0]) if priced else None,
            "latest_observed": _iso(priced[-1][0]) if priced else None,
            "first_observed_price": priced[0][2] if priced else None,
            "latest_observed_price": priced[-1][2] if priced else None,
            "priced_observations": len(priced), "observation_days": days,
            "observation_span_days": (priced[-1][0] - priced[0][0]).total_seconds() / 86400 if priced else 0,
            "history_status": "Repeat-day history" if days >= 2 else "Single observed day" if days else "No priced history",
            "drops_count": len(cuts), "increases_count": increases, "total_reductions": sum(amounts),
            "net_change": priced[-1][2] - priced[0][2] if priced else None,
            "mean_cut": mean(amounts) if amounts else None, "median_cut": median(amounts) if amounts else None,
            "interval_count": len(intervals), "mean_interval_days": mean(intervals) if intervals else None,
            "median_interval_days": median(intervals) if intervals else None,
            "interval_status": _interval_status(len(intervals)), "cuts": cuts, "intervals_days": intervals}


def _choose(timelines: list[dict]) -> dict | None:
    if not timelines:
        return None
    useful = [row for row in timelines if row["observation_days"] >= 2]
    priced = [row for row in timelines if row["priced_observations"]]

    def priority(row):
        authority = {"official-source": 4, "official-seller-url": 3, "seller listing": 2,
                     "provider-reported Rivian seller identity": 1}.get(row["cohort_basis"], 0)
        return (authority, row["observation_span_days"], row["priced_observations"],
                _date(row["latest_observed"]) or datetime.min.replace(tzinfo=timezone.utc), row["listing_id"])

    selected = dict(max(useful or priced or timelines, key=priority))
    selected["listing_timelines"] = len(timelines)
    return selected


def _aggregate(vehicles: list[dict]) -> dict:
    amounts = [cut["amount"] for row in vehicles for cut in row["cuts"]]
    intervals = [gap for row in vehicles for gap in row["intervals_days"]]
    first = [_date(row["first_observed"]) for row in vehicles if row["first_observed"]]
    last = [_date(row["latest_observed"]) for row in vehicles if row["latest_observed"]]
    changes = [row["net_change"] for row in vehicles if row["net_change"] is not None]
    return {"vehicle_count": len(vehicles), "listing_timelines": sum(row["listing_timelines"] for row in vehicles),
            "repeat_day_vehicles": sum(row["observation_days"] >= 2 for row in vehicles),
            "single_day_vehicles": sum(row["observation_days"] == 1 for row in vehicles),
            "no_history_vehicles": sum(not row["priced_observations"] for row in vehicles),
            "cut_bearing_vehicles": sum(bool(row["drops_count"]) for row in vehicles),
            "total_cuts": len(amounts), "total_reductions": sum(amounts),
            "net_change": sum(changes) if changes else None,
            "mean_cut": mean(amounts) if amounts else None, "median_cut": median(amounts) if amounts else None,
            "interval_count": len(intervals), "interval_vehicles": sum(bool(row["interval_count"]) for row in vehicles),
            "mean_interval_days": mean(intervals) if intervals else None,
            "median_interval_days": median(intervals) if intervals else None,
            "interval_status": _interval_status(len(intervals)),
            "first_observed": _iso(min(first)) if first else None,
            "latest_observed": _iso(max(last)) if last else None, "vehicles": vehicles}


def for_vehicle(conn, vehicle_id: int) -> dict:
    """Summarize this vehicle and official Rivian sellers, without fetching or changing data.

    Repeat-day history takes precedence over a sparse direct snapshot. Within that
    group, prefer seller authority, then observed span and observation count.
    Calendar-day coverage is counted in UTC, independently of the viewer's timezone.
    """
    listings = [dict(row) for row in conn.execute("""
        SELECT l.*, v.vin, v.make, v.model, v.year FROM listings l JOIN vehicles v ON v.id=l.vehicle_id
        WHERE v.is_demo=0 AND l.is_demo=0 AND l.import_method!='demo' AND v.merged_into_id IS NULL
          AND (v.id=? OR lower(trim(v.make))='rivian')
        ORDER BY l.id""", (vehicle_id,))]
    candidates = [row for row in listings if row["vehicle_id"] == vehicle_id or _official_authority(row)]
    candidate_ids = {row["id"] for row in candidates}
    observations = defaultdict(list)
    if candidate_ids:
        for row in conn.execute("""
            SELECT o.* FROM observations o JOIN listings l ON l.id=o.listing_id
            JOIN vehicles v ON v.id=l.vehicle_id
            WHERE v.is_demo=0 AND l.is_demo=0 AND l.import_method!='demo' AND v.merged_into_id IS NULL
              AND o.import_method!='demo' AND (v.id=? OR lower(trim(v.make))='rivian')""", (vehicle_id,)):
            if row["listing_id"] in candidate_ids:
                observations[row["listing_id"]].append(dict(row))
    own, cohort = [], defaultdict(list)
    for row in candidates:
        history = observations[row["id"]]
        if row["vehicle_id"] == vehicle_id:
            own.append(_timeline(row, history, official_only=bool(_official_authority(row))))
        if (row["make"] or "").strip().casefold() == "rivian" and _official_authority(row):
            key = (row["vin"] or f"vehicle:{row['vehicle_id']}").strip().casefold()
            cohort[key].append(_timeline(row, history, official_only=True))
    return {"vehicle": _choose(own), "rivian_seller": _aggregate([_choose(rows) for rows in cohort.values()]),
            "caveat": CAVEAT}
