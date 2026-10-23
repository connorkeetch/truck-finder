"""Trim families shared by collection exclusions and local inventory filters."""
from __future__ import annotations

import re


def trim_name(make: str | None, model: str | None, trim: str | None) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", (trim or "").lower()).strip()
    vehicle = re.sub(r"[^a-z0-9]", "", (model or "").lower())
    brand = (make or "").lower()
    if brand == "ford" and vehicle == "f150lightning":
        text = re.sub(r"^(?:ford )?(?:f ?150 lightning )?", "", text)
        match = re.match(r"(pro|xlt|flash|lariat|platinum)\b", text)
        if match and not text.startswith("pro power"):
            return {"pro": "Pro", "xlt": "XLT", "flash": "Flash", "lariat": "Lariat", "platinum": "Platinum"}[match[1]]
    elif brand == "chevrolet" and vehicle == "silveradoev":
        if re.search(r"\b(?:[1-9]?wt|work\s*truck)\b", text):
            return "WT"
        for name, pattern in (("RST", r"\brst\b"), ("Trail Boss", r"\btrail\s*boss\b"), ("LT", r"\b[1-9]?lt\b")):
            if re.search(pattern, text):
                return name
    elif brand == "gmc" and vehicle == "sierraev":
        for name in ("Denali", "Elevation", "AT4"):
            if re.search(r"\b" + name.lower() + r"\b", text):
                return name
    return (trim or "").strip() or "Unknown"


def trim_label(make: str | None, model: str | None, trim: str | None) -> str:
    brand = {"ford": "Ford", "chevrolet": "Chevrolet", "gmc": "GMC", "rivian": "Rivian"}.get(
        (make or "").lower(), make or "Unknown brand")
    return f"{brand} · {trim_name(make, model, trim)}"


def excluded_trim(make: str | None, model: str | None, trim: str | None, exclusions: dict | None) -> bool:
    expected = {"ford": "f150lightning", "chevrolet": "silveradoev"}.get((make or "").lower())
    if not expected or re.sub(r"[^a-z0-9]", "", (model or "").lower()) != expected:
        return False
    blocked = next((values for brand, values in (exclusions or {}).items()
                    if brand.lower() == (make or "").lower()), [])
    return trim_name(make, model, trim).lower() in {value.lower() for value in blocked}


def standard_range(make: str | None, model: str | None, *texts: str | None) -> bool:
    """Explicit range-package labels, scoped to the competing EV pickups."""
    expected = {"ford": "f150lightning", "chevrolet": "silveradoev", "gmc": "sierraev"}.get((make or "").lower())
    if not expected or re.sub(r"[^a-z0-9]", "", (model or "").lower()) != expected:
        return False
    return any(re.search(r"\bstandard[\W_]*range\b", text, re.I)
               for text in texts if isinstance(text, str))
