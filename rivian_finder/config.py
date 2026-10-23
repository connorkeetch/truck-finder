"""Paths, environment loading, and default user settings."""
from __future__ import annotations

import copy
import os
import platform
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = Path(os.environ.get("RIVIAN_FINDER_DATA_DIR", PROJECT_ROOT / "data")).resolve()
DB_PATH = Path(os.environ.get("RIVIAN_FINDER_DB", DATA_DIR / "rivian_finder.db")).resolve()
BACKUP_DIR = DATA_DIR / "backups"
EXPORT_DIR = DATA_DIR / "exports"
LOG_DIR = DATA_DIR / "logs"

CAPTURE_HOST = "127.0.0.1"
CAPTURE_PORT = int(os.environ.get("RIVIAN_FINDER_CAPTURE_PORT", "8765"))

HOST_OS = platform.system()  # 'Windows' | 'Darwin' | 'Linux'

TONNEAU_STATUSES = {"yes": "Yes", "no": "No", "unknown": "Unknown"}   # powered tonneau
OLD_TONNEAU = {"confirmed_operational": "yes", "listed_unverified": "yes", "confirmed_absent": "no"}
BATTERIES = ["Max", "Large+", "Large", "Standard+", "Standard", "Unknown"]
MOTORS = ["Quad", "Tri", "Performance Dual", "Dual", "Unknown"]
GENERATIONS = ["Gen 1", "Gen 2", "Unknown"]
TITLE_STATUSES = {"clean": "Clean", "branded": "Branded/salvage/rebuilt", "unknown": "Unknown"}
ACCIDENT_STATUSES = {"none_reported": "None reported", "reported": "Accident reported", "unknown": "Unknown"}

US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

