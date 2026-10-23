"""Plain data structures shared by source adapters, importers, and the ingest pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CONFIDENCE_RANK = {"verified": 4, "high": 3, "medium": 2, "low": 1}


@dataclass
class AttributeClaim:
    field: str
    value: str
    confidence: str          # high | medium | low
    method: str              # how this value was obtained, shown to the user
    source: str = ""         # filled in by the pipeline when empty
    evidence: str | None = None


@dataclass
class NormalizedListing:
    source_key: str
    import_method: str                       # api | email | capture | manual | csv | demo
    source_listing_id: str | None = None
    url: str | None = None
    vin: str | None = None
    year: int | None = None
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    price: int | None = None
    miles: int | None = None
    seller_name: str | None = None
    seller_type: str | None = None           # dealer | private | manufacturer | retailer | unknown
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    lat: float | None = None
    lon: float | None = None
    title: str | None = None
    description: str | None = None
    exterior_color: str | None = None
    interior_color: str | None = None
    transport_cost: int | None = None
    dealer_website: str | None = None          # selling dealer's homepage, when a provider reports it
    seller_phone: str | None = None
    history_report_url: str | None = None      # dealer-provided Carfax/AutoCheck link
    listed_at: str | None = None               # provider's earliest "first seen" for this listing (ISO UTC)
    days_on_market: int | None = None          # provider-reported days on market
    days_on_market_here: int | None = None     # days at the current seller (MarketCheck dom_active)
    photo_url: str | None = None               # one image of the truck (provider, email, page preview, user)
    photo_count: int | None = None
    attributes: list[AttributeClaim] = field(default_factory=list)
    available: bool = True
    removed_at: str | None = None            # provider says the listing was removed at this time
    is_demo: bool = False
    raw: dict[str, Any] | None = None


@dataclass
class FetchResult:
    listings: list[NormalizedListing]
    complete: bool                           # True only if every page of the scope was retrieved
    scope_hash: str | None = None
    api_calls: int = 0
    notes: list[str] = field(default_factory=list)
    error: str | None = None


class SourceError(Exception):
    """A connector failed; nothing it returned should be used to infer disappearances."""


class RateLimited(SourceError):
    pass


class NotConfigured(SourceError):
    pass
