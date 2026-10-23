"""Relist / flip detector: signs a truck has moved between sellers or been pulled and relisted.

Dealer-to-dealer moves are often wholesale/auction flips, sometimes after a problem — worth asking about and
checking the Carfax ownership/auction history. These are prompts to ask questions, not verdicts.
"""
from __future__ import annotations

from .dedup import norm_seller

ELSEWHERE_MIN_DAYS = 14
GAP_MIN_DAYS = 7


def _day(iso: str | None) -> str:
    return (iso or "")[:10]


def detect(listings: list[dict], events: list[dict]) -> dict:
    """listings/events for ONE vehicle. Returns {'flags': [...], 'text': str, 'flip': bool, 'sellers': [...]}."""
    flags: list[str] = []
    notes: list[str] = []

    # 1. Different sellers over time (ignore the same dealer appearing on several sites).
    spans: dict[str, dict] = {}
    for l in listings:
        key = norm_seller(l.get("seller_name"))
        if not key:
            continue
        s = spans.setdefault(key, {"name": l.get("seller_name"), "first": l["first_seen_at"], "last": l["last_seen_at"],
                                   "active": False})
        s["first"] = min(s["first"], l["first_seen_at"])
        s["last"] = max(s["last"], l["last_seen_at"])
        s["active"] = s["active"] or l.get("status") == "active"
    for e in events:
        if e.get("event_type") == "seller_change" and e.get("old_value"):
            key = norm_seller(e["old_value"])
            spans.setdefault(key, {"name": e["old_value"], "first": e["created_at"], "last": e["created_at"],
                                   "active": False})
    sellers = sorted(spans.values(), key=lambda s: s["first"])
    if len(sellers) >= 2:
        current = [s for s in sellers if s["active"]] or sellers[-1:]
        earlier = [s for s in sellers if s not in current]
        if earlier:
            flags.append("Changed dealers")
            notes.append("previously listed by " + ", ".join(f"{s['name']} ({_day(s['first'])}–{_day(s['last'])})"
                                                             for s in earlier)
                         + f"; now {current[-1]['name']}")
        elif len(current) >= 2:
            flags.append("Two sellers at once")
            notes.append("listed by " + " and ".join(s["name"] for s in current) + " at the same time")

    # 2. Pulled and relisted (missing for a while, then back).
    for e in events:
        if e.get("event_type") == "returned":
            flags.append("Relisted after a gap")
            notes.append(f"came back on {_day(e['created_at'])} after disappearing")
            break

    # 3. MarketCheck: days on market overall vs. at this seller.
    for l in listings:
        dom, here = l.get("days_on_market"), l.get("days_on_market_here")
        if dom is not None and here is not None and dom - here >= ELSEWHERE_MIN_DAYS:
            flags.append("Listed elsewhere first")
            notes.append(f"on the market {dom} days in total but only {here} at {l.get('seller_name') or 'this seller'} "
                         f"(about {dom - here} days somewhere else first)")
            break

    flags = list(dict.fromkeys(flags))
    text = "; ".join(notes)
    return {"flags": flags, "flip": bool(flags), "sellers": [s["name"] for s in sellers],
            "text": (text[0].upper() + text[1:] + ".") if text else ""}
