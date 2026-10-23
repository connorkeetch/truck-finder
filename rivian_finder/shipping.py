"""Transport estimate per truck. Rules, in order:

1. A cost you typed for the listing always wins (Carvana / CarMax show their exact fee on the listing).
2. Within your local radius → $0 (you pick it up).
3. Carvana and CarMax charge their own delivery fee: about $290 from a nearby hub (e.g. Las Vegas), $990 farther.
4. Sellers that deliver as part of the price (Vroom by default) → $0, "included".
5. Otherwise: base + $/mile × road miles (straight-line × road factor), never below the minimum.
6. Fly & drive: within a day's drive, flying there and driving it home (flight + rideshare/food + fast charging)
   is used instead whenever it's cheaper than steps 3–5. Not for sellers that only deliver (Carvana by default).
Estimates only; not a quote.
"""
from __future__ import annotations

import re

from .links import host_of

INCLUDED_SELLERS = {"carmax": "CarMax", "carvana": "Carvana", "vroom": "Vroom"}
DEFAULTS = {
    "included_sellers": [],
    "fee_sellers": [],    # opt in to seller-specific delivery estimates
    "fee_near": 290.0,
    "fee_far": 990.0,
    "fee_near_mi": 450,
    "fly_drive": {"enabled": False, "max_road_miles": 650, "flight": 60.0, "ground": 50.0, "mi_per_kwh": 2.0,
                  "price_per_kwh": 0.55, "start_kwh": 100.0, "delivery_only": ["carvana"]},
    "local_radius_mi": 150,
    "base": 300.0,
    "per_mile": 0.95,
    "road_factor": 1.2,
    "minimum": 600.0,
}


def seller_key(listing: dict) -> str | None:
    """Which known delivering seller (if any) holds this listing: by site, URL host, or dealer name."""
    src = (listing.get("source_key") or "").lower()
    host = host_of(listing.get("url"))
    name = re.sub(r"[^a-z]", "", (listing.get("seller_name") or "").lower())
    for key in INCLUDED_SELLERS:
        if src == key or host.endswith(f"{key}.com") or name.startswith(key):
            return key
    return None


def fly_drive(road_miles: float, cfg: dict) -> tuple[float, str]:
    """(cost, breakdown) of flying to the truck and driving it home."""
    fd = {**DEFAULTS["fly_drive"], **(cfg or {})}
    kwh = max(road_miles / float(fd["mi_per_kwh"]) - float(fd["start_kwh"]), 0.0)
    charging = kwh * float(fd["price_per_kwh"])
    cost = round((float(fd["flight"]) + float(fd["ground"]) + charging) / 5) * 5
    return float(cost), (f"flight ${float(fd['flight']):,.0f} + charging ${charging:,.0f} (~{road_miles:,.0f} road mi) "
                         f"+ rideshare/food ${float(fd['ground']):,.0f}")


def estimate(listing: dict, distance_mi: float | None, cfg: dict | None = None,
             fallback: float = 0.0) -> tuple[float, str]:
    """(cost, basis) for getting this truck home — the cheaper of shipping it and flying out to drive it back."""
    c = {**DEFAULTS, **(cfg or {})}
    cost, basis = _ship(listing, distance_mi, c, fallback)
    fd = {**DEFAULTS["fly_drive"], **(c.get("fly_drive") or {})}
    key = seller_key(listing)
    known = distance_mi is not None and distance_mi == distance_mi
    if (fd.get("enabled") and known and cost > 0 and not basis.startswith(("Your estimate", "Local pickup"))
            and key not in (fd.get("delivery_only") or [])):
        road = float(distance_mi) * float(c["road_factor"])
        if road <= float(fd["max_road_miles"]):
            fly_cost, how = fly_drive(road, fd)
            if fly_cost < cost:
                return fly_cost, f"Fly & drive: {how} — cheaper than shipping (${cost:,.0f})"
    return cost, basis


def _ship(listing: dict, distance_mi: float | None, c: dict, fallback: float) -> tuple[float, str]:
    if listing.get("transport_cost") is not None:
        return float(listing["transport_cost"]), "Your estimate"
    key = seller_key(listing)
    known = distance_mi is not None and distance_mi == distance_mi        # not unknown / NaN
    if known and distance_mi <= float(c["local_radius_mi"]):
        return 0.0, f"Local pickup (within {int(c['local_radius_mi'])} mi)"
    if key and key in (c.get("fee_sellers") or []):
        near = known and distance_mi <= float(c["fee_near_mi"])
        fee = float(c["fee_near"] if near else c["fee_far"])
        return fee, (f"{INCLUDED_SELLERS[key]} delivery fee est. (${float(c['fee_near']):,.0f} within "
                     f"{int(c['fee_near_mi'])} mi, ${float(c['fee_far']):,.0f} beyond"
                     + ("" if known else "; distance unknown") + ") — type the exact fee from the listing")
    if key and key in (c.get("included_sellers") or []):
        return 0.0, f"Included by {INCLUDED_SELLERS[key]} (confirm any transfer fee)"
    if not known:
        return float(fallback), "Distance unknown — default from Settings"
    road = distance_mi * float(c["road_factor"])
    cost = max(float(c["base"]) + float(c["per_mile"]) * road, float(c["minimum"]))
    cost = round(cost / 50) * 50
    return float(cost), f"Shipping est. ~{road:,.0f} road mi × ${float(c['per_mile']):.2f} + ${float(c['base']):,.0f}"
