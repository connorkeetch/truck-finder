"""Parse saved-search alert emails (.eml files or pasted content) into candidate listings.

Works from what the email itself contains: listing links plus the text around them. Tracking redirect links are
unwrapped only when the destination is embedded in the link; nothing is fetched from the network.
"""
from __future__ import annotations

import email
import re
from email import policy
from email.message import EmailMessage
from urllib.parse import parse_qsl, unquote, urlsplit

from bs4 import BeautifulSoup

from ..extract import (SITE_DOMAINS, canonical_url, extract_attributes, identify_site, parse_location, parse_miles,
                       parse_price, parse_truck_identity, parse_year)
from ..models import NormalizedListing
from ..vin import find_vins

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_REDIRECT_KEYS = ("url", "u", "redirect", "redirect_url", "target", "dest", "destination", "link", "r", "goto")
SENDER_SITES = {
    "autotrader": "autotrader", "cars.com": "cars_com", "cargurus": "cargurus", "carmax": "carmax",
    "carvana": "carvana", "ksl": "ksl", "rivian": "rivian", "autotempest": "autotempest", "truecar": "truecar",
    "facebook": "facebook", "facebookmail": "facebook",
}


def unwrap_url(url: str, depth: int = 0) -> str:
    """Return the destination embedded in a tracking/redirect URL, if any."""
    if depth > 3:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    for k, v in parse_qsl(parts.query, keep_blank_values=False):
        if k.lower() in _REDIRECT_KEYS:
            cand = unquote(v)
            if cand.lower().startswith(("http://", "https://")):
                return unwrap_url(cand, depth + 1)
    m = re.search(r"(https?%3A%2F%2F[^&\s]+)", url, re.I)
    if m:
        return unwrap_url(unquote(m.group(1)), depth + 1)
    return url


def _dedupe_key(url: str) -> str:
    """Photo, title and 'view' links for one listing often differ only in query strings."""
    site, listing_id = identify_site(url)
    return f"{site}:{listing_id}" if listing_id else (canonical_url(url) or url)


def _is_listing_url(url: str) -> bool:
    site, listing_id = identify_site(url)
    if listing_id:
        return True
    return bool(find_vins(url))


def read_eml(data: bytes) -> dict:
    msg: EmailMessage = email.message_from_bytes(data, policy=policy.default)  # type: ignore[assignment]
    html = text = None
    for part in msg.walk():
        ctype = part.get_content_type()
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError):
            content = part.get_payload(decode=True).decode("utf-8", "replace")
        if ctype == "text/html" and html is None:
            html = content
        elif ctype == "text/plain" and text is None:
            text = content
    return {"subject": str(msg.get("Subject", "")), "from": str(msg.get("From", "")), "date": str(msg.get("Date", "")),
            "html": html, "text": text}


def _sender_site(sender: str) -> str | None:
    s = sender.lower()
    for needle, key in SENDER_SITES.items():
        if needle in s:
            return key
    return None


def _card(tag):
    """(text, node) of the smallest ancestor that looks like a whole listing card."""
    node, best, best_node = tag, tag.get_text(" ", strip=True), tag
    for _ in range(8):
        node = node.parent
        if node is None or node.name in ("body", "html", "[document]"):
            break
        txt = node.get_text(" ", strip=True)
        if len(txt) > 1200:
            break
        best, best_node = txt, node
        if parse_price(txt) and (parse_miles(txt) is not None or parse_year(txt)):
            if node.name in ("td", "tr", "table", "div", "li", "article", "section"):
                break
    return best, best_node


def _block_text(tag) -> str:
    return _card(tag)[0]


_NOT_PHOTO = re.compile(r"logo|pixel|spacer|beacon|track|icon|badge|open\.|1x1", re.I)


def card_photo(node) -> str | None:
    """First image in a listing card that looks like a vehicle photo (not a logo or tracking pixel)."""
    for img in node.find_all("img") if hasattr(node, "find_all") else []:
        src = (img.get("src") or "").strip()
        if not src.lower().startswith(("http://", "https://")) or _NOT_PHOTO.search(src):
            continue
        try:
            if int(img.get("width") or 100) < 60 or int(img.get("height") or 100) < 40:
                continue
        except ValueError:
            pass
        return src
    return None


