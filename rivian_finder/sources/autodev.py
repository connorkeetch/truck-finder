"""Auto.dev Vehicle Listings API connector (https://docs.auto.dev/v2/products/vehicle-listings).

Free plan: 1,000 calls/month, results clamped to 20 per page. Auth: `Authorization: Bearer <key>`.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from ..extract import extract_attributes, normalize_state, parse_int, structured_truck_specs
from ..geo import usable_coords
from ..models import FetchResult, NormalizedListing, SourceError
from ..trims import excluded_trim, standard_range
from .base import BudgetExhausted, HttpSourceAdapter, collection_scopes, matches_target, scope_hash

BASE_URL = "https://api.auto.dev"


def build_params(scope: dict) -> dict:
    params = {
        "vehicle.make": scope.get("make", "Rivian"),
        "vehicle.model": scope.get("model", "R1T"),
        "vehicle.year": f"{scope.get('year_min', 2022)}-{scope.get('year_max', 2026)}",
        "retailListing.price": f"1-{int(scope.get('max_price', 90000))}",
        "retailListing.miles": f"0-{int(scope.get('max_miles', 80000))}",
        "sort": "updatedAt.desc",
        "limit": 100,
    }
    if scope.get("used_only", True):
        params["retailListing.used"] = "true"
    if int(scope.get("distance", 0) or 0) > 0:
        params.update(zip=scope.get("zip", "84020"), distance=int(scope["distance"]))
    return params


def _first(*vals):
    for v in vals:
        if v not in (None, "", []):
            return v
    return None


def _iso(ts: str | None) -> str | None:
    """'2026-10-16 09:27:42' -> '2026-10-16T09:27:42Z'."""
    if not ts or len(ts) < 10:
        return None
    return ts[:19].replace(" ", "T") + ("Z" if len(ts) >= 19 else "")


def parse_item(item: dict) -> NormalizedListing | None:
    vehicle = item.get("vehicle") or {}
    retail = item.get("retailListing") or {}
    if not retail:
        return None  # wholesale-only record; not something a consumer can buy
    vin = _first(item.get("vin"), vehicle.get("vin"))
    loc = item.get("location") or []
    lon, lat = (loc[0], loc[1]) if isinstance(loc, (list, tuple)) and len(loc) == 2 else (None, None)
    year = parse_int(vehicle.get("year"))
    title = _first(item.get("heading"), item.get("title"), retail.get("heading"), retail.get("title"),
                   vehicle.get("heading"), vehicle.get("title"),
                   " ".join(str(x) for x in (year, vehicle.get("make"), vehicle.get("model"), vehicle.get("trim")) if x))
    trim_text = " ".join(str(x) for x in (title, *(vehicle.get(key) for key in (
        "trim", "series", "version", "style", "engine", "drivetrain", "battery", "batteryType", "batteryPack", "configuration"))) if x)
    description = " ; ".join(str(x) for field in (
        item.get("description"), vehicle.get("description"), retail.get("description"),
        vehicle.get("options"), vehicle.get("features"), retail.get("options"), retail.get("features"))
        for x in (field if isinstance(field, list) else [field]) if x)
    attrs = extract_attributes(trim_text + " ; " + description, "Auto.dev listing fields", confidence="medium", structured=True,
                               make=vehicle.get("make"), model=vehicle.get("model"))
    attrs += structured_truck_specs(vehicle, "Auto.dev structured vehicle fields")
    attrs += structured_truck_specs(retail, "Auto.dev structured retail fields")
    if (vehicle.get("make") or "").lower() != "rivian":
        attrs = [c for c in attrs if c.field != "battery"] + [
            c for c in extract_attributes(trim_text, "Auto.dev configuration fields", confidence="medium", structured=True,
                                          make=vehicle.get("make"), model=vehicle.get("model")) if c.field == "battery"]
    url = retail.get("vdp")
    return NormalizedListing(
        source_key="autodev", import_method="api",
        source_listing_id=vin or (url and f"url:{url}") or None,
        url=url, vin=vin, year=year, make=vehicle.get("make"), model=vehicle.get("model"),
        trim=vehicle.get("trim"), price=parse_int(retail.get("price")), miles=parse_int(retail.get("miles")),
        seller_name=retail.get("dealer"), seller_type="dealer", city=retail.get("city"),
        state=normalize_state(retail.get("state")), zip=retail.get("zip"),
        lat=float(lat) if usable_coords(lat, lon) else None, lon=float(lon) if usable_coords(lat, lon) else None,
        title=title or None, description=description or None,
        exterior_color=vehicle.get("exteriorColor"), interior_color=vehicle.get("interiorColor"),
        attributes=attrs, available=item.get("online", True) is not False,
        removed_at=item.get("removedAt"), history_report_url=retail.get("carfaxUrl") or None,
        photo_url=retail.get("primaryImage") or None, photo_count=parse_int(retail.get("photoCount")),
        listed_at=_iso(item.get("createdAt")),
        raw={k: item.get(k) for k in ("vin", "createdAt", "updatedAt", "online", "vehicle", "retailListing")},
    )


class AutoDevAdapter(HttpSourceAdapter):
    key = "autodev"
    name = "Auto.dev"
    min_interval = 0.25   # free plan: 5 requests/second

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    def fetch(self, scope: dict) -> FetchResult:
        scopes = collection_scopes(scope, self.key)
        max_calls = max(int(scope.get("max_pages_per_run", 40)), 0)
        before = self.calls
        listings, notes, errors = [], [], []
        complete = True
        had_result = False
        for index, query_scope in enumerate(scopes):
            remaining = max_calls - (self.calls - before)
            if scope.get("searches") is not None:
                allowance = (remaining + len(scopes) - index - 1) // (len(scopes) - index)
            else:
                # Preserve the existing Rivian priority until the user configures custom searches.
                allowance = min(max_calls, max(1, max_calls // 4)) if index < len(scopes) - 1 else remaining
            self.set_call_limit(allowance)
            try:
                result = self._fetch_scope(query_scope)
            except SourceError as e:
                if len(scopes) == 1:
                    raise
                complete = False
                errors.append(str(e))
                continue
            had_result = True
            listings.extend(result.listings)
            notes.extend(result.notes)
            complete = complete and result.complete
            if result.error:
                errors.append(result.error)
        if errors and not had_result:
            raise SourceError("; ".join(errors))
        shash = scope_hash({"src": self.key, "queries": [build_params(s) for s in scopes],
                            **({"excluded_trims": scope["excluded_trims"]} if scope.get("excluded_trims") else {}),
                            **({"exclude_standard_range": True} if scope.get("exclude_standard_range") else {})})
        return FetchResult(listings, complete, shash, self.calls - before, notes, "; ".join(errors) or None)

    def _fetch_scope(self, scope: dict) -> FetchResult:
        params = build_params(scope)
        shash = scope_hash({"src": self.key, **{k: v for k, v in params.items() if k != "limit"},
                            **({"excluded_trims": scope["excluded_trims"]} if scope.get("excluded_trims") else {}),
                            **({"exclude_standard_range": True} if scope.get("exclude_standard_range") else {})})
        max_pages = int(scope.get("max_pages_per_run", 40))
        listings: list[NormalizedListing] = []
        notes: list[str] = []
        seen_vins: set[str] = set()
        skipped_new = 0
        skipped_trims = 0
        skipped_standard = 0
        url = f"{BASE_URL}/listings"
        query: dict | None = {**params, "page": 1, "includes": "total"}
        total = None
        pages = 0
        complete = False
        error = None
        while pages < max_pages:
            try:
                body = self.get_json(url, params=query, headers=self._headers())
            except BudgetExhausted as e:
                error = str(e)
                notes.append(error)
                break
            pages += 1
            data = body.get("data") or []
            if total is None and isinstance(body.get("total"), int):
                total = body["total"]
            for item in data:
                nl = parse_item(item)
                if nl is None:
                    continue
                if scope.get("searches") is not None and not matches_target(nl.make, nl.model, scope):
                    continue
                if scope.get("used_only", True) and (item.get("retailListing") or {}).get("used") is False:
                    skipped_new += 1
                    continue
                # shortcut: no documented API trim exclusion; filter rows until the provider supports it.
                if excluded_trim(nl.make, nl.model, nl.trim, scope.get("excluded_trims", {})):
                    skipped_trims += 1
                    continue
                vehicle = item.get("vehicle") or {}
                if scope.get("exclude_standard_range") and standard_range(
                        nl.make, nl.model, nl.trim, nl.title,
                        *(vehicle.get(key) for key in ("series", "version", "battery", "batteryType", "batteryPack", "configuration")),
                        *(c.value for c in nl.attributes if c.field == "battery")):
                    skipped_standard += 1
                    continue
                if nl.vin and nl.vin in seen_vins:
                    continue
                if nl.vin:
                    seen_vins.add(nl.vin)
                listings.append(nl)
            next_link = (body.get("links") or {}).get("next")
            if not data or not next_link:
                complete = True
                break
            # Follow the provider's next link (it switches to cursors on deep pages).
            parts = urlsplit(next_link)
            url = f"{BASE_URL}{parts.path}" if parts.path else url
            next_params = dict(parse_qsl(parts.query))
            query = {**(next_params or {"page": pages + 1}), **params}
        else:
            notes.append(f"Stopped after {max_pages} pages (max_pages_per_run). Scan is incomplete.")
        if total is not None:
            notes.append(f"Provider reported {total} matching listings; retrieved {len(listings)} retail listings "
                         f"in {pages} page(s).")
        if skipped_new:
            notes.append(f"Skipped {skipped_new} new-vehicle listings.")
        if skipped_trims:
            notes.append(f"Skipped {skipped_trims} excluded-trim listings.")
        if skipped_standard:
            notes.append(f"Skipped {skipped_standard} Standard Range listings.")
        if not listings and pages == 1 and complete:
            notes.append(f"Auto.dev returned no eligible {scope.get('model', 'R1T')} listings for this scope.")
        return FetchResult(listings=listings, complete=complete, scope_hash=shash, api_calls=self.calls,
                           notes=notes, error=error)

    def lookup_vin(self, vin: str) -> NormalizedListing | None:
        """Single-VIN lookup. Returns the latest stored listing, including removedAt for delisted vehicles."""
        try:
            body = self.get_json(f"{BASE_URL}/listings/{vin}", headers=self._headers())
        except SourceError as e:
            if "404" in str(e):
                return None
            raise
        item = body.get("data") if isinstance(body.get("data"), dict) else body
        return parse_item(item) if item else None
