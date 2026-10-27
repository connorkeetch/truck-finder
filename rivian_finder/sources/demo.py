"""Synthetic demo inventory. Every record is fake and flagged is_demo; URLs point at example.com.

Each "Run Search" advances a deterministic timeline so change detection can be seen working:
run 2 brings new listings, price drops and disappearances; run 3 more; run 4 a returning listing.
"""
from __future__ import annotations

import random
import sqlite3

from ..db import get_pref, set_pref
from ..extract import RIVIAN_COLORS, extract_attributes
from ..models import FetchResult, NormalizedListing
from ..vin import with_check_digit
from .base import SourceAdapter, scope_hash

FLEET_SIZE = 36
MAX_RUN = 5
YEAR_CODES = {2023: "P", 2024: "R", 2025: "S", 2026: "T"}
SELLERS = [
    ("Demo Motors Draper", "Draper", "UT", "84020"), ("Demo EV Salt Lake", "Salt Lake City", "UT", "84101"),
    ("Demo Auto Provo", "Provo", "UT", "84601"), ("Demo Trucks Ogden", "Ogden", "UT", "84401"),
    ("Demo Imports St George", "St George", "UT", "84770"), ("Demo Boise Motors", "Boise", "ID", "83702"),
    ("Demo Vegas EV", "Las Vegas", "NV", "89101"), ("Demo Phoenix Auto", "Phoenix", "AZ", "85004"),
    ("Demo Denver Trucks", "Denver", "CO", "80202"), ("Demo Irvine EV", "Irvine", "CA", "92618"),
    ("Demo Austin Motors", "Austin", "TX", "78701"), ("Demo Seattle EV", "Seattle", "WA", "98101"),
    ("Demo Orlando Auto", "Orlando", "FL", "32801"), ("Demo Normal Motors", "Normal", "IL", "61761"),
]


def _vehicle(i: int) -> dict:
    rng = random.Random(1000 + i)
    year = rng.choice([2023, 2023, 2024, 2024, 2024, 2025, 2025, 2026])
    gen2 = year >= 2025
    motor = rng.choices(["Dual", "Performance Dual", "Quad", "Tri"],
                        weights=[40, 25, 25, 10 if gen2 else 0])[0]
    battery = rng.choices(["Standard", "Large", "Max"], weights=[20, 50, 30])[0]
    base = {2023: 50500, 2024: 56000, 2025: 63500, 2026: 71000}[year]
    base += {"Dual": 0, "Performance Dual": 3000, "Tri": 9000, "Quad": 11000}[motor]
    base += {"Standard": -4000, "Large": 0, "Max": 5000}[battery]
    lo, hi = {2023: (14000, 46000), 2024: (7000, 32000), 2025: (1500, 18000), 2026: (300, 7000)}[year]
    miles = rng.randint(lo, hi)
    price = int(round((base - miles * 0.12 + rng.randint(-2500, 2500)) / 100.0) * 100)
    seller = SELLERS[i % len(SELLERS)]
    tonneau = rng.choices(["powered", "absent", "broken", "silent", "plain"], weights=[38, 14, 6, 34, 8])[0]
    motor_code = {"Quad": "A", "Dual": "B", "Performance Dual": "B", "Tri": "C"}[motor]
    vin = with_check_digit(f"7FCTG{motor_code}AL0{YEAR_CODES[year]}N9{i:05d}")
    color = rng.choice(RIVIAN_COLORS[:11])
    in_service = f"{rng.randint(1, 12):02d}/{rng.randint(1, 28):02d}/{year - (1 if rng.random() < 0.3 else 0)}"
    parts = [f"DEMO LISTING (synthetic data). {year} Rivian R1T in {color}."]
    if rng.random() < 0.75:
        parts.append(f"{motor}{'' if motor == 'Performance Dual' else '-Motor'} AWD.")
    if rng.random() < 0.7:
        parts.append(f"{battery} Pack.")
    parts.append({
        "powered": "Powered tonneau cover.", "absent": "No tonneau cover.",
        "broken": "Power tonneau not working, needs repair.", "silent": "", "plain": "Tonneau cover included.",
    }[tonneau])
    if rng.random() < 0.6:
        parts.append(f'{rng.choice(["20", "21", "22"])}" {rng.choice(["All-Terrain", "Road", "Sport", "Bright Sport"])} wheels.')
    if rng.random() < 0.5:
        parts.append(f"In-service date: {in_service}.")
    history = rng.choices(["clean", "accident", "branded", "silent"], weights=[60, 8, 3, 29])[0]
    parts.append({"clean": "Clean title, no accidents reported.", "accident": "Clean title. 1 accident reported.",
                  "branded": "Rebuilt title.", "silent": ""}[history])
    return {
        "i": i, "vin": vin, "year": year, "price": price, "miles": miles, "seller": seller, "color": color,
        "description": " ".join(p for p in parts if p),
        "trim": rng.choice(["Adventure", "Explore", "Adventure"] if year < 2025 else ["Dual", "Tri", "Quad", "Adventure"]),
    }


