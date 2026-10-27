"""MarketCheck active inventory search connector (https://docs.marketcheck.com).

Free plan (per MarketCheck's published pricing): 500 calls/month, 5 calls/second, searches limited to a
100-mile radius. Paid plans can search nationwide (set radius to 0 in Settings → Collection scope).
"""
from __future__ import annotations

import os
from datetime import date

from ..extract import extract_attributes, normalize_state, parse_int, structured_truck_specs
from ..models import AttributeClaim, FetchResult, NormalizedListing, SourceError
from ..trims import excluded_trim, standard_range
from .base import BudgetExhausted, HttpSourceAdapter, matches_target

BASE_URL = os.environ.get("MARKETCHECK_BASE_URL", "https://api.marketcheck.com")
ROWS = 50


def build_params(scope: dict) -> dict:
    years = ",".join(str(y) for y in range(int(scope.get("year_min", 2000)), int(scope.get("year_max", date.today().year + 1)) + 1))
    params = {
        "make": scope.get("make", "Rivian"),
        "model": scope.get("model", "R1T"),
        "year": years,
        "price_range": f"1-{int(scope.get('max_price', 90000))}",
        "miles_range": f"0-{int(scope.get('max_miles', 80000))}",
        "rows": ROWS,
        "sort_by": "price",
        "sort_order": "asc",
    }
    if scope.get("used_only", True):
        params["car_type"] = "used"
    radius = int(scope.get("marketcheck_radius", 100) or 0)
    if radius > 0:
        params["zip"] = scope.get("marketcheck_zip", "84020")
        params["radius"] = radius
    return params


def parse_item(item: dict) -> NormalizedListing:
    build = item.get("build") or {}
    dealer = item.get("dealer") or {}
    extra = item.get("extra") or {}
    description = " ; ".join(str(x) for x in (item.get("description"), item.get("seller_comments"),
                                               extra.get("description")) if x)
    configuration = " ".join(str(x) for x in (item.get("heading") or item.get("title"), *(build.get(key) for key in (
        "trim", "version", "drivetrain", "battery", "battery_type", "battery_pack", "configuration"))) if x)
    attrs = extract_attributes(configuration + " ; " + description, "MarketCheck structured build fields",
                               confidence="medium", structured=True, make=build.get("make"), model=build.get("model"))
    attrs += structured_truck_specs(build, "MarketCheck structured build fields")
    attrs += structured_truck_specs(extra, "MarketCheck structured extra fields")
    option_text = " ; ".join(str(x) for x in (extra.get("options") or []) + (extra.get("features") or [])
                             + (item.get("high_value_features") or []))
    if option_text:
        attrs += extract_attributes(option_text, "MarketCheck options/features list", confidence="medium",
                                    structured=True, make=build.get("make"), model=build.get("model"))
    if (build.get("make") or "").lower() != "rivian":
        attrs = [c for c in attrs if c.field != "battery"] + [
            c for c in extract_attributes(configuration, "MarketCheck configuration fields", confidence="medium", structured=True,
                                          make=build.get("make"), model=build.get("model")) if c.field == "battery"]
    if item.get("carfax_clean_title") is True:   # False only means "not reported clean", so it is ignored
        attrs.append(AttributeClaim("title_status", "clean", "medium", "MarketCheck: Carfax clean-title flag",
                                    evidence="carfax_clean_title = true"))
    if item.get("carfax_1_owner") is True:
        attrs.append(AttributeClaim("owners", "1 owner", "medium", "MarketCheck: Carfax one-owner flag",
                                    evidence="carfax_1_owner = true"))
    seller_type = (item.get("seller_type") or "dealer").lower()
    return NormalizedListing(
        source_key="marketcheck", import_method="api",
        source_listing_id=str(item.get("id")) if item.get("id") else item.get("vin"),
        url=item.get("vdp_url"), vin=item.get("vin"), year=parse_int(build.get("year")),
        make=build.get("make"), model=build.get("model"), trim=build.get("trim"),
        price=parse_int(item.get("price")), miles=parse_int(item.get("miles")),
        seller_name=dealer.get("name") or item.get("seller_name"),
        seller_type="private" if seller_type in ("fsbo", "private") else "dealer",
        city=dealer.get("city"), state=normalize_state(dealer.get("state")), zip=dealer.get("zip"),
        lat=float(dealer["latitude"]) if dealer.get("latitude") not in (None, "") else None,
        lon=float(dealer["longitude"]) if dealer.get("longitude") not in (None, "") else None,
        title=item.get("heading") or item.get("title"), description=description or None, exterior_color=item.get("exterior_color"),
        interior_color=item.get("interior_color"), attributes=attrs,
        dealer_website=_website(dealer.get("website")), seller_phone=dealer.get("phone") or None,
        listed_at=_earliest(item.get("first_seen_at_mc_date"), item.get("first_seen_at_source_date"),
                            item.get("first_seen_at_date")),
        days_on_market=parse_int(item.get("dom")), days_on_market_here=parse_int(item.get("dom_active")),
        photo_url=_first_photo(item.get("media")),
        photo_count=len((item.get("media") or {}).get("photo_links") or []) or None,
        raw={k: item.get(k) for k in ("id", "vin", "heading", "price", "miles", "first_seen_at_date",
                                      "first_seen_at_mc_date", "last_seen_at_date", "dom", "dom_active",
                                      "carfax_clean_title", "carfax_1_owner", "seller_type", "inventory_type")},
    )


