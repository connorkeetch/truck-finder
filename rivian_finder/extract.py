"""Conservative parsing of listing text into structured fields.

Everything parsed from free text is a *claim* with low confidence and an evidence snippet. Nothing here
infers equipment from trim names or model years: a value is only produced when the text says it.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import US_STATES
from .models import AttributeClaim
from .vin import find_vins

# ------------------------------------------------------------------ numbers

_PRICE_RE = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})+|\d{4,6})(?:\.\d{2})?(?!\s*(?:/|per)\s*mo)", re.I)
_PRICE_K_RE = re.compile(r"\$\s*(\d{2,3}(?:\.\d)?)\s*[kK]\b")
_MILES_RE = re.compile(
    r"(?<![\d$,])(\d{1,3}(?:,\d{3})+|\d{1,6})\s*(?:k\s*)?(?:mi\b|miles\b|mileage\b)(?!\s*(?:of\s+)?range)", re.I
)
_MILES_LABEL_RE = re.compile(r"(?:mileage|odometer|miles)\s*[:\-]?\s*(\d{1,3}(?:,\d{3})+|\d{1,6})(\s*k\b)?", re.I)
_MILES_K_RE = re.compile(r"(?<![\d$])(\d{1,3}(?:\.\d)?)\s*k\s*(?:mi|miles)\b", re.I)


def parse_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d.]", "", str(value))
    if not digits:
        return None
    try:
        return int(float(digits))
    except ValueError:
        return None


def parse_price(text: str | None) -> int | None:
    """First plausible vehicle price in text ($5k–$250k). Ignores '/mo' payment figures."""
    if not text:
        return None
    for m in _PRICE_RE.finditer(text):
        val = parse_int(m.group(1))
        if val and 5000 <= val <= 250000:
            return val
    m = _PRICE_K_RE.search(text)
    if m:
        val = int(float(m.group(1)) * 1000)
        if 5000 <= val <= 250000:
            return val
    if re.fullmatch(r"\s*\d{4,6}\s*", text or ""):
        return parse_int(text)
    return None


def parse_miles(text: str | None) -> int | None:
    """Odometer mileage. Skips 'miles of range' style phrases."""
    if not text:
        return None
    m = _MILES_LABEL_RE.search(text)
    if m:
        val = parse_int(m.group(1))
        if m.group(2):
            val = int(float(m.group(1).replace(",", "")) * 1000)
        if val is not None and val < 500000:
            return val
    m = _MILES_K_RE.search(text)
    if m:
        return int(float(m.group(1)) * 1000)
    for m in _MILES_RE.finditer(text):
        tail = text[m.end(): m.end() + 20].lower()
        if re.match(r"\s*(?:(?:of\s+)?(?:electric\s+)?range|away|from)\b", tail):
            continue
        if any(r.start() <= m.start() < r.end() for r in _RANGE_RE.finditer(text)):
            continue
        head = text[max(0, m.start() - 16): m.start()].lower()
        if re.search(r"(?:range|epa(?:\s*est(?:imated|\.)?)?)\s*(?:\(epa\))?\s*[:\-]?\s*$", head):
            continue
        val = parse_int(m.group(1))
        if val is not None and val < 500000:
            return val
    if re.fullmatch(r"\s*\d{1,6}\s*", text or ""):
        return parse_int(text)
    return None


def parse_year(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"\b((?:19|20)\d{2})\s+(?:rivian|r1t)\b", text, re.I) or re.search(r"\b((?:19|20)\d{2})\b", text)
    return int(m.group(1)) if m else None


_TRUCK_IDENTITIES = [
    ("Rivian", "R1T", re.compile(r"\br1t\b", re.I)),
    ("Ford", "F-150 Lightning", re.compile(r"\bf[\s\-–]*150[\s\-]+lightning\b", re.I)),
    ("Chevrolet", "Silverado EV", re.compile(r"\bsilverado[\s\-]+ev\b", re.I)),
    ("GMC", "Sierra EV", re.compile(r"\bsierra[\s\-]+ev\b", re.I)),
]


def parse_truck_identity(text: str | None) -> tuple[str | None, str | None]:
    """Recognize the supported electric pickups; a plain F-150/Silverado/Sierra is not an EV."""
    matches = [(m.start(), make, model) for make, model, pat in _TRUCK_IDENTITIES
               if (m := pat.search(text or ""))]
    if not matches:
        return None, None
    _, make, model = min(matches)
    return make, model


# ------------------------------------------------------------------ equipment

def _snippet(text: str, m: re.Match, width: int = 60) -> str:
    start, end = max(0, m.start() - width), min(len(text), m.end() + width)
    return ("…" if start else "") + text[start:end].replace("\n", " ").strip() + ("…" if end < len(text) else "")


_CONFIG = r"\b(?:quad|tri|dual)(?:[\s\-]*motor)?[\s,\-]+"   # Rivian config names: "Dual Large", "Tri Max"
_BATTERY_PATTERNS = [
    ("Max", re.compile(r"\bmax(?:imum)?[\s\-]*(?:range\s*)?(?:battery\s*)?pack\b|\bmax\s+battery\b|\bmax\s+range\s+battery\b"
                       + "|" + _CONFIG + r"max\b", re.I)),
    ("Large+", re.compile(r"\blarge\s*(?:\+|plus\b)", re.I)),
    ("Large", re.compile(r"\blarge[\s\-]*(?:battery\s*)?pack\b|\blarge\s+battery\b|" + _CONFIG + r"large\b(?!\s*(?:\+|plus))",
                         re.I)),
    ("Standard+", re.compile(r"\bstandard\s*(?:\+|plus\b)", re.I)),
    ("Standard", re.compile(r"\bstandard[\s\-]*(?:battery\s*)?pack\b|\bstandard\s+battery\b|" + _CONFIG + r"standard\b(?!\s*(?:\+|plus))",
                            re.I)),
]

_MOTOR_PATTERNS = [
    ("Quad", re.compile(r"\bquad[\s\-]*motor\b|\bquad[\s\-]*motor\s+awd\b|\bquad\b(?=[^.\n]{0,20}\b(?:awd|motor|drive))"
                        r"|\bquad(?=[\s\-]+(?:max|large|standard)\b)", re.I)),
    ("Tri", re.compile(r"\btri[\s\-]*motor\b|\btri(?=[\s\-]+(?:max|large|standard)\b)", re.I)),
    ("Performance Dual", re.compile(
        r"\bperformance\s+dual(?:[\s\-]*motor)?\b|\bdual[\s\-]*motor\s+performance\b|\bdual\s+performance\b"
        r"|\bperformance\s+upgrade\b", re.I)),
    ("Dual", re.compile(r"\bdual[\s\-]*motor\b|\bdual(?=[\s\-]+(?:max|large|standard)\b)", re.I)),
]

_TONNEAU_POWERED = re.compile(
    r"\b(?:powered|power|electric|motori[sz]ed|automatic|retractable)[\s\-]+(?:bed\s+)?tonneau\b"
    r"|\btonneau\s+cover\s*\((?:powered|power|electric)\)|\bpowered\s+bed\s+cover\b", re.I)
_TONNEAU_NEGATIVE = re.compile(
    r"\b(?:no|without|w/o|lacks|missing|not\s+equipped\s+with(?:\s+a)?|does\s+not\s+(?:have|include|come\s+with))"
    r"\s+(?:a\s+|the\s+)?(?:powered\s+|power\s+)?tonneau\b", re.I)
# Rivian's manual / soft covers are a different accessory: a truck with one doesn't have the powered tonneau.
_TONNEAU_MANUAL = re.compile(r"\b(?:manual|soft|roll[\s\-]?up|tri[\s\-]?fold|folding)\s+(?:\w+\s+)?tonneau\b", re.I)
_TONNEAU_BROKEN = re.compile(
    r"\btonneau[^.\n]{0,40}\b(?:inoperable|not\s+working|doesn'?t\s+work|broken|needs\s+repair|faulty)\b", re.I)
_TONNEAU_ANY = re.compile(r"\btonneau\b", re.I)

_RANGE_RE = re.compile(
    r"\b(?:epa|gm)[\s\-]*(?:est(?:imated|\.)?)?\s*(?:electric\s+)?(?:range\s*)?(?:of|:)?\s*(?:up\s+to\s*)?"
    r"(\d{3})\s*(?:mi|miles)\b"
    r"|\b(\d{3})[\s\-]*(?:mi|mile|miles)\s+(?:of\s+)?(?:all[\s\-]*electric\s+|electric\s+)?"
    r"(?:epa\s+)?(?:est(?:imated|\.)?\s+)?range\b"
    r"|\b(?:electric\s+|driving\s+)?range\s*(?:\(epa\))?\s*(?:[:\-]|of|up\s+to)\s*(\d{3})\s*(?:mi|miles)?\b", re.I)
_TOW_NUMBER = r"(\d{1,2},\d{3}|\d{4,5}|\d{1,2}(?:\.\d)?\s*k)"
_TOW_UNIT = r"(?:lbs?\.?|pounds?)\b"
_TOW_RE = re.compile(
    r"\b(?:max(?:imum)?\s+)?(?:conventional\s+)?(?:towing|tows?|trailering)(?:\s+(?:capacity|rating))?"
    r"\s*(?:is|of|:|=)?\s*(?:up\s+to\s*)?" + _TOW_NUMBER + r"\s*[\-]?\s*" + _TOW_UNIT
    + r"|\b" + _TOW_NUMBER + r"\s*[\-]?\s*" + _TOW_UNIT
    + r"\s+(?:max(?:imum)?\s+)?(?:conventional\s+)?(?:towing|tow|trailering)(?:\s+(?:capacity|rating))?\b", re.I)
_NON_RIVIAN_BATTERY = re.compile(r"\b(standard|extended|max)[\s\-]+range(?:\s+battery(?:\s+pack)?)?\b", re.I)


def _unsupported_rating(text: str, match: re.Match, *, towing: bool = False) -> bool:
    """Ignore negated ratings, charging increments, and equipment-dependent marketing copy."""
    start = max(text.rfind(";", 0, match.start()), text.rfind("\n", 0, match.start()),
                text.rfind(". ", 0, match.start())) + 1
    end = re.search(r"[;\n]|\.\s", text[match.end():])
    sentence = text[start:match.end() + end.start() if end else len(text)].lower()
    head = text[max(start, match.start() - 45):match.start()].lower()
    if re.search(r"\b(?:no|not|without|does\s+not|cannot|can.t)\s+(?:\w+\s+){0,3}$", head):
        return True
    if re.search(r"\b(?:if|when)\s+(?:properly\s+)?equipped\b|\bwith\s+(?:the\s+)?(?:optional|available)\b", sentence):
        return True
    tail = text[match.end():min(len(text), match.end() + 60)].lower()
    if re.match(r"\s*[\-–/]\s*\d", tail):
        return True
    return not towing and bool(re.search(r"\b(?:while\s+towing|when\s+towing|with\s+(?:a\s+)?trailer)\b", sentence)
                               or re.match(r"\s+(?:added\s+)?(?:in|per)\s+(?:approximately\s+)?\d+\s*(?:min|hour)", tail)
                               or re.search(r"\b(?:charg(?:e|ing)|adds?|gains?)\s+(?:up\s+to\s+)?$", head))


def _rating_int(raw: str) -> int:
    return int(float(raw.lower().replace(",", "").replace("k", "").strip()) * (1000 if "k" in raw.lower() else 1))


def structured_truck_specs(fields: dict, method: str) -> list[AttributeClaim]:
    """Read explicitly named, unit-specific provider fields; do not derive ratings from model names."""
    aliases = {
        "eparange": ("epa_range", 150, 600), "eparangemiles": ("epa_range", 150, 600),
        "electricrangemiles": ("epa_range", 150, 600), "rangemiles": ("epa_range", 150, 600),
        "towcapacitylbs": ("tow_capacity_lbs", 1000, 30000),
        "towingcapacitylbs": ("tow_capacity_lbs", 1000, 30000),
        "maxtowingcapacitylbs": ("tow_capacity_lbs", 1000, 30000),
        "maxtraileringcapacitylbs": ("tow_capacity_lbs", 1000, 30000),
    }
    claims = []
    for key, raw in fields.items():
        spec = aliases.get(re.sub(r"[^a-z0-9]", "", str(key).lower()))
        if not spec or raw is None or isinstance(raw, bool):
            continue
        field, low, high = spec
        unit = r"(?:mi|miles)?" if field == "epa_range" else r"(?:lbs?\.?|pounds?)?"
        m = re.fullmatch(r"\s*(\d{1,3}(?:,\d{3})+|\d{1,5})(?:\.0)?\s*" + unit + r"\s*", str(raw), re.I)
        if m and low <= (value := int(m.group(1).replace(",", ""))) <= high:
            claims.append(AttributeClaim(field, str(value), "medium", method, evidence=f"{key}: {raw}"))
    return claims
_WHEELS_RE = re.compile(r"\b(20|21|22)(?:\"|”|''|-inch|\s*inch|\s*in\.?)\s*([A-Za-z][A-Za-z\- ]{0,25}?)?\s*(?:wheels?|rims?)\b", re.I)
_IN_SERVICE_RE = re.compile(
    r"(?:in[\s\-]*service|warranty\s+start)(?:\s+date)?\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})", re.I)
_WARRANTY_EXP_RE = re.compile(
    r"(?:limited\s+|comprehensive\s+|bumper[\s\-]*to[\s\-]*bumper\s+)?warranty\s+"
    r"(?:expires|expiration|until|through|good\s+until|valid\s+until)\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
    re.I)

RIVIAN_COLORS = [
    "Launch Green", "Rivian Blue", "Limestone", "Forest Green", "Glacier White", "El Cap Granite",
    "Red Canyon", "Midnight", "LA Silver", "Compass Yellow", "Storm Blue", "Borealis", "Half Moon Grey",
    "Monterey Coast",
]
_COLOR_RES = [(c, re.compile(r"\b" + re.escape(c).replace(r"\ ", r"\s+") + r"\b", re.I)) for c in RIVIAN_COLORS]


def _date_iso(raw: str) -> str | None:
    raw = raw.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return raw
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw)
    if not m:
        return None
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                          "dec"], start=1)}
_WARRANTY_LINE = re.compile(
    r"(comprehensive|bumper[\s\-]*to[\s\-]*bumper|new vehicle limited|battery(?:\s*pack)?(?:\s*(?:&|and)\s*drive\s*(?:train|unit))?"
    r"|drive\s*(?:train|unit))[^\d]{0,40}?"
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}|\d{1,2}/\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}(?:-\d{2})?)"
    r"\s*(?:or|/|,|-)?\s*(\d{1,3}(?:,\d{3})+|\d{1,3})\s*(k)?\s*(?:mi|miles)\b", re.I | re.S)


def _warranty_date(raw: str) -> str | None:
    raw = raw.strip().lower().rstrip(".")
    m = re.fullmatch(r"([a-z]{3})[a-z]*\.?\s+(\d{4})", raw)
    if m and m.group(1) in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1)]:02d}-01"
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", raw)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}-01"
    return _date_iso(raw)


def parse_warranty(text: str | None) -> dict:
    """'Comprehensive Apr 2028 or 60k mi · Battery pack & drivetrain Apr 2031 or 175k mi' -> dates and mile caps."""
    out: dict = {}
    for m in _WARRANTY_LINE.finditer(text or ""):
        kind = "battery" if re.search(r"battery|drive", m.group(1), re.I) else "comprehensive"
        when = _warranty_date(m.group(2))
        miles = int(m.group(3).replace(",", "")) * (1000 if m.group(4) else 1)
        if miles < 1000:
            miles *= 1000            # "60 mi" style typo: assume thousands
        if not when:
            continue
        if kind == "comprehensive" and "warranty_expiration" not in out:
            out.update(warranty_expiration=when, warranty_miles=miles)
        elif kind == "battery" and "battery_warranty_expiration" not in out:
            out.update(battery_warranty_expiration=when, battery_warranty_miles=miles)
    return out


def classify_tonneau(text: str | None, structured: bool = False) -> tuple[str, str | None, str]:
    """Return (status, evidence, confidence) for the powered tonneau cover: 'yes', 'no' or 'unknown'."""
    if not text:
        return "unknown", None, "low"
    m = _TONNEAU_NEGATIVE.search(text)
    if m:
        return "no", _snippet(text, m), "low"
    m = _TONNEAU_MANUAL.search(text)
    if m and not _TONNEAU_POWERED.search(text):
        return "no", "Manual (not powered) tonneau: " + _snippet(text, m), "low"
    m = _TONNEAU_BROKEN.search(text)
    if m:
        return "yes", "Listed but reported not working: " + _snippet(text, m), "low"
    m = _TONNEAU_POWERED.search(text)
    if m:
        return "yes", _snippet(text, m), "medium" if structured else "low"
    return "unknown", None, "low"


# Classified sites (KSL and others) show the title as a labeled field: "Title Type: Rebuilt/Reconstructed".
_BRANDED_TITLE_LABEL_RE = re.compile(
    r"\btitle\s*(?:type|status|brand)?\s*[:\-]?\s*(?:rebuilt|reconstructed|salvage|branded|lemon|flood|buyback|junk)\b",
    re.I)
_CLEAN_TITLE_LABEL_RE = re.compile(r"\btitle\s*(?:type|status)?\s*[:\-]?\s*clean\b", re.I)
_PRIVATE_SELLER_RE = re.compile(
    r"\bfor\s+sale\s+by\s+owner\b|\bfsbo\b|\bprivate\s+(?:seller|party)\b"
    r"|\bseller\s*type\s*[:\-]?\s*(?:private|owner|individual)\b", re.I)
_DEALER_SELLER_RE = re.compile(r"\bseller\s*type\s*[:\-]?\s*(?:dealer|dealership|business)\b|\bdealer\s+licen[cs]e\b",
                               re.I)


def parse_seller_type(text: str | None) -> str | None:
    """'private' or 'dealer' when the listing says so ("For Sale By Owner", "Seller Type: Dealer"), else None.
    Only explicit wording counts: private ads often mention a dealer ("dealer serviced")."""
    hits = [(m.start(), kind) for kind, pat in (("private", _PRIVATE_SELLER_RE), ("dealer", _DEALER_SELLER_RE))
            if (m := pat.search(text or ""))]
    return min(hits)[1] if hits else None


def extract_attributes(text: str | None, method: str, confidence: str = "low",
                       structured: bool = False, make: str | None = None,
                       model: str | None = None) -> list[AttributeClaim]:
    """Pull equipment claims out of a block of listing text."""
    if not text:
        return []
    claims: list[AttributeClaim] = []
    detected_make, _ = parse_truck_identity(f"{make or ''} {model or ''} {text}")
    rivian = (make or detected_make or "Rivian").lower() == "rivian"

    # Free text: the first (biggest) pack named. Structured fields: every pack named, so a listing that
    # contradicts itself ("Dual Standard" trim, "Max Pack" spec) shows up as uncertain instead of picking one.
    for value, pat in _BATTERY_PATTERNS if rivian else []:
        m = pat.search(text)
        if m:
            claims.append(AttributeClaim("battery", value, confidence, method, evidence=_snippet(text, m)))
            if not structured:
                break
    if not rivian:
        for m in _NON_RIVIAN_BATTERY.finditer(text):
            claims.append(AttributeClaim("battery", f"{m.group(1).title()} Range", confidence, method,
                                         evidence=_snippet(text, m)))
            if not structured:
                break
    for value, pat in _MOTOR_PATTERNS:
        m = pat.search(text)
        if m:
            claims.append(AttributeClaim("motor", value, confidence, method, evidence=_snippet(text, m)))
            break

    status, evidence, t_conf = classify_tonneau(text, structured=structured)
    if status != "unknown":
        claims.append(AttributeClaim("tonneau", status, t_conf, method, evidence=evidence))
    else:
        m = _TONNEAU_ANY.search(text)
        if m:
            # A tonneau is mentioned but not clearly powered: record the evidence, keep status unknown.
            claims.append(AttributeClaim("tonneau_mention", "mentioned (type unclear)", "low", method,
                                         evidence=_snippet(text, m)))

    for m in _RANGE_RE.finditer(text):
        rng = next(g for g in m.groups() if g)
        if 150 <= int(rng) <= 600 and not _unsupported_rating(text, m):
            claims.append(AttributeClaim("epa_range", rng, confidence, method, evidence=_snippet(text, m)))
    for m in _TOW_RE.finditer(text):
        tow = _rating_int(next(g for g in m.groups() if g))
        if 1000 <= tow <= 30000 and not _unsupported_rating(text, m, towing=True):
            claims.append(AttributeClaim("tow_capacity_lbs", str(tow), confidence, method,
                                         evidence=_snippet(text, m)))
    m = _WHEELS_RE.search(text)
    if m:
        style = (m.group(2) or "").strip().title()
        value = f'{m.group(1)}" {style}'.strip()
        claims.append(AttributeClaim("wheels", value, confidence, method, evidence=_snippet(text, m)))
    m = _IN_SERVICE_RE.search(text)
    if m and _date_iso(m.group(1)):
        claims.append(AttributeClaim("in_service_date", _date_iso(m.group(1)), confidence, method,
                                     evidence=_snippet(text, m)))
    for field, value in parse_warranty(text).items():
        claims.append(AttributeClaim(field, str(value), confidence, method, evidence="warranty text"))
    m = _WARRANTY_EXP_RE.search(text)
    if m and _date_iso(m.group(1)) and not any(c.field == "warranty_expiration" for c in claims):
        claims.append(AttributeClaim("warranty_expiration", _date_iso(m.group(1)), confidence, method,
                                     evidence=_snippet(text, m)))

    m = (re.search(r"\b(?:salvage|rebuilt|reconstructed|branded|flood|lemon)\s+title\b", text, re.I)
         or _BRANDED_TITLE_LABEL_RE.search(text))
    if m:
        claims.append(AttributeClaim("title_status", "branded", confidence, method, evidence=_snippet(text, m)))
    else:
        m = (re.search(r"\bclean\s+(?:carfax\s+|autocheck\s+)?title\b", text, re.I)
             or _CLEAN_TITLE_LABEL_RE.search(text))
        if m:
            claims.append(AttributeClaim("title_status", "clean", confidence, method, evidence=_snippet(text, m)))
    m = re.search(r"\b(?:no|zero|0)\s+(?:reported\s+)?accidents?(?:\s+reported)?\b|\baccident[\s\-]free\b", text, re.I)
    if m:
        claims.append(AttributeClaim("accident_history", "none_reported", confidence, method,
                                     evidence=_snippet(text, m)))
    else:
        m = re.search(r"\b(?:[1-9]|one|two)\s+accidents?\s*(?:reported)?\b|\baccident\s+reported\b"
                      r"|\b(?:minor|moderate|severe)\s+damage\s+reported\b", text, re.I)
        if m:
            claims.append(AttributeClaim("accident_history", "reported", confidence, method,
                                         evidence=_snippet(text, m)))
    for color, pat in _COLOR_RES if rivian else []:
        m = pat.search(text)
        if m:
            claims.append(AttributeClaim("exterior_color", color, confidence, method, evidence=_snippet(text, m)))
            break
    return claims


# ------------------------------------------------------------------ location / misc

_CITY_STATE_ZIP_RE = re.compile(r"\b([A-Z][a-zA-Z.\- ]{1,30}),\s*(" + "|".join(US_STATES) + r")\b(?:\s+(\d{5}))?")
_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "washington dc": "DC", "florida": "FL",
    "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY",
}


def parse_location(text: str | None) -> tuple[str | None, str | None, str | None]:
    """(city, state, zip) from text like 'Draper, UT 84020'."""
    if not text:
        return None, None, None
    m = _CITY_STATE_ZIP_RE.search(text)
    if m:
        city = m.group(1).strip()
        city = re.sub(r"^(?:in|near|located in|location:?)\s+", "", city, flags=re.I)
        return city, m.group(2), m.group(3)
    return None, None, None


def normalize_state(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if v.upper() in US_STATES:
        return v.upper()
    return _STATE_NAMES.get(v.lower())


_TRACKING_PARAMS = re.compile(r"^(utm_|gclid|fbclid|mc_|cid$|clickid|ref$|referrer|trk|_hs|mkt_tok)", re.I)


def canonical_url(url: str | None) -> str | None:
    """Lowercase host, drop tracking parameters and cosmetic fragments so the same listing compares equal.
    Fragments that identify the listing (#vin=…, #listing=…) are kept: some sites put the only ID there."""
    if not url:
        return None
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        return None
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING_PARAMS.match(k)]
    path = parts.path.rstrip("/") or "/"
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    frag = parts.fragment if re.search(r"(?:^|[&#])(?:vin|listing|listingid|id)=", parts.fragment, re.I) else ""
    return urlunsplit(("https", host, path, urlencode(query), frag))


