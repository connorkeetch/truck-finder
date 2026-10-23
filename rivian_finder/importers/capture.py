"""Assisted capture: turn text the user copied from a listing page into a reviewable listing draft.

The user chooses what to copy (or highlights it before clicking the browser extension). This module only
parses that text; it never visits the page.
"""
from __future__ import annotations

import re
import sqlite3

from ..db import utcnow
from ..extract import (extract_attributes, identify_site, parse_location, parse_miles, parse_price,
                       parse_truck_identity, parse_year)
from ..models import NormalizedListing
from ..vin import find_vins

MAX_TEXT = 200_000
# Domains where even single-page assisted capture is disabled: copy details by hand instead.
BLOCKED_CAPTURE_DOMAINS = ("facebook.com", "messenger.com", "fb.com")


def capture_blocked(url: str | None) -> bool:
    host = re.sub(r"^https?://", "", (url or "").lower()).split("/")[0]
    return any(host == d or host.endswith("." + d) for d in BLOCKED_CAPTURE_DOMAINS)


def draft_from_text(text: str, url: str | None = None, title: str | None = None, image_url: str | None = None) -> dict:
    """Parse copied listing text into editable fields plus equipment claims with evidence."""
    text = (text or "")[:MAX_TEXT]
    blob = "\n".join(x for x in (title, text) if x)
    site, site_id = identify_site(url) if url else ("other", None)
    vins = find_vins(blob) or (find_vins(url) if url else [])
    city, state, zip_code = parse_location(blob)
    make, model = parse_truck_identity(title) if title else (None, None)
    if not model:
        make, model = parse_truck_identity(blob)
    seller = None
    m = re.search(r"(?i:sold by|seller|dealer(?:ship)?|offered by)\s*[:\-]?\s*([A-Z][\w&' \-]{2,50})", blob)
    if m:
        seller = m.group(1).strip()
    trim = None
    trim_names = {"Rivian": "Launch Edition|Adventure|Explore|Ascend",
                  "Ford": "Lariat|Platinum|XLT|Flash|Pro",
                  "Chevrolet": "Trail Boss|RST|WT|LT", "GMC": "Denali|Elevation|AT4"}
    m = re.search(r"\b(" + trim_names.get(make, "(?!)") + r")\b", blob, re.I)
    if m:
        trim = m.group(1).title()
    claims = extract_attributes(blob, "Parsed from text copied off the listing page", make=make, model=model)
    return {
        "url": url or "", "source": site, "source_listing_id": site_id, "vin": vins[0] if vins else "",
        "other_vins": vins[1:], "year": parse_year(blob), "make": make or "", "model": model or "", "trim": trim or "",
        "price": parse_price(blob), "miles": parse_miles(blob), "seller_name": seller or "", "city": city or "",
        "state": state or "", "zip": zip_code or "", "title": title or "", "description": text[:5000],
        "claims": claims, "photo_url": image_url if (image_url or "").startswith(("http://", "https://")) else "",
    }


def listing_from_draft(d: dict, import_method: str = "capture") -> NormalizedListing:
    return NormalizedListing(
        source_key=d.get("source") or "other", import_method=import_method,
        source_listing_id=d.get("source_listing_id") or None, url=d.get("url") or None, vin=d.get("vin") or None,
        year=d.get("year") or None, make=d.get("make") or None, model=d.get("model") or None,
        trim=d.get("trim") or None, price=d.get("price") or None, miles=d.get("miles"),
        seller_name=d.get("seller_name") or None, seller_type=d.get("seller_type") or "unknown",
        city=d.get("city") or None, state=d.get("state") or None, zip=d.get("zip") or None,
        title=d.get("title") or None, description=d.get("description") or None,
        exterior_color=d.get("exterior_color") or None, transport_cost=d.get("transport_cost"),
        photo_url=d.get("photo_url") or None,
        attributes=list(d.get("claims") or []),
    )


def enqueue(conn: sqlite3.Connection, origin: str, url: str | None, title: str | None, text: str | None,
            image_url: str | None = None) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO capture_queue(received_at, origin, url, title, text, image_url) VALUES (?,?,?,?,?,?)",
            (utcnow(), origin, (url or "")[:2000], (title or "")[:500], (text or "")[:MAX_TEXT],
             (image_url or "")[:2000] or None))
    return cur.lastrowid


def pending(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM capture_queue WHERE status='pending' ORDER BY id DESC").fetchall()


def resolve_capture(conn: sqlite3.Connection, capture_id: int, status: str, listing_id: int | None = None) -> None:
    with conn:
        conn.execute("UPDATE capture_queue SET status=?, listing_id=? WHERE id=?", (status, listing_id, capture_id))


def blank_draft_reason(d: dict) -> str | None:
    if not any((d.get("price"), d.get("vin"), d.get("miles"), d.get("year"))):
        return "Nothing recognizable was found. Select the listing details on the page (price, mileage, VIN) and capture again, or type them in."
    return None