DEFAULT_SETTINGS: dict = {
    "home_zip": "",
    "priority_states": [],
    # Display filters: applied locally to everything in the database. Changing them never triggers a refetch.
    "filters": {
        "make": "",
        "model": "",
        "brands": [],                # empty = all collected brands
        "trims": [],                 # empty = all eligible trim families
        "min_range": 0,
        "include_unknown_range": True,
        "year_min": 2000,
        "year_max": 2026,
        "generations": ["Gen 1", "Gen 2", "Unknown"],
        "max_price": 65000,
        "max_miles": 100000,
        "batteries": list(BATTERIES),
        "motors": list(MOTORS),
        "tonneau": list(TONNEAU_STATUSES.keys()),
        "states": [],                 # empty = nationwide
        "max_distance": 0,            # 0 = no limit
        "hide_branded_title": True,
        "hide_reported_accidents": False,
        "subframes": ["cast", "welded", "unsure", "unknown"],     # front subframe (estimated from the VIN)
        "favorites_only": False,
        "include_missing": False,
        "show_demo": True,
        "near_misses": True,          # also show trucks slightly over max price / miles
        "near_miss_price_pct": 5,
        "near_miss_miles_pct": 10,
        "count_discounts": True,      # compare Max price with your price after seller discounts
        "show_hidden": False,         # trucks you marked "not interested"
        "hidden_only": False,
    },
    # Collection scope: what API connectors ask providers for. Deliberately broader than the display
    # filters so tightening a filter does not make listings look like they disappeared.
    "collection": {
        "make": "Rivian",
        "model": "R1T",
        "searches": [{"make": "Rivian", "model": "R1T"}],  # editable example, not a model whitelist
        "year_min": 2000,
        "year_max": 2026,
        "max_price": 75000,
        "max_miles": 100000,
        "used_only": True,
        "include_other_brands": False,
        "other_max_miles": 100000,
        "other_max_distance": 650,
        "other_min_range": 0,
        "exclude_standard_range": False,
        "excluded_trims": {},
        "marketcheck_zip": "",
        "marketcheck_radius": 100,     # free tier is limited to 100 miles
        "max_pages_per_run": 40,
        "vpic_enrichment": True,
        "mc_second_opinion": False,   # optional extra MarketCheck VIN calls for Rivian battery evidence
    },
    "finance": {
        "target_monthly": 1000.0,
        "terms": [60, 72],
        "aprs": [6.0],
        "current_vehicle": "",
        "trade_payoff": 0.0,
        "trade_in_low": 0.0,
        "trade_in_high": 0.0,
        "cash_offer": 0.0,
        "sales_tax_rate": 0.0,
        "dmv_fees": 0.0,
        "doc_fee": 0.0,
        "extra_cash_down": 0.0,
        "default_transport_cost": 0.0,
        # Set these to match the buyer's location and transaction.
        "trade_in_reduces_taxable": False,
        "cash_sale_reduces_taxable": False,
        "primary_scenario": "cash_sale",   # cash_sale | trade_low | trade_high
        "primary_term": 72,
        "primary_apr": 6.0,
        "discounts": [],
    },
    # Rivian New Vehicle Limited Warranty terms used to estimate remaining coverage.
    # Verify against Rivian's warranty guide for the specific VIN before relying on them.
    "warranty": {
        # Comprehensive: 4 yr / 50k, longer for the motors listed. Battery & drivetrain: 8 yr, miles by pack.
        # A truck's own warranty dates (pasted from Rivian/Carfax) always beat these rules.
        "comprehensive_years": 4,
        "comprehensive_miles": 50000,
        "longer_motors": ["Quad"],
        "longer_years": 5,
        "longer_miles": 60000,
        "battery_years": 8,
        "battery_miles_large_max": 175000,
        "battery_miles_standard": 150000,
    },
    "adjustments": {                       # your adjusted price = your price + shipping − what features are worth to you
        "include_shipping": False,
        "rules": [],
        # range below "ok_at" costs per_mile; below "floor" it costs per_mile + per_mile_below_floor
        "range_value": {"enabled": False, "ok_at": 0, "per_mile": 0.0, "floor": 0, "per_mile_below_floor": 0.0},
        # each month of comprehensive warranty beyond / short of the baseline is worth this much
        "warranty_value": {"enabled": False, "per_month": 0.0, "baseline": "", "annual_miles": 12000},
    },
    "shipping": {
        "included_sellers": [],                              # add sellers whose delivery is included
        "fee_sellers": [],                                   # add sellers with a known delivery-fee estimate
        "fee_near": 290.0, "fee_far": 990.0, "fee_near_mi": 450,
        "fly_drive": {"enabled": False, "max_road_miles": 650, "flight": 60.0, "ground": 50.0, "mi_per_kwh": 2.0,
                      "price_per_kwh": 0.55, "start_kwh": 100.0, "delivery_only": ["carvana"]},
        "local_radius_mi": 150,                              # pick it up yourself within this distance
        "base": 300.0,
        "per_mile": 0.95,                                    # open-carrier ballpark per road mile
        "road_factor": 1.2,                                  # road miles ≈ straight-line × 1.2
        "minimum": 600.0,
    },
    "alerts": {
        "enabled": False,
        "times": ["08:00"],
        "new_matches": True,
        "favorite_drops": True,
        "great_deals": True,
        "min_drop": 0,
        "notify_when_nothing": False,
    },
    "ui": {
        "photo_size": "L",        # S / M / L / XL thumbnails in tables
    },
    "export": {
        "new_listing_window_days": 7,
        "include_filtered_out": False,
        "export_dir": "",
    },
}


def default_settings() -> dict:
    return copy.deepcopy(DEFAULT_SETTINGS)


def merge_settings(stored: dict | None) -> dict:
    """Overlay stored settings on defaults so new settings keys always have a value."""
    merged = default_settings()
    for section, value in (stored or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(section), dict):
            merged[section].update(value)
        else:
            merged[section] = value
    if stored and "searches" not in stored.get("collection", {}):
        merged["collection"]["searches"] = None  # Keep existing collection behavior until searches are explicitly saved.
    ton = merged.get("filters", {}).get("tonneau")
    if isinstance(ton, list):                        # saved before tonneau became yes / no / unknown
        merged["filters"]["tonneau"] = list(dict.fromkeys(OLD_TONNEAU.get(t, t) for t in ton
                                                          if OLD_TONNEAU.get(t, t) in TONNEAU_STATUSES)) \
            or list(TONNEAU_STATUSES)
    return merged


def ensure_dirs() -> None:
    for d in (DATA_DIR, BACKUP_DIR, EXPORT_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
