"""Where is the truck actually being sold? Classify listing URLs as the seller's own page or an aggregator.

Aggregators (AutoTrader, Cars.com, CarGurus, TrueCar, AutoTempest…) mostly re-display a dealer's inventory.
The "seller listing" is the page owned by whoever holds the truck: the dealer's website, Rivian, CarMax,
Carvana, or the private seller's own ad (KSL, Facebook, or a private-party ad on a marketplace).
"""
from __future__ import annotations

from urllib.parse import quote_plus, urlsplit

AGGREGATOR_DOMAINS = {
    "autotrader.com": "AutoTrader", "cars.com": "Cars.com", "cargurus.com": "CarGurus", "truecar.com": "TrueCar",
    "autotempest.com": "AutoTempest", "edmunds.com": "Edmunds", "kbb.com": "Kelley Blue Book",
    "carfax.com": "Carfax Listings", "autolist.com": "Autolist", "iseecars.com": "iSeeCars",
    "carsforsale.com": "CarsForSale", "cardaddy.com": "CarDaddy", "capitalone.com": "Capital One Auto Navigator",
    "carsdirect.com": "CarsDirect", "auto.dev": "Auto.dev", "marketcheck.com": "MarketCheck",
    "rivianroamer.com": "Rivian Roamer", "vast.com": "Vast (listing network)",
}
# Sites where the listing page itself is the point of sale.
SELLER_DOMAINS = {
    "rivian.com": "Rivian (manufacturer)", "carmax.com": "CarMax", "carvana.com": "Carvana",
    "ksl.com": "KSL ad (private/dealer)", "facebook.com": "Facebook Marketplace ad", "craigslist.org": "Craigslist ad",
    "ebay.com": "eBay Motors listing", "vroom.com": "Vroom", "shift.com": "Shift",
}
SELLER_PRIORITY = {"manufacturer": 0, "dealer": 1, "retailer": 1, "private": 2}


def host_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _match(host: str, table: dict[str, str]) -> str | None:
    for domain, label in table.items():
        if host == domain or host.endswith("." + domain):
            return label
    return None


def listing_role(url: str | None, seller_type: str | None = None) -> tuple[str, str]:
    """Return (role, label). role is 'seller', 'aggregator' or 'none' (no URL).

    An aggregator page for a private-party ad counts as the seller listing: the seller posted it there.
    Any host we don't recognise is assumed to be the selling dealer's own website.
    """
    host = host_of(url)
    if not host:
        return "none", ""
    if host in ("example.com",) or host.endswith(".example") or host.endswith(".example.com"):
        return "seller", "Demo/sample site"
    agg = _match(host, AGGREGATOR_DOMAINS)
    if agg:
        if (seller_type or "").lower() == "private":
            return "seller", f"{agg} (private-party ad)"
        return "aggregator", agg
    seller = _match(host, SELLER_DOMAINS)
    if seller:
        return "seller", seller
    return "seller", f"Dealer site ({host})"


def pick_links(listings: list[dict]) -> dict:
    """From all listings of one vehicle, choose the seller's own link and the aggregator links.

    Active listings beat missing/removed ones; among seller pages, dealer/manufacturer pages beat
    private-party marketplace ads, then the most recently seen wins.
    """
    status_rank = {"active": 0, "missing": 1, "removed": 2}
    sellers, aggregators = [], []
    for l in listings:
        role, label = listing_role(l.get("url"), l.get("seller_type"))
        if role == "seller":
            sellers.append((l, label))
        elif role == "aggregator":
            aggregators.append((l, label))
    sellers.sort(key=lambda t: (status_rank.get(t[0].get("status"), 3),
                                SELLER_PRIORITY.get((t[0].get("seller_type") or "dealer"), 1),
                                -_ts(t[0].get("last_seen_at"))))
    aggregators.sort(key=lambda t: (status_rank.get(t[0].get("status"), 3), -_ts(t[0].get("last_seen_at"))))
    dealer_site = next((l.get("dealer_website") for l in listings if l.get("dealer_website")), None)
    out = {
        "seller_url": sellers[0][0]["url"] if sellers else "",
        "seller_listing_id": sellers[0][0].get("id") if sellers else None,
        "seller_listing_name": sellers[0][0].get("seller_name") or "" if sellers else "",
        "seller_site": sellers[0][1] if sellers else "",
        "seller_listing_status": sellers[0][0].get("status") if sellers else "",
        "found_on_url": aggregators[0][0]["url"] if aggregators else "",
        "found_on": ", ".join(dict.fromkeys(lbl for _, lbl in aggregators)),
        "dealer_website": dealer_site or "",
    }
    if sellers:
        out["link_status"] = "seller" if out["seller_listing_status"] == "active" else "seller (not active)"
    elif aggregators:
        out["link_status"] = "aggregator only"
    else:
        out["link_status"] = "no link"
    return out


def _ts(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def vin_search_url(vin: str | None) -> str:
    """A web search for the exact VIN — usually surfaces the selling dealer's own page."""
    return f"https://www.google.com/search?q={quote_plus(chr(34) + vin + chr(34))}" if vin else ""


def dealer_search_url(seller: str | None, city: str | None = None, state: str | None = None,
                      make: str = "Rivian", model: str = "R1T") -> str:
    """A web search for the dealer's used Rivian inventory, for listings that don't expose a VIN."""
    if not seller:
        return ""
    q = " ".join(x for x in (seller, city, state, "used", make, model) if x)
    return f"https://www.google.com/search?q={quote_plus(q)}"


def listing_search_url(year, price, city: str | None, state: str | None,
                       make: str = "Rivian", model: str = "R1T") -> str:
    """Last-resort search when neither VIN nor seller is known."""
    bits = [str(int(year)) if year else "", make, model, f"${int(price):,}" if price else "", city or "", state or ""]
    q = " ".join(b for b in bits if b)
    return f"https://www.google.com/search?q={quote_plus(q)}"


BRAND_CASE = {"carmax": "CarMax", "autonation": "AutoNation", "automatch": "AutoMatch", "ev": "EV", "llc": "LLC",
              "gmc": "GMC", "bmw": "BMW", "usa": "USA"}


def display_name(name: str | None, site_label: str | None = None) -> str:
    """Just who the seller is: 'AutoMatch', 'Carvana', 'Anchor Auto Outlet Inc' — no 'dealer'/'manufacturer' labels."""
    name = (name or "").strip()
    if name:
        if name.islower() or name.isupper():
            name = " ".join(w if (len(w) <= 3 and w.isupper() and w.isalpha() and w not in ("INC", "LLC")) else w.capitalize()
                            for w in name.split())
        return " ".join(BRAND_CASE.get(w.lower(), w) for w in name.split())
    label = (site_label or "").strip()
    if label.startswith("Dealer site (") and label.endswith(")"):
        return label[len("Dealer site ("):-1]
    for suffix in (" (manufacturer)", " (private/dealer)", " (private-party ad)"):
        label = label.replace(suffix, "")
    return label
