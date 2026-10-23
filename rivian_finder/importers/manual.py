"""Manual entry and CSV/JSON import. A URL is stored as a reference only; it is never fetched."""
from __future__ import annotations

import csv
import io
import json

from ..config import TONNEAU_STATUSES
from ..extract import (canonical_url, extract_attributes, identify_site, normalize_state, parse_int, parse_location,
                       parse_miles, parse_price, parse_truck_identity, parse_year, structured_truck_specs)
from ..models import AttributeClaim, NormalizedListing
from ..vin import clean_vin, find_vins

CSV_COLUMNS = [
    "url", "vin", "year", "make", "model", "trim", "price", "miles", "seller_name", "seller_type", "city", "state",
    "zip", "exterior_color", "interior_color", "battery", "motor", "tonneau", "epa_range", "tow_capacity_lbs", "wheels",
    "in_service_date", "warranty_expiration", "title_status", "accident_history", "transport_cost", "description",
    "source",
]
_ALIASES = {
    "link": "url", "listing_url": "url", "listing url": "url", "price_usd": "price", "asking price": "price",
    "mileage": "miles", "odometer": "miles", "dealer": "seller_name", "seller": "seller_name", "color": "exterior_color",
    "exterior": "exterior_color", "notes": "description", "location": "city", "site": "source",
    "towing_capacity_lbs": "tow_capacity_lbs", "tow capacity": "tow_capacity_lbs", "range_miles": "epa_range",
}
USER_FIELDS = ["battery", "motor", "tonneau", "epa_range", "tow_capacity_lbs", "wheels", "in_service_date", "warranty_expiration",
               "title_status", "accident_history"]


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    s = str(value).strip()
    return s or None


def listing_from_fields(fields: dict, import_method: str = "manual", entered_by_user: bool = True) -> NormalizedListing:
    """Build a listing from user-provided fields. User-typed equipment values are recorded as listing claims
    ('Entered by user from listing'); use Vehicle Details → Verify to mark something as personally verified."""
    f = {(_ALIASES.get(k.strip().lower(), k.strip().lower())): _clean(v) for k, v in fields.items()}
    url = f.get("url")
    site, site_id = identify_site(url) if url else ((f.get("source") or "other"), None)
    if f.get("source") and not url:
        site = f["source"]
    vin = clean_vin(f.get("vin")) or None
    desc = f.get("description")
    detected_make, detected_model = parse_truck_identity(" ".join(f.get(k) or "" for k in ("make", "model", "title", "description")))
    make, model = f.get("make") or detected_make, f.get("model") or detected_model
    if not vin and desc:
        vins = find_vins(desc)
        vin = vins[0] if vins else None
    city, state, zip_code = f.get("city"), normalize_state(f.get("state")), f.get("zip")
    if city and not state:
        c2, s2, z2 = parse_location(city)
        if s2:
            city, state, zip_code = c2, s2, zip_code or z2
    method = "Entered by user from listing" if entered_by_user else f"Imported ({import_method})"
    attrs: list[AttributeClaim] = []
    for key in USER_FIELDS:
        val = f.get(key)
        if not val:
            continue
        if key == "tonneau":
            val = val if val in TONNEAU_STATUSES else _tonneau_from_text(val)
        if key in ("epa_range", "tow_capacity_lbs"):
            numeric = structured_truck_specs({key: val}, method)
            if not numeric:
                continue
            val = numeric[0].value
        attrs.append(AttributeClaim(key, val, "medium", method, evidence=f.get(key)))
    if desc:
        typed = {a.field for a in attrs}
        attrs += [a for a in extract_attributes(desc, "Parsed from pasted listing text", make=make, model=model)
                  if a.field not in typed]
    return NormalizedListing(
        source_key=site, import_method=import_method, source_listing_id=site_id, url=url, vin=vin,
        year=parse_int(f.get("year")) or parse_year(desc), make=make, model=model,
        trim=f.get("trim"), price=parse_int(f.get("price")) if f.get("price") else parse_price(desc),
        miles=parse_int(f.get("miles")) if f.get("miles") else parse_miles(desc),
        seller_name=f.get("seller_name"), seller_type=f.get("seller_type") or "unknown", city=city, state=state,
        zip=zip_code, exterior_color=f.get("exterior_color"), interior_color=f.get("interior_color"),
        transport_cost=parse_int(f.get("transport_cost")), title=f.get("title"), description=desc, attributes=attrs,
    )


def _tonneau_from_text(val: str) -> str:
    v = val.lower()
    if any(w in v for w in ("absent", "none", "no ", "without")) or v == "no":
        return "no"
    if any(w in v for w in ("yes", "power", "listed", "has")):
        return "yes"
    return "unknown"


def parse_csv(data: bytes | str) -> list[NormalizedListing]:
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    reader = csv.DictReader(io.StringIO(text))
    return [listing_from_fields(row, "csv", entered_by_user=False) for row in reader if any((v or "").strip() for v in row.values())]


def parse_json(data: bytes | str) -> list[NormalizedListing]:
    payload = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    rows = payload.get("listings", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("JSON must be a list of listing objects or {\"listings\": [...]}")
    return [listing_from_fields(r, "json", entered_by_user=False) for r in rows if isinstance(r, dict)]


def csv_template() -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    w.writerow({"url": "https://example.com/your-listing", "vin": "", "year": 2024, "make": "Rivian", "model": "R1T",
                "trim": "Adventure", "price": 59990, "miles": 18000, "seller_name": "Example Dealer",
                "seller_type": "dealer", "city": "Draper", "state": "UT", "zip": "84020",
                "exterior_color": "Launch Green", "battery": "Large", "motor": "Dual",
                "tonneau": "yes", "description": "Paste listing text here", "source": ""})
    return buf.getvalue()


def dedupe_key(nl: NormalizedListing) -> str:
    return nl.vin or canonical_url(nl.url) or f"{nl.year}-{nl.price}-{nl.miles}-{nl.seller_name}"
