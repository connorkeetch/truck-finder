"""Offline ZIP lookup and straight-line distance."""
from __future__ import annotations

import math
from functools import lru_cache

import zipcodes


@lru_cache(maxsize=4096)
def zip_latlon(zip_code: str | None) -> tuple[float, float] | None:
    if not zip_code:
        return None
    z = str(zip_code).strip()[:5]
    if len(z) != 5 or not z.isdigit():
        return None
    try:
        matches = zipcodes.matching(z)
    except (ValueError, TypeError):
        return None
    if not matches:
        return None
    try:
        return float(matches[0]["lat"]), float(matches[0]["long"])
    except (KeyError, TypeError, ValueError):
        return None


@lru_cache(maxsize=4096)
def city_latlon(city: str | None, state: str | None) -> tuple[float, float] | None:
    """Rough centre of a city (average of its ZIP centroids) — for listings that give a city but no ZIP."""
    if not city or not state:
        return None
    try:
        matches = zipcodes.filter_by(city=city.strip().title(), state=state.strip().upper())
    except (ValueError, TypeError):
        return None
    pts = [(float(m["lat"]), float(m["long"])) for m in matches if m.get("lat") and m.get("long")]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


@lru_cache(maxsize=4096)
def zip_state(zip_code: str | None) -> str | None:
    if not zip_code:
        return None
    try:
        matches = zipcodes.matching(str(zip_code).strip()[:5])
    except (ValueError, TypeError):
        return None
    return matches[0]["state"] if matches else None


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def usable_coords(lat: float | None, lon: float | None) -> bool:
    """Real coordinates — not missing, and not the 0,0 some providers send when they don't know."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(lat) or math.isnan(lon):
        return False
    return not (abs(lat) < 1e-6 and abs(lon) < 1e-6)


def distance_from_zip(home_zip: str, lat: float | None, lon: float | None, zip_code: str | None,
                      city: str | None = None, state: str | None = None) -> float | None:
    """Straight-line miles from home ZIP to a listing (coordinates preferred, else its ZIP, else its city)."""
    home = zip_latlon(home_zip)
    if not home:
        return None
    if usable_coords(lat, lon):
        point = (float(lat), float(lon))
    else:
        point = zip_latlon(zip_code) or city_latlon(city, state)
    if not point:
        return None
    return round(haversine_miles(home, point), 0)
