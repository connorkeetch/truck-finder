"""RivianForums classifieds: owner listings in the forum's "Rivians / Vehicles For Sale" section.

The forum's terms forbid automated access, so nothing here visits it. Listings arrive only from what the user brings:
the forum's own watched-forum notification emails, or a thread page copied and pasted (or highlighted and sent from
the browser extension).

Thread titles carry most of the facts, in the forum's own style:
    "Texas - For Sale: 2022 R1T El Cap Granite w/ Forest Edge Interior, 26k miles; $56k, PENDING"
Only the title and the first post are read. Replies often quote other trucks' prices and mileage.
"""
from __future__ import annotations

import re

from ..extract import normalize_state, parse_location, parse_miles, parse_price, parse_year

SITE = "rivianforums"
SELLER_SUFFIX = " (RivianForums)"

_STATE_PREFIX_RE = re.compile(r"^\s*([A-Za-z][A-Za-z .]{1,24}?)\s*[-–—:|]\s+")
_STATUS_PREFIX_RE = re.compile(r"^\s*(?:sold|pending|sale\s+pending|for\s+sale)\s*[:\-–—]\s*", re.I)
# "Looking for a quick sale" is a seller's phrase, so only buying phrases count.
_WANTED_RE = re.compile(r"\b(?:wtb|iso|wanted|want(?:ed)?\s+to\s+buy|looking\s+to\s+buy|in\s+search\s+of)\b", re.I)
_SOLD_RE = re.compile(r"\bsold\b(?!\s+by\b)", re.I)
_PENDING_RE = re.compile(r"\b(?:sale\s+)?pending\b", re.I)
_BARE_K_PRICE_RE = re.compile(r"(?<![\w$.,])(\d{2,3}(?:\.\d)?)\s*[kK]\b(?!\s*(?:mi\b|miles\b|mile\b))")
_POST_NUMBER_RE = re.compile(r"^\s*#(\d{1,4})\s*$", re.M)
_THREAD_STARTER_RE = re.compile(r"Thread starter\s+(.+?)(?:\s+Start date\b|\s*$)", re.M)
_LOCATION_LINE_RE = re.compile(r"^\s*Location\s*:?\s+(.+?)\s*$", re.M)
_PAGE_TITLE_SUFFIX_RE = re.compile(r"\s*[|–—-]\s*Rivian ?Forums?\b.*$", re.I)


def is_forum_url(url: str | None) -> bool:
    return bool(url) and "rivianforums.com" in url.lower()


def clean_title(title: str | None) -> str:
    """Browser tab titles end in ' | Rivian Forum – R1T R1S …'; keep just the thread title."""
    return _PAGE_TITLE_SUFFIX_RE.sub("", (title or "").strip()).strip()


def parse_title(title: str | None) -> dict:
    """Facts from a classified thread title. Missing facts are None."""
    t = clean_title(title)
    body = _STATUS_PREFIX_RE.sub("", t)          # "Sold: Texas 2025 R1T …" → "Texas 2025 R1T …"
    m = _STATE_PREFIX_RE.match(body)
    state = normalize_state(m.group(1)) if m else None
    words = body.split()
    for n in (3, 2, 1):                          # a spelled-out state leading the title without a separator
        if state:
            break
        name = " ".join(words[:n]).strip(" -:|,")
        state = normalize_state(name) if len(name) > 2 else None
    price = parse_price(t)
    if price is None:
        bare = _BARE_K_PRICE_RE.findall(t)
        if len(bare) == 1:                     # "For Sale: 64K - … 20,500 Miles"; two bare K numbers are ambiguous
            value = round(float(bare[0]) * 1000)
            price = value if 10_000 <= value <= 300_000 else None
    if _WANTED_RE.search(t):
        status = "wanted"
    elif _SOLD_RE.search(t):
        status = "sold"
    elif _PENDING_RE.search(t):
        status = "pending"
    else:
        status = None
    return {"title": t, "state": state, "year": parse_year(t), "price": price, "miles": parse_miles(t),
            "status": status}


def first_post(text: str) -> str:
    """The opening post of a copied thread page: after the '#1' post marker, up to '#2'."""
    text = text or ""
    markers = {int(m.group(1)): m for m in _POST_NUMBER_RE.finditer(text)}
    start = markers[1].end() if 1 in markers else 0
    following = [m.start() for n, m in markers.items() if n > 1 and m.start() > start]
    return text[start:min(following)].strip() if following else text[start:].strip()


def looks_like_title(line: str | None) -> bool:
    """A classified headline ("Texas - For Sale: 2022 R1T …") with a model year, price or WTB in it. Not a
    breadcrumb ("Rivians / Vehicles For Sale") or a button label ("View this thread")."""
    line = (line or "").strip()
    return 12 <= len(line) <= 200 and bool(parse_year(line) or parse_price(line) or _WANTED_RE.search(line))


def find_title(text: str) -> str | None:
    """The thread title from a copied page: the first line before the first post that reads like an ad."""
    head = text[:_first_marker(text)]
    return next((line.strip() for line in head.splitlines() if looks_like_title(line)), None)


def _first_marker(text: str) -> int:
    m = _POST_NUMBER_RE.search(text or "")
    return m.start() if m else len(text or "")


def thread_starter(text: str) -> str | None:
    m = _THREAD_STARTER_RE.search(text or "")
    return m.group(1).strip() if m else None


def refine_draft(draft: dict, page_text: str, title: str | None) -> dict:
    """Apply forum facts to a capture draft built from the first post. The title wins for price, miles and year:
    it is the seller's current asking price, while posts often mention the original MSRP."""
    facts = parse_title(title)
    head = (page_text or "")[:_first_marker(page_text or "")]
    starter = thread_starter(head)
    loc = _LOCATION_LINE_RE.search(head)
    city, state, zip_code = parse_location(loc.group(1)) if loc else (None, None, None)
    draft.update(
        source=SITE, seller_type="private", forum_status=facts["status"],
        title=facts["title"] or draft.get("title") or "",
        price=facts["price"] or draft.get("price"),
        miles=facts["miles"] if facts["miles"] is not None else draft.get("miles"),
        year=facts["year"] or draft.get("year"),
    )
    if starter:
        draft["seller_name"] = starter + SELLER_SUFFIX
    if not draft.get("state"):
        draft.update(city=draft.get("city") or city or "", state=state or facts["state"] or "",
                     zip=draft.get("zip") or zip_code or "")
    return draft


STATUS_NOTES = {
    "wanted": "This is a wanted-to-buy post, not a truck for sale.",
    "sold": "The thread is marked SOLD. If you save it, it's recorded as sold, which still helps price comparisons.",
    "pending": "The thread says the sale is pending.",
}
