"""Negotiation leverage: how long a truck has been listed and how its price has moved."""
from __future__ import annotations

from datetime import datetime, timezone


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def price_moves(observations: list[tuple[str, int]]) -> dict:
    """observations: [(observed_at, price)] in time order for one listing."""
    prices: list[int] = []
    drops, dropped, last_drop = 0, 0, None
    for at, price in observations:
        if price is None:
            continue
        if prices and price < prices[-1]:
            drops += 1
            dropped += prices[-1] - price
            last_drop = at
        if not prices or price != prices[-1]:
            prices.append(price)
    return {"first": prices[0] if prices else None, "prices": prices, "drops": drops, "dropped": dropped,
            "last_drop_at": last_drop, "peak": max(prices) if prices else None,
            "last_change": (prices[-1] - prices[-2]) if len(prices) > 1 else 0,
            "total_change": (prices[-1] - prices[0]) if prices else 0}


def days_listed(listings: list[dict], now: datetime | None = None) -> tuple[int | None, str | None, str]:
    """(days, listed_since ISO, how we know). Takes the longest evidence across all of a truck's listings."""
    now = now or datetime.now(timezone.utc)
    best_days, since, source = None, None, ""
    for l in listings:
        for iso, label in ((l.get("listed_at"), "provider's first-seen date"),
                           (l.get("first_seen_at"), "first seen by Truck Finder")):
            dt = _parse(iso)
            if dt:
                d = max((now - dt).days, 0)
                if best_days is None or d > best_days:
                    best_days, since, source = d, dt.date().isoformat(), label
        dom = l.get("days_on_market")
        if dom is not None and (best_days is None or dom > best_days):
            best_days, since, source = int(dom), None, "MarketCheck days-on-market"
    return best_days, since, source


def leverage(days: int | None, drops: int, dropped: int) -> tuple[str, str]:
    """Heuristic only: long-listed trucks and sellers who've already cut price tend to have room to move."""
    if days is None and not drops:
        return "Unknown", "No listing-age data yet"
    days = days or 0
    if days >= 60 or drops >= 2:
        level = "High"
    elif days >= 30 or drops == 1:
        level = "Medium"
    else:
        level = "Low"
    parts = [f"listed {days} days"] if days else []
    if drops:
        parts.append(f"{drops} price drop{'s' if drops != 1 else ''} (−${dropped:,})")
    return level, ", ".join(parts) or "recently listed"