def _first_photo(media: dict | None) -> str | None:
    for key in ("photo_links", "photo_links_cached"):
        for url in (media or {}).get(key) or []:
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                return url
    return None


def _earliest(*dates: str | None) -> str | None:
    """Earliest of several ISO timestamps like '2026-06-16T11:03:45.000Z', normalised to seconds + Z."""
    vals = sorted(d[:19] + "Z" for d in dates if d and len(d) >= 19)
    return vals[0] if vals else None


def _website(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return value if value.startswith(("http://", "https://")) else f"https://{value}"


class MarketCheckAdapter(HttpSourceAdapter):
    key = "marketcheck"
    name = "MarketCheck"
    min_interval = 0.25

    def fetch(self, scope: dict) -> FetchResult:
        return self._fetch_scopes(scope, build_params)

    def _fetch_scope(self, scope: dict) -> FetchResult:
        params = build_params(scope)
        max_pages = int(scope.get("max_pages_per_run", 40))
        listings: list[NormalizedListing] = []
        notes: list[str] = []
        start, pages, num_found, complete = 0, 0, None, False
        error = None
        skipped_trims = 0
        skipped_standard = 0
        while pages < max_pages:
            try:
                body = self.get_json(f"{BASE_URL}/v2/search/car/active",
                                     params={**params, "start": start, "api_key": self.api_key})
            except BudgetExhausted as e:
                error = str(e)
                notes.append(error)
                break
            except SourceError as e:
                if "HTTP 422" in str(e) and pages > 0:
                    notes.append("Reached the plan's pagination limit; scan is incomplete.")
                    break
                raise
            pages += 1
            num_found = body.get("num_found", num_found)
            batch = body.get("listings") or []
            for item in batch:
                nl = parse_item(item)
                if scope.get("searches") is not None and not matches_target(nl.make, nl.model, scope):
                    continue
                # shortcut: no documented API trim exclusion; filter rows until the provider supports it.
                if excluded_trim(nl.make, nl.model, nl.trim, scope.get("excluded_trims", {})):
                    skipped_trims += 1
                    continue
                build = item.get("build") or {}
                if scope.get("exclude_standard_range") and standard_range(
                        nl.make, nl.model, nl.trim, nl.title,
                        *(build.get(key) for key in ("version", "battery", "battery_type", "battery_pack", "configuration")),
                        *(c.value for c in nl.attributes if c.field == "battery")):
                    skipped_standard += 1
                    continue
                listings.append(nl)
            start += ROWS
            if not batch or (num_found is not None and start >= num_found):
                complete = True
                break
        else:
            notes.append(f"Stopped after {max_pages} pages (max_pages_per_run). Scan is incomplete.")
        if "radius" in params:
            notes.append(f"Searched within {params['radius']} miles of {params['zip']} (free plan limit is 100).")
        if num_found is not None:
            notes.append(f"Provider reported {num_found} listings; retrieved {len(listings)}.")
        if skipped_trims:
            notes.append(f"Skipped {skipped_trims} excluded-trim listings.")
        if skipped_standard:
            notes.append(f"Skipped {skipped_standard} Standard Range listings.")
        return FetchResult(listings=listings, complete=complete, notes=notes, error=error)
