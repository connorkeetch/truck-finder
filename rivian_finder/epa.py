"""EPA range ratings for every R1T configuration (fueleconomy.gov), and per-truck range estimates.

Range depends on model year, motor, battery pack and wheel size. With all four known we can give the official
rating; with wheels unknown we give the span across the wheel options. The table ships with the app
(rivian_finder/data/epa_r1t.json) and can be refreshed from fueleconomy.gov's free web service.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

import requests

DATA_FILE = Path(__file__).parent / "data" / "epa_r1t.json"
BASE = "https://www.fueleconomy.gov/ws/rest"


def parse_model(year: int, name: str) -> dict:
    """'R1T All-Terrain Performance Dual Large Plus (20in)' -> motor/battery/wheels fields."""
    n = name.replace("All-Terrain", "AT")
    wheels = re.search(r"(\d{2})\s*(?:in|inch)", n)
    motor = ("Performance Dual" if "Performance Dual" in n else "Dual" if re.search(r"\bDual\b", n)
             else "Tri" if "Tri" in n else "Quad")            # early (2022–23) entries without a motor were Quad
    battery = ("Large+" if "Large Plus" in n else "Standard+" if "Standard Plus" in n else
               "Max" if "Max" in n else "Large" if "Large" in n else "Standard" if "Standard" in n else "Large")
    return {"year": year, "name": name, "motor": motor, "battery": battery,
            "wheels": int(wheels.group(1)) if wheels else None, "all_terrain": bool(re.search(r"\bAT\b", n))}


def refresh(path: Path = DATA_FILE, years: range = range(2022, 2028), session: requests.Session | None = None) -> int:
    """Download every R1T rating from fueleconomy.gov and rewrite the table. Returns the number of ratings."""
    s = session or requests.Session()
    rows = []
    for year in years:
        r = s.get(f"{BASE}/vehicle/menu/model", params={"year": year, "make": "Rivian"}, timeout=30)
        models = [m.findtext("value") for m in ET.fromstring(r.content).findall("menuItem")]
        for model in (m for m in models if m and m.startswith("R1T")):
            opts = ET.fromstring(s.get(f"{BASE}/vehicle/menu/options",
                                       params={"year": year, "make": "Rivian", "model": model}, timeout=30).content)
            for o in opts.findall("menuItem"):
                v = ET.fromstring(s.get(f"{BASE}/vehicle/{o.findtext('value')}", timeout=30).content)
                rng = v.findtext("range")
                if rng and rng.isdigit():
                    rows.append({**parse_model(year, model), "range": int(rng), "epa_id": o.findtext("value")})
    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"source": "fueleconomy.gov", "ratings": rows}, indent=1), encoding="utf-8")
        table.cache_clear()
    return len(rows)


@lru_cache(maxsize=1)
def table() -> tuple[dict, ...]:
    try:
        return tuple(json.loads(DATA_FILE.read_text(encoding="utf-8"))["ratings"])
    except (OSError, ValueError, KeyError):
        return ()


def _wheel_size(wheels: str | None) -> int | None:
    m = re.search(r"\b(20|21|22)\b", wheels or "")
    return int(m.group(1)) if m else None


def rated_year(year, battery: str | None) -> int | None:
    """The model year whose ratings apply: this one, or the nearest that rated this pack (prefer later).

    The Max pack reached the R1T late in the 2023 model year with the same hardware as 2024, but fueleconomy.gov
    only rates it from 2024 — so a 2023 Max uses the 2024 ratings."""
    years = {r["year"] for r in table() if r["battery"] == battery}
    if not year or not years:
        return None
    return int(year) if int(year) in years else min(years, key=lambda y: (abs(y - int(year)), y < int(year)))


def candidates(year, motor: str | None, battery: str | None, wheels: str | None = None) -> list[dict]:
    if not year or not battery or battery == "Unknown":
        return []
    rated = rated_year(year, battery)
    rows = [r for r in table() if r["year"] == rated and r["battery"] == battery]
    if motor and motor != "Unknown":
        rows = [r for r in rows if r["motor"] == motor] or (
            [r for r in rows if r["motor"] == "Dual"] if motor == "Performance Dual" else [])
    size = _wheel_size(wheels)
    if size:
        exact = [r for r in rows if r["wheels"] == size and (r["all_terrain"] == ("terrain" in (wheels or "").lower()
                                                                                  or "AT" in (wheels or "")))]
        rows = exact or [r for r in rows if r["wheels"] == size] or rows
    return rows


def estimate(year, motor: str | None, battery: str | None, wheels: str | None = None) -> dict:
    """{'low','high','text','basis'} — empty text when the configuration isn't known well enough."""
    rows = candidates(year, motor, battery, wheels)
    if not rows:
        return {"low": None, "high": None, "text": "", "basis": ""}
    lo, hi = min(r["range"] for r in rows), max(r["range"] for r in rows)
    text = f"{lo}" if lo == hi else f"{lo}–{hi}"
    rated = rows[0]["year"]
    cfg = f"{rated} {motor if motor and motor != 'Unknown' else 'any motor'} {battery}"
    basis = f"EPA rating for {cfg}" + (f" on {wheels}" if lo == hi and wheels else
                                        " (wheel size unknown)" if lo != hi else "")
    if rated != int(year):
        basis += f" (no {int(year)} {battery} rating — same pack)"
    return {"low": lo, "high": hi, "text": text, "basis": basis + " — fueleconomy.gov"}


def batteries_for_range(year, motor: str | None, rated_range: int) -> set[str]:
    """Which battery packs carry this EPA rating for the year/motor — a cross-check on the listing's battery."""
    rows = [r for r in table() if r["year"] == int(year) and r["range"] == int(rated_range)]
    if motor and motor != "Unknown":
        rows = [r for r in rows if r["motor"] in (motor, "Dual" if motor == "Performance Dual" else motor)]
    return {r["battery"] for r in rows}