def _candidate(url: str, block: str, sender_site: str | None, subject: str) -> NormalizedListing:
    site, listing_id = identify_site(url)
    if site in ("dealer", "other") and sender_site:
        site = sender_site if sender_site not in ("autotempest",) else site
    vins = find_vins(block) or find_vins(url)
    city, state, zip_code = parse_location(block)
    seller = None
    if city and state:
        m = re.search(r"([A-Z][\w&'.\- ]{2,40}?)\s*[·•|]\s*" + re.escape(city) + r",\s*" + state, block)
        if m:
            seller = m.group(1).strip()
    make, model = parse_truck_identity(block)
    title_m = re.search(r"\b20\d{2}\s+(?:(?:Rivian\s+)?R1T|(?:Ford\s+)?F[\s\-]*150\s+Lightning"
                        r"|(?:(?:Chevrolet|Chevy)\s+)?Silverado\s+EV|(?:GMC\s+)?Sierra\s+EV)[^$\n|•]{0,40}", block, re.I)
    return NormalizedListing(
        source_key=site, import_method="email", source_listing_id=listing_id, url=url,
        vin=vins[0] if vins else None, year=parse_year(block), make=make,
        model=model, price=parse_price(block),
        miles=parse_miles(block), city=city, state=state, zip=zip_code, seller_name=seller,
        title=title_m.group(0).strip() if title_m else None, description=block[:2000],
        attributes=extract_attributes(block, f"Parsed from {site} alert email" + (f" ({subject[:60]})" if subject else ""),
                                      make=make, model=model),
    )


def parse_alert(html: str | None = None, text: str | None = None, sender: str = "", subject: str = "") -> list[NormalizedListing]:
    """Extract listing candidates from an alert email body (HTML preferred)."""
    sender_site = _sender_site(sender)
    found: dict[str, NormalizedListing] = {}
    if html:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            url = unwrap_url(a["href"].strip())
            if not _is_listing_url(url):
                continue
            key = _dedupe_key(url)
            block, node = _card(a)
            cand = _candidate(url, block, sender_site, subject)
            cand.photo_url = card_photo(node)
            prev = found.get(key)
            # several links (photo, title, "view") usually point at one listing; keep the richest block
            if prev is None or len(cand.description or "") > len(prev.description or ""):
                cand.photo_url = cand.photo_url or (prev.photo_url if prev else None)
                found[key] = cand
            elif not prev.photo_url and cand.photo_url:
                prev.photo_url = cand.photo_url
    if text and not found:
        # Plain text: a listing's details are its own paragraph. When several listings share a paragraph,
        # use only the lines since the previous listing link so values never bleed between listings.
        for para in re.split(r"\n\s*\n", text):
            lines = para.splitlines()
            hits = [(i, unwrap_url(m.group(0).rstrip(".,;"))) for i, line in enumerate(lines)
                    for m in _URL_RE.finditer(line)]
            hits = [(i, u) for i, u in hits if _is_listing_url(u)]
            prev = -1
            for i, url in hits:
                segment = lines if len(hits) == 1 else lines[prev + 1: i + 1]
                block = " ".join(l.strip() for l in segment if l.strip())
                found.setdefault(_dedupe_key(url), _candidate(url, block, sender_site, subject))
                prev = i
    return list(found.values())


def parse_eml_bytes(data: bytes) -> tuple[dict, list[NormalizedListing]]:
    meta = read_eml(data)
    return meta, parse_alert(meta["html"], meta["text"], meta["from"], meta["subject"])


def parse_pasted(content: str) -> list[NormalizedListing]:
    """Pasted email: raw .eml source, HTML, or plain text."""
    head = content.lstrip()[:2000]
    if re.search(r"^(?:From|Subject|Received|MIME-Version):", head, re.M | re.I):
        return parse_eml_bytes(content.encode("utf-8", "replace"))[1]
    if re.search(r"<(?:html|table|a\s)", head, re.I):
        return parse_alert(html=content)
    return parse_alert(text=content)


def looks_like_rivian(nl: NormalizedListing) -> bool:
    blob = f"{nl.title or ''} {nl.description or ''} {nl.vin or ''} {nl.url or ''}".lower()
    return "rivian" in blob or "r1t" in blob or (nl.vin or "").startswith("7FCT")


def looks_like_truck(nl: NormalizedListing) -> bool:
    return parse_truck_identity(f"{nl.make or ''} {nl.model or ''} {nl.title or ''} {nl.description or ''}")[1] is not None


KNOWN_ALERT_SITES = sorted(SITE_DOMAINS)