SITE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("autotrader", re.compile(r"autotrader\.com/.*?(?:vehicle/|listingId=|/vehicledetails\.xhtml\?.*?listingId=)(\d{6,})", re.I)),
    ("cars_com", re.compile(r"cars\.com/vehicledetail/([a-z0-9\-]{6,})", re.I)),
    ("cargurus", re.compile(r"cargurus\.com/.*?(?:#listing=|listing=|/details/)(\d{6,})", re.I)),
    ("carmax", re.compile(r"carmax\.com/car/(\d{6,})", re.I)),
    ("carvana", re.compile(r"carvana\.com/vehicle/(\d{5,})", re.I)),
    ("ksl", re.compile(r"(?:cars|classifieds)\.ksl\.com/(?:v2/)?listing/(\d{4,})", re.I)),
    ("facebook", re.compile(r"facebook\.com/marketplace/item/(\d{6,})", re.I)),
    ("truecar", re.compile(r"truecar\.com/used-cars-for-sale/listing/([A-HJ-NPR-Z0-9]{17})", re.I)),
    ("rivian", re.compile(r"rivian\.com/.*?(?:configurations|pre-owned|inventory|r1t)[^\s\"']*?([A-HJ-NPR-Z0-9]{17})?", re.I)),
    ("autotempest", re.compile(r"autotempest\.com/(?:details|listing)/([^\s/?\"']+)", re.I)),
    # XenForo thread links: /forum/threads/<slug>.<id>/ with optional /post-<n>, /unread, /page-<n> after it
    ("rivianforums", re.compile(r"rivianforums\.com/(?:forum/)?threads/(?:[^/?#\s\"']*\.)?(\d{3,})", re.I)),
    ("roamer", re.compile(r"rivianroamer\.com/inventory/([A-Za-z0-9\-]{4,})", re.I)),
]

SITE_DOMAINS = {
    "autotrader": "autotrader.com", "cars_com": "cars.com", "cargurus": "cargurus.com", "carmax": "carmax.com",
    "carvana": "carvana.com", "ksl": "ksl.com", "facebook": "facebook.com", "truecar": "truecar.com",
    "rivian": "rivian.com", "autotempest": "autotempest.com", "rivianforums": "rivianforums.com",
    "roamer": "rivianroamer.com",
}


def identify_site(url: str | None) -> tuple[str, str | None]:
    """(source_key, listing id or None) for a listing URL. Unknown hosts are 'dealer'."""
    if not url:
        return "other", None
    for key, pat in SITE_PATTERNS:
        m = pat.search(url)
        if m:
            return key, (m.group(1) if m.groups() and m.group(1) else None)
    host = urlsplit(url).netloc.lower()
    for key, domain in SITE_DOMAINS.items():
        if host.endswith(domain):
            return key, None
    vins = find_vins(url)
    return "dealer", (vins[0] if vins else None)
