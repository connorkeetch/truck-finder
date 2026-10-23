"""Read models shared by the UI and the Excel export."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

import pandas as pd

from . import adjust, checklist, deals, epa, finance, flips, linkcheck, links, negotiation, photos, recalls, shipping, subframe, warranty
from .attributes import resolve_many
from .config import ACCIDENT_STATUSES, TITLE_STATUSES, TONNEAU_STATUSES
from .geo import distance_from_zip
from .pipeline import EVENT_LABELS
from .sources.base import EV_TRUCK_PRESET, matches_target
from .trims import excluded_trim, standard_range, trim_label

CONF_LABEL = {"verified": "verified", "high": "high", "medium": "med", "low": "low", "": ""}
SOURCE_LABELS = {
    "autodev": "Auto.dev", "marketcheck": "MarketCheck", "demo": "DEMO", "rivian": "Rivian", "carmax": "CarMax",
    "carvana": "Carvana", "autotrader": "AutoTrader", "autotempest": "AutoTempest", "ksl": "KSL",
    "facebook": "Facebook", "cars_com": "Cars.com", "cargurus": "CarGurus", "truecar": "TrueCar",
    "dealer": "Dealer site", "other": "Other", "nhtsa_vpic": "NHTSA vPIC", "vin_rule": "VIN rule",
    "listing_year": "Listed year", "user": "You", "marketcheck_decode": "MarketCheck decode",
    "epa_match": "EPA rating match",
}


def source_label(key: str | None) -> str:
    return SOURCE_LABELS.get(key or "", key or "")


def _obs_stats(conn: sqlite3.Connection) -> dict[int, dict]:
    by_listing: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for r in conn.execute("SELECT listing_id, observed_at, price FROM observations WHERE price IS NOT NULL"
                          " ORDER BY listing_id, observed_at, id"):
        by_listing[r["listing_id"]].append((r["observed_at"], r["price"]))
    return {lid: negotiation.price_moves(obs) for lid, obs in by_listing.items()}


def _options(res) -> list[str]:
    """Every value a source has claimed (only your verified value counts once you've verified it)."""
    if res is None:
        return []
    if res.confidence == "verified":
        return [res.value]
    return sorted({res.value, *(a["value"] for a in res.alternatives)} - {None, ""})


def _subframe(vin: str | None, verified: str | None) -> dict:
    """Front subframe: what you verified, else the VIN-based estimate."""
    if verified in ("cast", "welded"):
        return {"subframe": verified, "subframe_note": "verified by you"}
    status, why = subframe.estimate(vin)
    return {"subframe": status, "subframe_note": why}


def _uncertain(res) -> bool:
    """Sources disagree and you haven't verified it."""
    return bool(res is not None and res.confidence != "verified" and len(_options(res)) > 1)


def _method_hint(method: str | None) -> str:
    """Which part of the listing a claim came from, in a couple of words."""
    m = (method or "").lower()
    for needle, hint in (("trim", " trim name"), ("structured", " spec text"), ("decode", " decode"),
                         ("epa", " EPA range"), ("description", " description"), ("title", " title")):
        if needle in m:
            return hint
    return ""


def _who_says(res) -> str:
    """'Large: MarketCheck decode, Auto.dev · Standard: Auto.dev' for disputed values."""
    if not _uncertain(res):
        return ""
    by: dict[str, list[str]] = {}
    for a in res.alternatives:
        by.setdefault(a["value"], [])
        label = source_label(a["source"]) + _method_hint(a.get("method"))
        if label not in by[a["value"]]:
            by[a["value"]].append(label)
    return " · ".join(f"{v}: {', '.join(srcs)}" for v, srcs in by.items())


def _attr_text(res) -> str:
    if res is None or res.value in (None, ""):
        return ""
    src = source_label(res.source)
    return f"{src} ({CONF_LABEL.get(res.confidence, res.confidence)})" if src else ""


def inventory_frame(conn: sqlite3.Connection, settings: dict) -> pd.DataFrame:
    """One row per vehicle with its best listing, resolved attributes, finance estimate and fit score."""
    vehicles = [dict(r) for r in conn.execute("SELECT * FROM vehicles WHERE merged_into_id IS NULL")]
    if not vehicles:
        return pd.DataFrame()
    listings_by_vehicle: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT * FROM listings"):
        listings_by_vehicle[r["vehicle_id"]].append(dict(r))
    favorites = {r[0] for r in conn.execute("SELECT vehicle_id FROM watchlist")}
    attrs = resolve_many(conn, [v["id"] for v in vehicles])
    stats = _obs_stats(conn)
    fa = finance.FinanceAssumptions.from_settings(settings["finance"])
    home_zip = settings.get("home_zip", "84020")
    priority = set(settings.get("priority_states") or [])
    recall_counts = recalls.counts_by_year(conn)
    events_by_vehicle: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT vehicle_id, event_type, old_value, new_value, created_at FROM change_events"
                          " WHERE event_type IN ('seller_change', 'returned')"):
        events_by_vehicle[r["vehicle_id"]].append(dict(r))
    progress = checklist.progress(conn)
    contact_info = checklist.contact_summary(conn)
    ship_cfg = settings.get("shipping") or {}
    link_checks = linkcheck.latest(conn)
    rows = []
    status_rank = {"active": 0, "missing": 1, "removed": 2}
    for v in vehicles:
        ls = listings_by_vehicle.get(v["id"], [])
        if not ls:
            continue
        ls.sort(key=lambda l: (status_rank.get(l["status"], 3), l["current_price"] or 10**9))
        best = ls[0]
        a = attrs.get(v["id"], {})
        get = lambda f: (a.get(f).value if a.get(f) else None)  # noqa: E731
        make, model = v["make"] or "", v["model"] or ""
        rivian = make.lower() == "rivian" and model.upper() == "R1T"
        miles = best["current_miles"]
        battery = get("battery") or "Unknown"
        _int = lambda v: int(v) if (v or "").isdigit() else None  # noqa: E731
        w = warranty.remaining(get("in_service_date"), miles, settings["warranty"], battery, motor=get("motor"),
                               comp_exp=get("warranty_expiration"), comp_miles=_int(get("warranty_miles")),
                               batt_exp=get("battery_warranty_expiration"),
                               batt_miles=_int(get("battery_warranty_miles")), use_rules=rivian)
        dist = distance_from_zip(home_zip, best["lat"], best["lon"], best["zip"], best["city"], best["state"])
        vehicle_ship_cfg = ship_cfg
        if not any(matches_target(make, model, t) for t in EV_TRUCK_PRESET):
            vehicle_ship_cfg = {**ship_cfg, "fly_drive": {**(ship_cfg.get("fly_drive") or {}), "enabled": False}}
        transport, transport_basis = shipping.estimate(best, dist, vehicle_ship_cfg, fa.default_transport_cost)
        seller_k = shipping.seller_key(best) or ""
        fin = finance.primary_summary(best["current_price"], fa, transport, seller_k)
        your_price = finance.best_price(best["current_price"], fa, seller_k)
        st = stats.get(best["id"], {})
        year = v["year"] or (int(get("model_year")) if get("model_year") else None)
        tonneau = get("tonneau") or "unknown"
        lk = links.pick_links(ls)
        fixed = get("seller_url")                     # you corrected (or removed) the seller link
        if fixed:
            lk = {**lk, "seller_url": "" if fixed == "none" else fixed, "seller_listing_id": None,
                  "seller_site": "" if fixed == "none" else links.listing_role(fixed, "dealer")[1],
                  "link_status": "seller" if fixed != "none" else ("aggregator only" if lk["found_on_url"] else "no link")}
        chk = link_checks.get(lk["seller_url"] or best["url"] or "") or {}
        fl = flips.detect(ls, events_by_vehicle.get(v["id"], []))
        dl, listed_since, listed_source = negotiation.days_listed(ls)
        last_drop = max((stats.get(l["id"], {}).get("last_drop_at") or "" for l in ls), default="") or None
        lev, lev_text = negotiation.leverage(dl, st.get("drops", 0), st.get("dropped", 0))
        row = {
            "vehicle_id": v["id"], "favorite": v["id"] in favorites, "is_demo": bool(v["is_demo"]),
            "custom_searches": settings.get("collection", {}).get("searches") is not None,
            "vin": v["vin"] or "", "vin_status": "validated" if v["vin"] else ("unverified: " + v["vin_raw"] if v["vin_raw"] else "none"),
            "year": year, "make": make, "model": model,
            "trim": get("trim") or v["trim"] or "", "generation": get("generation") or "Unknown",
            "battery": battery, "battery_src": _attr_text(a.get("battery")),
            "motor": get("motor") or "Unknown", "motor_src": _attr_text(a.get("motor")),
            "tonneau": tonneau, "tonneau_label": TONNEAU_STATUSES.get(tonneau, tonneau),
            "tonneau_src": _attr_text(a.get("tonneau")),
            "epa_range": int(get("epa_range")) if (get("epa_range") or "").isdigit() else None,
            "epa_range_verified": bool(a.get("epa_range") and a["epa_range"].confidence == "verified"),
            "tow_capacity_lbs": _int(get("tow_capacity_lbs")),
            "tow_src": _attr_text(a.get("tow_capacity_lbs")),
            "tow_conf": a["tow_capacity_lbs"].confidence if a.get("tow_capacity_lbs") else "",
            "tow_verified": bool(a.get("tow_capacity_lbs") and a["tow_capacity_lbs"].confidence == "verified"),
            "wheels": get("wheels") or "", "color": get("exterior_color") or best["exterior_color"] or "",
            "interior": get("interior_color") or "",
            "in_service_date": get("in_service_date") or "", "warranty": w["summary"],
            "warranty_months_left": w["comprehensive_months_left"], "warranty_basis": w["basis"],
            "warranty_expires": w["comprehensive_expires"] or "", "warranty_miles_limit": w["comprehensive_miles_limit"],
            "battery_warranty": (f"to {w['battery_expires'][:7]}" + (f", {w['battery_miles_left']:,} mi left"
                                 if w["battery_miles_left"] is not None else "")) if w["battery_expires"] else "",
            "title_status": get("title_status") or "unknown", "accident_history": get("accident_history") or "unknown",
            **(_subframe(v["vin"], get("front_subframe")) if rivian else
               {"subframe": "unknown", "subframe_note": "Rivian front-subframe rule does not apply"}),
            "price": best["current_price"], "miles": miles,
            "price_change": st.get("total_change", 0), "last_price_change": st.get("last_change", 0),
            "seller": best["seller_name"] or "", "seller_type": best["seller_type"] or "",
            "city": best["city"] or "", "state": best["state"] or "",
            "location": ", ".join(x for x in (best["city"], best["state"]) if x),
            "distance_mi": dist, "priority_state": (best["state"] or "") in priority,
            "url": best["url"] or "", "source": source_label(best["source_key"]), "source_key": best["source_key"],
            "source_count": len(ls), "active_listings": sum(1 for l in ls if l["status"] == "active"),
            "sources": ", ".join(sorted({source_label(l["source_key"]) for l in ls})),
            "all_urls": " ".join(l["url"] for l in ls if l["url"]),
            "first_seen": min(l["first_seen_at"] for l in ls), "last_seen": max(l["last_seen_at"] for l in ls),
            "status": best["status"], "status_reason": best["status_reason"] or "",
            "missing_since": best["missing_since"] or "",
            "transport_cost": transport, "transport_basis": transport_basis, "seller_key": seller_k,
            "your_price": your_price,
            "battery_options": _options(a.get("battery")), "motor_options": _options(a.get("motor")),
            "battery_uncertain": _uncertain(a.get("battery")), "battery_note": _who_says(a.get("battery")),
            "motor_uncertain": _uncertain(a.get("motor")), "motor_note": _who_says(a.get("motor")),
            "est_monthly": fin["est_monthly"], "cash_to_target": fin["cash_to_target"],
            "amount_financed": fin["amount_financed"], "total_cost": fin["total_cost"],
            "conflicts": ", ".join(sorted(f for f, r in a.items() if r.conflict)),
            "listing_id": best["id"], "notes": v["notes"] or "",
            "sold_by": links.display_name(lk["seller_listing_name"] or best["seller_name"], lk["seller_site"]),
            "seller_url": lk["seller_url"], "seller_site": lk["seller_site"], "found_on_url": lk["found_on_url"],
            "seller_listing_id": lk.get("seller_listing_id"), "seller_link_fixed": bool(fixed),
            "link_result": chk.get("result") or "", "link_note": chk.get("note") or "",
            "link_checked_at": chk.get("checked_at") or "",
            "found_on": lk["found_on"], "link_status": lk["link_status"], "dealer_website": lk["dealer_website"],
            "find_seller_url": "" if lk["seller_url"] and chk.get("result") not in linkcheck.PROBLEMS else (
                links.vin_search_url(v["vin"]) or links.dealer_search_url(best["seller_name"], best["city"], best["state"], make, model)
                or links.listing_search_url(year, best["current_price"], best["city"], best["state"], make, model)),
            "history_report_url": next((l["history_report_url"] for l in ls if l.get("history_report_url")), ""),
            "owners": get("owners") or "",
            "recall_count": recall_counts.get(year) if rivian else None,
            "recall_lookup_url": f"{recalls.VIN_LOOKUP}?vin={v['vin']}" if v["vin"] else recalls.VIN_LOOKUP,
            "seller_phone": next((l["seller_phone"] for l in ls if l.get("seller_phone")), ""),
            "photo_url": photos.best_url(v, ls) or "",
            "checklist": progress.get(v["id"], {}).get("text", ""),
            "checklist_problems": progress.get(v["id"], {}).get("problems", 0),
            "last_contact": (contact_info.get(v["id"], {}).get("last_contact") or ""),
            "follow_up": (contact_info.get(v["id"], {}).get("follow_up") or ""),
            "days_listed": dl, "listed_since": listed_since or "", "listed_source": listed_source,
            "price_drops": st.get("drops", 0), "dropped_total": st.get("dropped", 0), "last_drop_at": last_drop or "",
            "leverage": lev, "leverage_text": lev_text,
            "flip": fl["flip"], "flags": ", ".join(fl["flags"]), "flip_text": fl["text"],
            "hidden": bool(v.get("hidden_at")), "hidden_reason": v.get("hidden_reason") or "",
            "hidden_note": v.get("hidden_note") or "", "hidden_at": v.get("hidden_at") or "",
        }
        if not rivian:
            est = {"low": None, "high": None, "text": "", "basis": ""}
        elif row["battery_uncertain"]:
            spans = [epa.estimate(year, row["motor"], b, row["wheels"]) for b in row["battery_options"]]
            spans = [e for e in spans if e["low"]]
            est = ({"low": min(e["low"] for e in spans), "high": max(e["high"] for e in spans),
                    "text": f"{min(e['low'] for e in spans)}–{max(e['high'] for e in spans)}",
                    "basis": "EPA ratings for each battery the sources claim (battery uncertain) — fueleconomy.gov"}
                   if spans else {"low": None, "high": None, "text": "", "basis": ""})
        else:
            est = epa.estimate(year, row["motor"], battery, row["wheels"])
        row["epa_est_low"], row["epa_est_high"], row["epa_basis"] = est["low"], est["high"], est["basis"]
        rng, how = adjust.effective_range(row)        # same source the range penalty uses
        row["range_text"] = (f"{est['text']} est." if how == "est." else f"{rng:.0f} ({how})" if rng else "")
        row["range_source"] = how
        row["range_mi"] = rng
        row["trim_filter"] = trim_label(make, model, row["trim"])
        scope = settings.get("collection") or {}
        comparison_reasons = []
        if excluded_trim(make, model, row["trim"], scope.get("excluded_trims")):
            comparison_reasons.append(f"excluded trim: {row['trim_filter']}")
        if scope.get("exclude_standard_range", True) and standard_range(
                make, model, row["trim"], v["trim"], battery, *(l["title"] for l in ls)):
            comparison_reasons.append("Standard Range configuration excluded")
        if not rivian and scope.get("searches") is None:
            max_price = settings["filters"].get("max_price")
            if best["current_price"] is None or (max_price and best["current_price"] > max_price):
                comparison_reasons.append("outside comparison price limit or price unknown")
            if miles is None or miles > scope.get("other_max_miles", 45000):
                comparison_reasons.append("outside comparison mileage limit or mileage unknown")
            if dist is None or dist > scope.get("other_max_distance", 650):
                comparison_reasons.append("outside comparison distance limit or distance unknown")
            if rng is not None and rng < scope.get("other_min_range", 301):
                comparison_reasons.append("below comparison range preference")
        row["comparison_in_scope"] = not comparison_reasons
        row["comparison_excluded"] = "; ".join(comparison_reasons)
        row["fit_score"], row["fit_breakdown"] = fit_score(row, settings)
        row["adjusted_price"], row["adjust_note"] = adjust.adjusted(row, settings.get("adjustments"),
                                                                    settings.get("warranty"))
        row["to_confirm"] = ", ".join(adjust.to_confirm(row, settings.get("adjustments")))
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in ("year", "price", "miles", "epa_range", "range_mi", "tow_capacity_lbs", "distance_mi", "warranty_months_left", "est_monthly",
                "cash_to_target", "amount_financed", "total_cost", "transport_cost", "recall_count", "days_listed",
                "your_price"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = deals.annotate(df)
    return df.sort_values(["fit_score", "price"], ascending=[False, True], na_position="last").reset_index(drop=True)


def fit_score(row: dict, settings: dict) -> tuple[int, str]:
    """0–100 ranking aid built from stated preferences. Unknowns get neutral, not optimistic, credit."""
    f = settings["filters"]
    parts: list[tuple[str, float]] = []
    custom = settings.get("collection", {}).get("searches") is not None
    if not custom:
        parts.append(("tonneau", {"yes": 25, "unknown": 5, "no": 0}.get(row["tonneau"], 5)))
        parts.append(("battery", 6 if row.get("battery_uncertain") else
                      {"Max": 15, "Large+": 14, "Large": 13, "Standard+": 5, "Standard": 2}.get(row["battery"], 6)))
        parts.append(("motor", {"Quad": 8, "Performance Dual": 8, "Tri": 7, "Dual": 6}.get(row["motor"], 4)))
        wm = row.get("warranty_months_left")
        parts.append(("warranty", 12 * min(wm / 60, 1) if wm is not None else 4))
    price, max_price = row.get("price"), float(f.get("max_price") or 65000)
    parts.append(("price", 15 * max(0.0, min((max_price - price) / 15000, 1.0)) if price else 3))
    miles, max_miles = row.get("miles"), float(f.get("max_miles") or 40000)
    parts.append(("miles", 10 * max(0.0, min((max_miles - miles) / max_miles, 1.0)) if miles is not None else 3))
    dist = row.get("distance_mi")
    loc = 10 if row.get("priority_state") else (10 * max(0.0, 1 - dist / 1500) if dist is not None else 3)
    parts.append(("location", loc))
    hist = 0.0
    hist += {"clean": 3, "branded": -25}.get(row["title_status"], 0)
    hist += {"none_reported": 2, "reported": -10}.get(row["accident_history"], 0)
    parts.append(("history", hist))
    if custom:
        parts = [(k, p * (2 if k == "history" else 2.5)) for k, p in parts]
    total = max(0, min(100, round(sum(p for _, p in parts))))
    return total, " · ".join(f"{k} {p:+.0f}" for k, p in parts)


def _price_for_filter(df: pd.DataFrame, f: dict) -> pd.Series:
    if f.get("count_discounts", True) and "your_price" in df:
        return df["your_price"].where(df["your_price"].notna(), df["price"])
    return df["price"]


def _expand(allowed) -> set:
    allowed = set(allowed or [])
    if "Large" in allowed:
        allowed.add("Large+")
    return allowed


def _any_allowed(options: pd.Series, allowed: list) -> pd.Series:
    allowed = _expand(allowed)
    return options.map(lambda opts: bool(set(opts or []) & allowed))


def filter_checks(df: pd.DataFrame, f: dict) -> dict[str, pd.Series]:
    """Each filter as its own pass/fail Series, so we can say exactly why a truck is hidden."""
    checks: dict[str, pd.Series] = {}
    statuses = ["active", "missing", "removed"] if f.get("include_missing") else ["active"]
    checks["status"] = df["status"].isin(statuses)
    if f.get("hidden_only"):
        checks["hidden"] = df["hidden"]
    elif not f.get("show_hidden"):
        checks["hidden"] = ~df["hidden"]
    if not f.get("show_demo", True):
        checks["demo"] = ~df["is_demo"]
    make = df["make"].fillna("Rivian").str.lower() if "make" in df else pd.Series("rivian", index=df.index)
    model = df["model"].fillna("R1T").str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    rivian = make.eq("rivian") & model.eq("r1t")
    checks["model"] = (rivian | (make.eq("ford") & model.eq("f150lightning"))
                       | (make.eq("chevrolet") & model.eq("silveradoev"))
                       | (make.eq("gmc") & model.eq("sierraev")))
    if "custom_searches" in df:
        checks["model"] |= df["custom_searches"].fillna(False).astype(bool)
    if f.get("models"):
        checks["selected model"] = df["model"].str.casefold().isin([m.casefold() for m in f["models"]])
    if f.get("brands"):
        checks["brand"] = make.isin([b.lower() for b in f["brands"]])
    if f.get("trims"):
        checks["trim"] = df["trim_filter"].isin(f["trims"])
    if "comparison_in_scope" in df:
        checks["comparison"] = df["comparison_in_scope"]
    yr = df["year"]
    checks["year"] = yr.isna() | ((yr >= f.get("year_min", 0)) & (yr <= f.get("year_max", 9999)))
    checks["generation"] = ~rivian | df["generation"].isin(f.get("generations") or [])
    if f.get("max_price"):
        price = _price_for_filter(df, f)
        checks["price"] = price.isna() | (price <= f["max_price"])
    if f.get("max_miles"):
        checks["miles"] = df["miles"].isna() | (df["miles"] <= f["max_miles"])
    # When sources disagree (e.g. "Standard Pack" vs "Dual Large"), any claimed value counts: never hide on doubt.
    checks["battery"] = ~rivian | df["battery"].isin(_expand(f.get("batteries"))) | (
        _any_allowed(df["battery_options"], f.get("batteries")) if "battery_options" in df else False)
    checks["motor"] = ~rivian | df["motor"].isin(f.get("motors") or []) | (
        _any_allowed(df["motor_options"], f.get("motors")) if "motor_options" in df else False)
    checks["tonneau"] = df["tonneau"].isin(f.get("tonneau") or [])
    if f.get("states"):
        checks["states"] = df["state"].isin(f["states"])
    if f.get("max_distance"):
        checks["distance"] = df["distance_mi"].isna() | (df["distance_mi"] <= f["max_distance"])
    if f.get("subframes") and set(f["subframes"]) != set(subframe.LABELS):
        checks["subframe"] = ~rivian | df["subframe"].isin(f["subframes"])
    if f.get("min_range"):
        rng = df["range_mi"] if "range_mi" in df else df["epa_range"]
        checks["range"] = (rng >= f["min_range"]) | (rng.isna() & f.get("include_unknown_range", True))
    elif not f.get("include_unknown_range", True):
        rng = df["range_mi"] if "range_mi" in df else df["epa_range"]
        checks["range"] = rng.notna()
    if f.get("hide_branded_title"):
        checks["title"] = df["title_status"] != "branded"
    if f.get("hide_reported_accidents"):
        checks["accidents"] = df["accident_history"] != "reported"
    if f.get("favorites_only"):
        checks["favorites"] = df["favorite"]
    return checks


def near_miss_mask(df: pd.DataFrame, f: dict) -> pd.Series:
    """Trucks that fail ONLY the price and/or mileage limit, and only by a little."""
    if df.empty:
        return pd.Series(False, index=df.index)
    checks = filter_checks(df, f)
    others = pd.Series(True, index=df.index)
    for name, ok in checks.items():
        if name not in ("price", "miles"):
            others &= ok
    price_ok = checks.get("price", pd.Series(True, index=df.index))
    miles_ok = checks.get("miles", pd.Series(True, index=df.index))
    price = _price_for_filter(df, f)
    p_lim = (f.get("max_price") or 0) * (1 + (f.get("near_miss_price_pct", 5) or 0) / 100)
    m_lim = (f.get("max_miles") or 0) * (1 + (f.get("near_miss_miles_pct", 10) or 0) / 100)
    price_close = price_ok | (price <= p_lim)
    miles_close = miles_ok | (df["miles"] <= m_lim)
    return others & ~(price_ok & miles_ok) & price_close & miles_close


def why_hidden(row: pd.Series, f: dict) -> list[str]:
    """Plain-English reasons a truck isn't in the filtered list (empty = it shows)."""
    df = row.to_frame().T.infer_objects()
    checks = filter_checks(df, f)
    out = []
    for name, ok in checks.items():
        if bool(ok.iloc[0]):
            continue
        if name == "price":
            p = _price_for_filter(df, f).iloc[0]
            extra = f" (your price after discounts: ${p:,.0f})" if p != row["price"] else ""
            out.append(f"price ${row['price']:,.0f}{extra} is ${p - f['max_price']:,.0f} over your ${f['max_price']:,.0f} max")
        elif name == "miles":
            out.append(f"{row['miles']:,.0f} miles is {row['miles'] - f['max_miles']:,.0f} over your {f['max_miles']:,.0f} max")
        elif name == "battery":
            out.append(f"battery is {row['battery']} (your filter: {', '.join(f.get('batteries') or [])})")
        elif name == "motor":
            out.append(f"motor is {row['motor']} (your filter: {', '.join(f.get('motors') or [])})")
        elif name == "status":
            out.append(f"listing status is {row['status']}" + (f" — {row['status_reason']}" if row.get("status_reason") else ""))
        elif name == "hidden":
            out.append("you marked it Not interested" if row["hidden"] else "it's not one of your hidden trucks")
        elif name == "year":
            out.append(f"model year {int(row['year'])} is outside {f.get('year_min')}–{f.get('year_max')}")
        elif name == "subframe":
            out.append(f"front subframe is {subframe.LABELS.get(row['subframe'], row['subframe']).lower()} "
                       f"(your filter: {', '.join(subframe.LABELS[k] for k in f['subframes'] if k in subframe.LABELS)})")
        elif name == "title":
            out.append("branded title (you hide those)")
        elif name == "accidents":
            out.append("accident reported (you hide those)")
        elif name == "comparison":
            out.append(row.get("comparison_excluded") or "outside comparison limits")
        elif name == "trim":
            out.append(f"trim {row['trim_filter']} is outside your selected trims")
        elif name == "range":
            out.append(f"range below {f.get('min_range', 0)} mi or unknown (check range filters)")
        else:
            out.append(f"{name} filter")
    return out


def find_trucks(df: pd.DataFrame, text: str) -> pd.DataFrame:
    """Find trucks by VIN, listing URL, or listing number — regardless of filters."""
    from .extract import canonical_url
    from .vin import clean_vin
    q = (text or "").strip()
    if not q or df.empty:
        return df.iloc[0:0]
    vin = clean_vin(q)
    if len(vin) == 17:
        return df[df["vin"] == vin]
    if q.lower().startswith(("http://", "https://")):
        canon = canonical_url(q)
        hit = df["all_urls"].map(lambda urls: canon in {canonical_url(u) for u in (urls or "").split()})
        if hit.any():
            return df[hit]
        from urllib.parse import urlsplit
        q = urlsplit(q).path.rstrip("/").split("/")[-1] or q     # fall back to the listing number at the end
        if not q or q == text.strip():
            return df.iloc[0:0]
    return df[df["all_urls"].str.contains(q, regex=False) | df["vin"].str.contains(q.upper(), regex=False)]


def apply_filters(df: pd.DataFrame, f: dict, search: str = "") -> pd.DataFrame:
    if df.empty:
        return df
    m = pd.Series(True, index=df.index)
    for ok in filter_checks(df, f).values():
        m &= ok
    if f.get("near_misses") and not f.get("hidden_only"):
        m |= near_miss_mask(df, f)
    if search:
        s = search.lower()
        hay = (df["vin"] + " " + df["seller"] + " " + df["location"] + " " + df["color"] + " " + df["trim"]
               + " " + df["make"] + " " + df["model"]
               + " " + df["sources"] + " " + df["notes"]).str.lower()
        m &= hay.str.contains(s, regex=False)
    return df[m]


def events_frame(conn: sqlite3.Connection, run_id: int | None = None, since: str | None = None,
                 types: list[str] | None = None) -> pd.DataFrame:
    q = ("SELECT e.*, l.url, l.source_key, l.seller_name, l.city, l.state, l.current_price, l.current_miles,"
         " l.is_demo, v.vin, v.year, v.model FROM change_events e LEFT JOIN listings l ON l.id = e.listing_id"
         " LEFT JOIN vehicles v ON v.id = e.vehicle_id WHERE 1=1")
    params: list = []
    if run_id is not None:
        q += " AND e.run_id = ?"
        params.append(run_id)
    if since:
        q += " AND e.created_at >= ?"
        params.append(since)
    if types:
        q += f" AND e.event_type IN ({','.join('?' * len(types))})"
        params += types
    q += " ORDER BY e.id DESC"
    df = pd.read_sql_query(q, conn, params=params)
    if not df.empty:
        df["event"] = df["event_type"].map(EVENT_LABELS).fillna(df["event_type"])
        df["source"] = df["source_key"].map(source_label)
    return df


def price_history(conn: sqlite3.Connection, vehicle_id: int) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT o.observed_at, o.price, o.miles, o.available, o.import_method, l.id AS listing_id, l.source_key,"
        " l.seller_name, l.url FROM observations o JOIN listings l ON l.id = o.listing_id"
        " WHERE l.vehicle_id = ? ORDER BY o.observed_at, o.id", conn, params=[vehicle_id])


