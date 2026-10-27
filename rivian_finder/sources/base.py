"""Shared plumbing for API connectors: polite HTTP with retries, usage accounting, scope hashing."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import Callable

import requests

from ..db import utcnow
from ..models import FetchResult, RateLimited, SourceError
from ..credentials import redact

log = logging.getLogger(__name__)
USER_AGENT = "TruckFinder/1.0 (local-first inventory tracker)"
API_CAPS = {"autodev": 1000, "marketcheck": 500}
EV_TRUCK_PRESET = [
    {"make": "Rivian", "model": "R1T"},
    {"make": "Ford", "model": "F-150 Lightning"},
    {"make": "Chevrolet", "model": "Silverado EV"},
    {"make": "GMC", "model": "Sierra EV"},
]
SUPPORTED_BRANDS = tuple(target["make"] for target in EV_TRUCK_PRESET)


class BudgetExhausted(SourceError):
    """The local request limit stopped a connector before another billable attempt."""


def search_targets(scope: dict) -> list[dict]:
    """Validate explicit make/model pairs; absent configuration retains the original truck preset."""
    searches = scope.get("searches")
    if searches is None:
        return [dict(target) for target in EV_TRUCK_PRESET]
    if not isinstance(searches, list) or not searches:
        raise ValueError("Add at least one vehicle search with both a make and model.")
    targets, seen = [], set()
    for search in searches:
        if not isinstance(search, dict):
            raise ValueError("Each vehicle search needs both a make and model.")
        target = {}
        for field in ("make", "model"):
            value = search.get(field)
            if not isinstance(value, str) or not value.strip() or any(c in value for c in (",", "\r", "\n")):
                raise ValueError("Make and model must be nonempty text without commas or newlines.")
            target[field] = " ".join(value.split())
        pair = (target["make"].casefold(), target["model"].casefold())
        if pair not in seen:
            seen.add(pair)
            targets.append(target)
    return targets


def configured_brands(scope: dict) -> list[str]:
    """Brand choices for the configured make/model searches, preserving the first spelling."""
    names = {}
    for target in search_targets(scope):
        names.setdefault(target["make"].casefold(), target["make"])
    return list(names.values())


def matches_target(make: str | None, model: str | None, target: dict) -> bool:
    if not isinstance(make, str) or not isinstance(model, str):
        return False
    return (" ".join((make or "").split()).casefold(), " ".join((model or "").split()).casefold()) == (
        target["make"].casefold(), target["model"].casefold())


def collection_scopes(scope: dict, source_key: str) -> list[dict]:
    """Build selected custom pairs, or retain the original grouped EV-truck queries."""
    brands = scope.get("brands")
    if scope.get("searches") is not None:
        chosen = None if brands is None else {brand.casefold() for brand in brands}
        scopes = []
        for target in search_targets(scope):
            if chosen is not None and target["make"].casefold() not in chosen:
                continue
            query = {**scope, **target, "zip": scope.get("home_zip", "84020"),
                     "distance": int(scope.get("max_distance", 0) or 0)}
            if query["distance"] < 0:
                raise ValueError("Maximum search distance must be zero (nationwide) or a positive number of miles.")
            if source_key == "marketcheck":
                limits = [int(scope.get("marketcheck_radius", 100) or 0), query["distance"]]
                if any(radius < 0 for radius in limits):
                    raise ValueError("MarketCheck radius must be zero (nationwide) or a positive number of miles.")
                query.update(marketcheck_zip=query["zip"],
                             marketcheck_radius=min((r for r in limits if r > 0), default=0))
            scopes.append(query)
        return scopes
    if brands is None:
        if not scope.get("include_other_brands", False):
            return [scope]
        brands = SUPPORTED_BRANDS
    models = {"Ford": "F-150 Lightning", "Chevrolet": "Silverado EV", "GMC": "Sierra EV"}
    makes = [make for make in models if make in brands]
    scopes = []
    if makes:
        other = {**scope, "make": ",".join(makes), "model": ",".join(models[make] for make in makes),
                 "max_price": scope.get("other_max_price", 65000),
                 "max_miles": scope.get("other_max_miles", 45000), "used_only": True,
                 "zip": scope.get("home_zip", "84020"), "distance": scope.get("other_max_distance", 650)}
        if source_key == "marketcheck":
            # Free MarketCheck searches remain inside the user's existing plan radius.
            radius = int(scope.get("marketcheck_radius", 100) or 0)
            other.update(marketcheck_zip=other["zip"],
                         marketcheck_radius=min(radius or other["distance"], other["distance"]))
        scopes.append(other)
    if "Rivian" in brands:
        scopes.append({**scope, "make": "Rivian", "model": "R1T"} if scope.get("brands") is not None else scope)
    return scopes


def scope_hash(params: dict) -> str:
    return hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:16]


class SourceAdapter:
    key = "base"
    name = "Base"

    def is_configured(self) -> tuple[bool, str]:
        return True, ""

    def fetch(self, scope: dict):  # -> FetchResult
        raise NotImplementedError


class HttpSourceAdapter(SourceAdapter):
    min_interval = 0.25          # seconds between requests (respect provider rate limits)
    max_retries = 3
    timeout = 30

    def __init__(self, api_key: str | None, session: requests.Session | None = None,
                 conn: sqlite3.Connection | None = None, sleep=time.sleep):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.conn = conn
        self.sleep = sleep
        self._last_call = 0.0
        self.calls = 0
        self._call_limit = None

    def is_configured(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, f"No API key configured for {self.name}. Add it in Settings → API credentials."
        return True, ""

    def _fetch_scopes(self, scope: dict, build_params: Callable[[dict], dict]) -> FetchResult:
        """Share one request allowance and combine the provider's per-scope results."""
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

    def set_call_limit(self, limit: int) -> None:
        """Limit all subsequent attempts, including retries, relative to the current count."""
        self._call_limit = self.calls + max(int(limit), 0)

    def _reserve_call(self, endpoint: str) -> int | None:
        if self._call_limit is not None and self.calls >= self._call_limit:
            raise BudgetExhausted(f"Stopped at the per-run request limit for {self.name}; scan is incomplete.")
        if self.conn is None:
            return None
        now = utcnow()
        cap = API_CAPS.get(self.key)
        with self.conn:
            # Reserve atomically before HTTP so retries and concurrent searches share the same cap.
            row = self.conn.execute(
                "INSERT INTO api_usage(source_key, called_at, endpoint, status_code)"
                " SELECT ?,?,?,NULL WHERE ? IS NULL OR"
                " (SELECT COUNT(*) FROM api_usage WHERE source_key=? AND called_at>=?) < ?",
                (self.key, now, endpoint, cap, self.key, now[:7] + "-01T00:00:00Z", cap))
            if not row.rowcount:
                raise BudgetExhausted(f"Stopped to protect {self.name}'s {cap:,}-call monthly budget.")
            return row.lastrowid

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict:
        """GET with pacing, Retry-After aware backoff on 429/5xx, and credential-free error messages."""
        attempt = 0
        while True:
            usage_id = self._reserve_call(url.split("?")[0])
            self.calls += 1
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                self.sleep(wait)
            self._last_call = time.monotonic()
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                attempt += 1
                if attempt > self.max_retries:
                    raise SourceError(f"Network error contacting {self.name}: {redact(str(e))}") from None
                self.sleep(2 ** attempt)
                continue
            if usage_id is not None:
                with self.conn:
                    self.conn.execute("UPDATE api_usage SET status_code=? WHERE id=?", (resp.status_code, usage_id))
            if resp.status_code == 429 or resp.status_code >= 500:
                attempt += 1
                if attempt > self.max_retries:
                    if resp.status_code == 429:
                        raise RateLimited(f"{self.name} returned HTTP 429 after {self.max_retries} retries")
                    raise SourceError(f"{self.name} returned HTTP {resp.status_code}")
                retry_after = resp.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 2 ** attempt
                self.sleep(min(delay, 60))
                continue
            if resp.status_code in (401, 403):
                raise SourceError(f"{self.name} rejected the API key (HTTP {resp.status_code}). "
                                  "Check the key or your plan.")
            if resp.status_code >= 400:
                detail = ""
                try:
                    body = resp.json()
                    err = body.get("error")
                    detail = (err.get("message") if isinstance(err, dict) else err) or body.get("message") or ""
                    if body.get("code"):
                        detail = f"{body['code']}: {detail}"
                except ValueError:
                    detail = resp.text[:200]
                raise SourceError(f"{self.name} HTTP {resp.status_code}: {redact(str(detail))}")
            try:
                return resp.json()
            except ValueError:
                raise SourceError(f"{self.name} returned non-JSON content") from None