def _timeline(i: int) -> dict:
    rng = random.Random(5000 + i)
    appear = 1
    if i >= FLEET_SIZE - 10:
        appear = 2 if i < FLEET_SIZE - 5 else (3 if i < FLEET_SIZE - 2 else 4)
    disappear, comeback = None, None
    if i in (2, 9, 17, 25):
        disappear = 2
    elif i in (5, 13):
        disappear = 3
    if i == 9:
        comeback = 4
    drops = {r: rng.choice([500, 1000, 1500, 2000, 2500]) for r in (2, 3, 4) if rng.random() < 0.18}
    if i == 4:
        drops[2] = 1800
    mileage_bump = {3: rng.randint(40, 300)} if rng.random() < 0.15 else {}
    return {"appear": appear, "disappear": disappear, "comeback": comeback, "drops": drops, "miles": mileage_bump}


def demo_listings(run_index: int, *, include_general: bool = False) -> list[NormalizedListing]:
    out = []
    for i in range(FLEET_SIZE):
        v, t = _vehicle(i), _timeline(i)
        if run_index < t["appear"]:
            continue
        if t["disappear"] and t["disappear"] <= run_index and not (t["comeback"] and run_index >= t["comeback"]):
            continue
        price = v["price"] - sum(a for r, a in t["drops"].items() if r <= run_index)
        miles = v["miles"] + sum(a for r, a in t["miles"].items() if r <= run_index)
        name, city, state, zip_code = v["seller"]
        desc = v["description"]
        attrs = extract_attributes(desc, "Demo listing text", confidence="low")
        common = dict(source_key="demo", import_method="demo", vin=v["vin"], year=v["year"], make="Rivian",
                      model="R1T", trim=v["trim"], miles=miles, exterior_color=v["color"],
                      description=desc, attributes=attrs, is_demo=True)
        out.append(NormalizedListing(
            source_listing_id=f"demo-{i}", url=f"https://example.com/demo-listing/{i}", price=price,
            seller_name=name, seller_type="dealer", city=city, state=state, zip=zip_code,
            title=f"[DEMO] {v['year']} Rivian R1T {v['trim']}", **common))
        if i in (3, 11, 20):  # same truck listed a second time elsewhere
            out.append(NormalizedListing(
                source_listing_id=f"demo-{i}-b", url=f"https://example.com/demo-classified/{i}",
                price=price + 900, seller_name="Demo Classifieds private seller", seller_type="private",
                city=city, state=state, zip=zip_code, title=f"[DEMO] {v['year']} R1T (classified ad)", **common))
    if include_general:
        # General samples are manual imports, outside the Rivian connector's changing timeline.
        for key, make, model, year, trim, price, miles in (
                ("camry", "Toyota", "Camry", 2025, "SE", 28900, 12000),
                ("cr-v", "Honda", "CR-V", 2024, "EX-L", 31900, 18000),
                ("mach-e", "Ford", "Mustang Mach-E", 2025, "Premium", 34900, 15000)):
            out.append(NormalizedListing(
                source_key="demo", import_method="manual", source_listing_id=f"demo-general-{key}",
                url=f"https://example.com/demo-listing/{key}", year=year, make=make, model=model, trim=trim,
                price=price, miles=miles, seller_name="Demo Motors", seller_type="dealer", city="Denver",
                state="CO", zip="80202", title=f"[DEMO] {year} {make} {model} {trim}",
                description="Synthetic example vehicle for exploring the shopping workflow.", is_demo=True))
    return out


class DemoAdapter(SourceAdapter):
    key = "demo"
    name = "Demo data (synthetic)"

    def __init__(self, conn: sqlite3.Connection, advance: bool = True):
        self.conn = conn
        self.advance = advance

    def fetch(self, scope: dict) -> FetchResult:
        if scope.get("brands") is not None and "Rivian" not in scope["brands"]:
            return FetchResult([], complete=True, scope_hash=scope_hash({"demo": 1, "brands": scope["brands"]}),
                               notes=["Demo inventory contains Rivians; no selected-brand demo listings to refresh."])
        idx = int(get_pref(self.conn, "demo_run_index", 0)) + (1 if self.advance else 0)
        idx = max(1, min(idx, MAX_RUN))
        set_pref(self.conn, "demo_run_index", idx)
        return FetchResult(listings=demo_listings(idx), complete=True, scope_hash=scope_hash({"demo": 1}),
                           notes=[f"Synthetic demo data, timeline step {idx} of {MAX_RUN}."])