def latest_runs(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)):
        d = dict(r)
        d["summary"] = json.loads(d.get("summary_json") or "{}")
        out.append(d)
    return out


def last_search_run(conn: sqlite3.Connection) -> dict | None:
    r = conn.execute("SELECT * FROM runs WHERE trigger='run_search' AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    d = dict(r)
    d["summary"] = json.loads(d.get("summary_json") or "{}")
    return d


def source_status(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT s.key, s.name, s.kind, s.enabled, s.last_attempt_at, s.last_success_at, s.last_status, s.last_error,"
        " (SELECT COUNT(*) FROM listings l WHERE l.source_key = s.key AND l.status='active') AS active_listings,"
        " (SELECT COUNT(*) FROM listings l WHERE l.source_key = s.key AND l.status='missing') AS missing_listings,"
        " (SELECT notes FROM source_runs sr WHERE sr.source_key = s.key ORDER BY sr.id DESC LIMIT 1) AS last_notes,"
        " (SELECT complete FROM source_runs sr WHERE sr.source_key = s.key ORDER BY sr.id DESC LIMIT 1) AS last_complete"
        " FROM sources s ORDER BY s.kind, s.name", conn)
    return df


def api_calls_this_month(conn: sqlite3.Connection, source_key: str) -> int:
    from datetime import datetime, timezone
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return conn.execute("SELECT COUNT(*) FROM api_usage WHERE source_key=? AND substr(called_at,1,7)=?",
                        (source_key, month)).fetchone()[0]


def api_budget(conn: sqlite3.Connection, source_key: str, monthly_cap: int) -> dict:
    """Calls used this month, what the last complete run cost, and how many such runs are left."""
    used = api_calls_this_month(conn, source_key)
    last = conn.execute(
        "SELECT api_calls, listings_seen, finished_at FROM source_runs WHERE source_key=? AND complete=1"
        " AND api_calls > 0 ORDER BY id DESC LIMIT 1", (source_key,)).fetchone()
    per_run = int(last["api_calls"]) if last else None
    left = max(monthly_cap - used, 0)
    return {"used": used, "cap": monthly_cap, "left": left, "per_run": per_run,
            "runs_left": (left // per_run) if per_run else None,
            "last_run_listings": int(last["listings_seen"]) if last else None}


def summary_text(summary: dict, matching: int | None) -> str:
    c = summary.get("counts", {})
    parts = []
    if matching is not None:
        parts.append(f"{matching} matching vehicle{'s' if matching != 1 else ''}")
    parts.append(f"{c.get('new_listing', 0)} new")
    if c.get("new_source_for_vin"):
        parts.append(f"{c['new_source_for_vin']} new source listing(s) for known VINs")
    parts.append(f"{c.get('price_drop', 0)} price reduction{'s' if c.get('price_drop', 0) != 1 else ''}")
    if c.get("price_increase"):
        parts.append(f"{c['price_increase']} price increase(s)")
    parts.append(f"{c.get('disappeared', 0)} missing since last successful scan")
    if c.get("returned"):
        parts.append(f"{c['returned']} returned")
    text = ", ".join(parts) + "."
    if c.get("hidden_vehicle_updates"):
        text += f" ({c['hidden_vehicle_updates']} update(s) on trucks you marked not interested.)"
    problems = [s for s in summary.get("sources", []) if s.get("status") in ("failed", "partial", "skipped")]
    for s in problems:
        what = {"failed": "failed", "partial": "incomplete", "skipped": "skipped"}[s["status"]]
        text += f" {s.get('name', s['source'])} {what}"
        if s.get("error"):
            text += f" ({s['error']})"
        text += " — previous listings left unchanged." if s["status"] != "skipped" else "."
    return text


def label_title(v: str) -> str:
    return TITLE_STATUSES.get(v, v)


def label_accidents(v: str) -> str:
    return ACCIDENT_STATUSES.get(v, v)
