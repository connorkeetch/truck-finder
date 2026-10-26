"""Vehicle details: every source, price history, equipment verification, conflicts, notes, financing."""
from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from .. import attributes, checklist, compare, dedup, finance, hiding, links, photos, pipeline, queries, recalls, services, shipping
from ..geo import distance_from_zip
from ..config import ACCIDENT_STATUSES, BATTERIES, GENERATIONS, MOTORS, TITLE_STATUSES, TONNEAU_STATUSES
from ..extract import RIVIAN_COLORS
from . import common, price_insights

FIELD_LABELS = {
    "generation": "Generation", "model_year": "Model year", "trim": "Trim", "vpic_trim": "Trim (NHTSA)",
    "battery": "Battery", "motor": "Motor", "tonneau": "Powered tonneau", "tonneau_mention": "Tonneau mention",
    "epa_range": "EPA range (mi)", "tow_capacity_lbs": "Tow capacity (lb)", "wheels": "Wheels", "exterior_color": "Exterior color",
    "interior_color": "Interior", "in_service_date": "In-service date", "warranty_expiration": "Warranty expiration",
    "title_status": "Title", "accident_history": "Accident history", "plant": "Assembly plant",
    "vpic_decoded": "NHTSA decode date", "vin_conflict": "Conflicting VIN reported", "owners": "Owners",
    "warranty_miles": "Comprehensive warranty miles", "battery_warranty_expiration": "Battery warranty expiration",
    "battery_warranty_miles": "Battery warranty miles", "mc_decoded": "MarketCheck decode date",
}
VALUE_LABELS = {"tonneau": TONNEAU_STATUSES, "title_status": TITLE_STATUSES, "accident_history": ACCIDENT_STATUSES}
NO_OVERRIDE = "(not verified — use sources)"


def _label(field: str, value) -> str:
    if value in (None, ""):
        return "Unknown"
    return VALUE_LABELS.get(field, {}).get(value, str(value))


def render() -> None:
    c = common.conn()
    s = common.settings()
    inv = common.inventory(s)
    st.title("Vehicle details")
    if inv.empty:
        st.info("No vehicles yet.")
        return
    ids = inv["vehicle_id"].tolist()
    labels = {int(r["vehicle_id"]): common.vehicle_label(r) for _, r in inv.iterrows()}
    sel = st.session_state.get("selected_vehicle")
    if sel not in labels:
        sel = ids[0]
    vid = st.selectbox("Vehicle", ids, index=ids.index(sel), format_func=lambda i: labels[i], key="veh_select")
    st.session_state["selected_vehicle"] = vid
    render_truck(c, s, inv, vid)


def warranty_line(row) -> None:
    """One line of warranty info above the notes (details live in Quick verify / Overview)."""
    from .. import warranty as w
    ends = w.ends_text(row.get("warranty_expires"), row.get("warranty_miles_limit"))
    if ends:
        left = (row.get("warranty") or "").split(" (to ")[0]
        st.markdown(f"🛡️ **Warranty:** ends {ends} · {left}" + (f"  \n<small>Based on {row['warranty_basis']}</small>"
                                                                  if row.get("warranty_basis") else ""),
                    unsafe_allow_html=True)
    else:
        st.markdown("🛡️ **Warranty:** unknown — " + ("add the in-service date or paste the warranty lines in Quick verify."
                    if row.get("make") == "Rivian" else "paste this truck's actual warranty dates and mileage limits in Quick verify."))


def notes_box(c, vid: int, current: str | None) -> None:
    """Free-form notes for this truck — saved as soon as you click away."""
    key = f"notes_box_{vid}_{abs(hash(current or '')) % 10**8}"     # fresh box if the notes changed elsewhere

    def _save() -> None:
        # No st.toast here: this runs inside the details pop-up's own refresh, where drawing from a callback
        # crashes the page. The confirmation is shown below instead.
        with c:
            c.execute("UPDATE vehicles SET notes=? WHERE id=?", ((st.session_state.get(key) or "").strip(), vid))
        st.session_state[f"notes_saved_{vid}"] = True

    st.text_area("📝 Notes", current or "", key=key, height=110, on_change=_save,
                 placeholder="Anything you learn — tonneau, condition, what the seller said, questions to ask…",
                 help="Saved automatically when you click outside the box (or press Ctrl+Enter). Also shown in the "
                      "Inventory table's Notes column.")
    if st.session_state.pop(f"notes_saved_{vid}", False):
        st.caption("✓ Notes saved")


def favorite_and_hide(c, row, vid: int, where) -> None:
    """★ Favorite and 🚫 Not interested, at the top of the truck's details."""
    f1, f2 = where.columns([1, 1.6])
    fav = f1.toggle("★ Favorite", bool(row["favorite"]), key=f"fav_{vid}")
    if fav != bool(row["favorite"]):
        services.toggle_favorite(c, vid, fav)
        st.rerun()
    if row["hidden"]:
        return
    with f2.popover("🚫 Not interested…", width="stretch"):
        st.caption("Hides this truck everywhere (including if it's relisted on another site). 'Title issues' also "
                   "records the title as branded; 'Sold / dead link' marks its listings removed.")
        reason = st.selectbox("Reason", list(hiding.HIDE_REASONS), format_func=hiding.reason_label,
                              key=f"hide_reason_{vid}")
        note = st.text_input("Note (optional)", key=f"hide_note_{vid}",
                             placeholder="e.g. Carfax shows rebuilt title from 2024 flood claim")
        if st.button("Hide this truck", type="primary", key=f"hide_{vid}"):
            hiding.hide_vehicle(c, vid, reason, note)
            common.flash(f"Hidden: {hiding.reason_label(reason)}. Find it again under Inventory → 🚫 Hidden.", "info")
            st.session_state.pop("dialog_vid", None)        # close the Inventory pop-up
            st.rerun()


def render_truck(c, s, inv, vid: int) -> None:
    """Everything about one truck. Used by the Vehicle details page and the Inventory pop-up."""
    row = inv[inv["vehicle_id"] == vid].iloc[0]
    is_rivian = row.get("make") == "Rivian"
    vehicle = c.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    resolved = attributes.resolve(c, vid)

    src = common.photo_image(vid, row["photo_url"])
    pic, head = st.columns([1.15, 3])
    head.subheader(compare.vehicle_name(row))
    if src:
        pic.image(src, width="stretch")
    else:
        pic.caption("No photo yet")
    with pic.popover("📷 Change photo" if src else "📷 Add photo", width="stretch"):
        photo_form(c, vid, row)
    badges = []
    if row["is_demo"]:
        badges.append("<span class='rf-badge rf-demo'>DEMO — synthetic data</span>")
    badges.append(f"<span class='rf-badge'>{row['status']}</span>")
    badges.append(f"<span class='rf-badge'>{row['generation']}</span>")
    badges.append(f"<span class='rf-badge'>VIN {row['vin'] or '— (' + row['vin_status'] + ')'}</span>")
    head.markdown(" ".join(badges), unsafe_allow_html=True)
    if row["status"] != "active" and row["status_reason"]:
        head.warning(row["status_reason"])

    m = head.columns(3) + head.columns(3)
    m[0].metric("Price", common.money(row["price"]),
                delta=f"{row['price_change']:+,.0f} since first seen" if row["price_change"] else None,
                delta_color="inverse")
    m[1].metric("Mileage", common.miles(row["miles"]))
    m[2].metric("Est. monthly", common.money(row["est_monthly"]),
                help="Primary scenario from Settings → Loan assumptions")
    m[3].metric("Cash for target payment", common.money(row["cash_to_target"]))
    m[4].metric("Distance", f"{row['distance_mi']:,.0f} mi" if pd.notna(row["distance_mi"]) else "—")
    m[5].metric("Personal score", int(row.get("match_score") or 0), help="How this truck fits your shopping profile and saved limits.")
    head.markdown(f"**Personal match: {row.get('match_status') or 'Needs verification'}**")
    if row.get("match_failures"):
        head.warning("Does not meet: " + "; ".join(row["match_failures"]))
    if row.get("match_missing"):
        head.caption("Need proof: " + "; ".join(row["match_missing"]))
    favorite_and_hide(c, row, vid, head)

    if row["hidden"]:
        h1, h2 = st.columns([5, 1])
        h1.warning(f"🚫 **Not interested:** {hiding.reason_label(row['hidden_reason'])}"
                   + (f" — {row['hidden_note']}" if row["hidden_note"] else "")
                   + f" (since {common.local_time(row['hidden_at'])}). Hidden from Dashboard, Inventory and Excel.")
        if h2.button("↩ Restore", key=f"restore_{vid}", width="stretch"):
            hiding.restore_vehicle(c, vid)
            st.rerun()

    where_sold(c, row, vid)
    deal_strip(row)
    negotiation_strip(row)
    quick_verify(c, vid, row)
    warranty_line(row)
    notes_box(c, vid, vehicle["notes"])

    (t_overview, t_verify, t_prices, t_listings, t_history, t_finance, t_checklist, t_identity,
     t_log) = st.tabs(["Overview", "Verify equipment", "Price history", "Listings & sources", "History & recalls",
                       "Financing", "Checklist & contacts", "Photo & identity", "Change log"])

    # ---------------------------------------------------------- overview
    with t_overview:
        st.caption(f"Legacy fit score: {row['fit_score']}/100 · {row['fit_breakdown']}")
        rows = []
        for f in ["model_year", "generation", "trim", "vpic_trim", "battery", "motor", "tonneau", "tonneau_mention",
                  "epa_range", "tow_capacity_lbs", "wheels", "exterior_color", "interior_color", "in_service_date", "warranty_expiration",
                  "warranty_miles", "battery_warranty_expiration", "battery_warranty_miles",
                  "title_status", "accident_history", "owners", "plant"]:
            r = resolved.get(f)
            if r is None or (r.value in (None, "") and f not in ("battery", "motor", "tonneau", "epa_range", "tow_capacity_lbs",
                                                                  "in_service_date", "title_status", "accident_history")):
                continue
            rows.append({"Field": FIELD_LABELS.get(f, f), "Value": _label(f, r.value),
                         "Source": queries.source_label(r.source) or "—", "Confidence": r.confidence or "—",
                         "How we know": r.method, "Evidence": r.evidence or "", "Conflict": "⚠️" if r.conflict else ""})
        st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
            "Evidence": st.column_config.TextColumn(width="large"), "How we know": st.column_config.TextColumn(width="medium")})
        st.markdown(f"**Warranty remaining:** {row['warranty']}"
                    + (f"  \n<small>Based on {row['warranty_basis']}</small>" if row["warranty_basis"] else ""),
                    unsafe_allow_html=True)
        if row["epa_basis"]:
            st.markdown(f"**EPA range:** {row['range_text']}  \n<small>{row['epa_basis']}</small>",
                        unsafe_allow_html=True)
        if row["vin"] and st.button("Look up listed specifications (1 API call)", key=f"mc2_{vid}"):
            from .. import enrich
            res = enrich.mc_second_opinion(c, vid, max_calls=1)
            common.flash(("MarketCheck says: " + (res.get("version") or "no version info")
                          + (f", EPA {res['epa_range']} mi" if res.get("epa_range") else "")) if res.get("ok")
                         else f"MarketCheck lookup failed: {res.get('error')}", "info" if res.get("ok") else "error")
            st.rerun()
        st.caption("Confidence: verified = you checked it · high = manufacturer/VIN data · medium = structured "
                   "listing field · low = parsed from listing text. Unknown means no source has said.")
        st.caption("Tow capacity must match this truck's battery, configuration and tow package. Verify its rating and payload from the sticker or manufacturer before towing.")
        conflicts = {f: r for f, r in resolved.items() if r.conflict}
        if conflicts:
            st.subheader("⚠️ Source conflicts")
            for f, r in conflicts.items():
                st.markdown(f"**{FIELD_LABELS.get(f, f)}** — using *{_label(f, r.value)}* ({queries.source_label(r.source)})")
                st.dataframe(pd.DataFrame([{"Value": _label(f, a["value"]), "Source": queries.source_label(a["source"]),
                                            "Confidence": a["confidence"], "Method": a["method"],
                                            "Evidence": a["evidence"] or "", "Seen": a["observed_at"][:10]}
                                           for a in r.alternatives]), hide_index=True)

    # ---------------------------------------------------------- verification
    with t_verify:
        st.write("Record what **you** have verified (in person, from the seller, a Carfax report or the manufacturer). "
                 "Verified values always override source data and are never overwritten by later scans.")
        overrides = {r["field"]: dict(r) for r in c.execute("SELECT * FROM user_overrides WHERE vehicle_id=?", (vid,))}
        with st.form(f"verify_{vid}"):
            def pick(field, options, fmt=None, col=st):
                cur = overrides.get(field, {}).get("value")
                opts = [NO_OVERRIDE] + options
                return col.selectbox(FIELD_LABELS[field], opts, index=opts.index(cur) if cur in opts else 0,
                                     format_func=(lambda o: o if o == NO_OVERRIDE else (fmt(o) if fmt else o)),
                                     key=f"ov_{field}_{vid}")
            c1, c2 = st.columns(2)
            ton = pick("tonneau", list(TONNEAU_STATUSES), lambda k: TONNEAU_STATUSES[k], c1)
            bat = (pick("battery", [b for b in BATTERIES if b != "Unknown"], col=c2) if is_rivian else
                   c2.text_input("Battery — blank = use sources", overrides.get("battery", {}).get("value") or "", key=f"ov_bat_{vid}"))
            mot = (pick("motor", [x for x in MOTORS if x != "Unknown"], col=c1) if is_rivian else
                   c1.text_input("Motor — blank = use sources", overrides.get("motor", {}).get("value") or "", key=f"ov_mot_{vid}"))
            gen = (pick("generation", [g for g in GENERATIONS if g != "Unknown"], col=c2) if is_rivian else
                   overrides.get("generation", {}).get("value"))
            title = pick("title_status", [k for k in TITLE_STATUSES if k != "unknown"], lambda k: TITLE_STATUSES[k], c1)
            acc = pick("accident_history", [k for k in ACCIDENT_STATUSES if k != "unknown"],
                       lambda k: ACCIDENT_STATUSES[k], c2)
            color = (pick("exterior_color", RIVIAN_COLORS, col=c1) if is_rivian else
                     c1.text_input("Exterior color — blank = use sources", overrides.get("exterior_color", {}).get("value") or "", key=f"ov_color_{vid}"))
            rng_cur = overrides.get("epa_range", {}).get("value")
            rng = c2.number_input("EPA range (mi) — 0 = not verified", 0, 600, int(rng_cur) if rng_cur else 0, key=f"ov_rng_{vid}")
            tow_cur = overrides.get("tow_capacity_lbs", {}).get("value")
            tow = c1.number_input("Tow capacity (lb) — 0 = not verified", 0, 40000, int(tow_cur) if tow_cur else 0,
                                   100, key=f"ov_tow_{vid}")
            wheels = c1.text_input("Wheels", overrides.get("wheels", {}).get("value", ""), key=f"ov_wh_{vid}")
            isd_cur = overrides.get("in_service_date", {}).get("value")
            isd = c2.date_input("In-service date", date.fromisoformat(isd_cur) if isd_cur else None, key=f"ov_isd_{vid}", format="MM/DD/YYYY",
                                min_value=date(2021, 1, 1), max_value=date.today())
            wexp_cur = overrides.get("warranty_expiration", {}).get("value")
            wexp = c1.date_input("Comprehensive warranty expiration", date.fromisoformat(wexp_cur) if wexp_cur else None, format="MM/DD/YYYY",
                                 key=f"ov_wexp_{vid}", min_value=date(2021, 1, 1), max_value=date(2040, 12, 31))
            note = c2.text_input("Verification note (how you verified)", key=f"ov_note_{vid}")
            if st.form_submit_button("Save verified values", type="primary"):
                values = {"tonneau": ton, "battery": bat, "motor": mot, "generation": gen, "title_status": title,
                          "accident_history": acc, "exterior_color": color,
                          "epa_range": str(rng) if rng else None, "tow_capacity_lbs": str(tow) if tow else None,
                          "wheels": wheels.strip() or None,
                          "in_service_date": isd.isoformat() if isd else None,
                          "warranty_expiration": wexp.isoformat() if wexp else None}
                for field, val in values.items():
                    val = None if val in (NO_OVERRIDE, "") else val
                    prev = overrides.get(field, {}).get("value")
                    if val != prev:
                        attributes.set_override(c, vid, field, val, note)
                st.success("Saved.")
                st.rerun()

    # ---------------------------------------------------------- price history
    with t_prices:
        price_insights.render(c, vid)
        ph = queries.price_history(c, vid)
        if ph.empty:
            st.write("No observations yet.")
        else:
            ph["when"] = pd.to_datetime(ph["observed_at"])
            ph["listing"] = ph.apply(lambda r: f"{queries.source_label(r['source_key'])} · {r['seller_name'] or 'seller ?'} (#{r['listing_id']})", axis=1)
            chart = alt.Chart(ph.dropna(subset=["price"])).mark_line(point=True, interpolate="step-after").encode(
                x=alt.X("when:T", title="Observed"), y=alt.Y("price:Q", title="Price ($)", scale=alt.Scale(zero=False)),
                color=alt.Color("listing:N", title="Listing"),
                tooltip=["when:T", alt.Tooltip("price:Q", format="$,.0f"), alt.Tooltip("miles:Q", format=",.0f"), "listing:N"])
            st.altair_chart(chart, width="stretch")
            show = ph[["observed_at", "price", "miles", "listing", "import_method", "available"]].copy()
            show["observed_at"] = show["observed_at"].map(common.local_time)
            st.dataframe(show.iloc[::-1], hide_index=True, column_config={
                "observed_at": "Observed", "price": st.column_config.NumberColumn("Price", format="dollar", step=1),
                "miles": st.column_config.NumberColumn("Miles", format="%,d"), "import_method": "Method",
                "available": st.column_config.CheckboxColumn("Available")})

    # ---------------------------------------------------------- listings
    with t_listings:
        listings = c.execute("SELECT * FROM listings WHERE vehicle_id=? ORDER BY status, current_price", (vid,)).fetchall()
        for l in listings:
            role, role_label = links.listing_role(l["url"], l["seller_type"])
            with st.container(border=True):
                a, b = st.columns([4, 2])
                tag = {"seller": "🏷️ Seller's listing", "aggregator": "🔁 Aggregator (re-listing)",
                       "none": "No URL"}[role]
                a.markdown(f"<span class='rf-badge'>{tag}</span> <small>{role_label}</small>", unsafe_allow_html=True)
                a.markdown(f"**{queries.source_label(l['source_key'])}** · {l['seller_name'] or 'Unknown seller'}"
                           f" ({l['seller_type'] or 'unknown'}) · {', '.join(x for x in (l['city'], l['state'], l['zip']) if x) or 'location ?'}  \n"
                           f"{common.money(l['current_price'])} · {common.miles(l['current_miles'])} · "
                           f"status **{l['status']}** · via {l['import_method']}  \n"
                           f"<small>First seen {common.local_time(l['first_seen_at'])} · last seen "
                           f"{common.local_time(l['last_seen_at'])}</small>", unsafe_allow_html=True)
                if l["url"]:
                    b.link_button("Open seller's listing ↗" if role == "seller" else f"Open on {role_label} ↗",
                                  l["url"], width="stretch")
                if l["dealer_website"]:
                    b.link_button("Dealer website ↗", l["dealer_website"], width="stretch")
                if l["status_reason"]:
                    a.caption(l["status_reason"])
                t1, t2 = b.columns(2)
                d_l = distance_from_zip(s["home_zip"], l["lat"], l["lon"], l["zip"], l["city"], l["state"])
                est, basis = shipping.estimate({**dict(l), "transport_cost": None}, d_l, s.get("shipping"),
                                               s["finance"].get("default_transport_cost", 0))
                tc = t1.number_input("Transport $", min_value=0, max_value=30000, value=l["transport_cost"], step=50,
                                     key=f"tc_{l['id']}", placeholder=f"est. {est:,.0f}",
                                     help=common.md(f"Leave blank to use the estimate: ${est:,.0f} — {basis}"))
                if tc != l["transport_cost"]:
                    with c:
                        c.execute("UPDATE listings SET transport_cost=? WHERE id=?", (tc, l["id"]))
                    st.rerun()
                b.caption(common.md(f"Transport: {basis if l['transport_cost'] is None else 'your amount'}"
                          + (f" (estimate ${est:,.0f})" if l["transport_cost"] is not None else f" → ${est:,.0f}")))
                if l["status"] != "removed" and t2.button("Mark sold", key=f"rm_{l['id']}"):
                    pipeline.mark_removed(c, l["id"])
                    st.rerun()
                if l["description"]:
                    with a.expander("Listing text"):
                        st.text(l["description"][:5000])

    # ---------------------------------------------------------- history & recalls
    with t_history:
        history_tab(c, row, vid)

    # ---------------------------------------------------------- financing
    with t_finance:
        if not row["price"]:
            st.write("No price known.")
        else:
            fa = finance.FinanceAssumptions.from_settings(s["finance"])
            rows = []
            for sc in finance.all_scenarios(float(row["price"]), fa, float(row["transport_cost"] or 0)):
                base = {"Scenario": sc.label, "Taxable": sc.taxable_amount, "Sales tax": sc.sales_tax,
                        "Fees": sc.fees, "Transport": sc.transport, "Equity applied": sc.equity,
                        "Total cost": sc.total_acquisition_cost, "Financed": sc.amount_financed}
                for k in sc.payments:
                    term, apr = k.split("@")
                    rows.append({**base, "Term": int(term), "APR %": float(apr), "Monthly": sc.payments[k],
                                 f"Cash to hit ${fa.target_monthly:,.0f}": sc.cash_to_target[k],
                                 "Total interest": sc.total_interest[k]})
            fdf = pd.DataFrame(rows)
            money_cols = [col for col in fdf.columns if col not in ("Scenario", "Term", "APR %")]
            st.dataframe(fdf, hide_index=True, column_config={
                **{col: st.column_config.NumberColumn(col, format="dollar", step=1) for col in money_cols},
                "Monthly": st.column_config.NumberColumn("Monthly", format="dollar", step=0.01)})
            st.caption("Trade-in scenarios reduce the taxable price only if 'Dealer trade-in reduces taxable price' is on; "
                       "the separate cash sale does not by default. Edit assumptions in Settings → Loan assumptions.")

    with t_checklist:
        checklist_tab(c, vid, row)

    # ---------------------------------------------------------- notes & identity
    with t_identity:
        photo_manager(c, vid, row)
        if not vehicle["vin"]:
            st.subheader("Add VIN")
            st.write("This vehicle has no validated VIN, so it can't be matched automatically across sources.")
            new_vin = st.text_input("VIN (17 characters)", vehicle["vin_raw"] or "", key=f"vin_{vid}")
            if st.button("Save VIN", key=f"save_vin_{vid}"):
                try:
                    keep, msg = dedup.set_vin(c, vid, new_vin)
                    st.success(msg)
                    st.session_state["selected_vehicle"] = keep
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        cands = c.execute(
            "SELECT * FROM match_candidates WHERE status='pending' AND (vehicle_id=? OR candidate_vehicle_id=?)",
            (vid, vid)).fetchall()
        if cands:
            st.subheader("Possible duplicates (needs your review)")
            for cand in cands:
                other = cand["candidate_vehicle_id"] if cand["vehicle_id"] == vid else cand["vehicle_id"]
                orow = inv[inv["vehicle_id"] == other]
                label = common.vehicle_label(orow.iloc[0]) if not orow.empty else f"vehicle #{other}"
                st.markdown(common.md(f"- **{label}** — score {cand['score']:.1f}: {cand['reasons']}"))
                b1, b2 = st.columns(2)
                if b1.button("Same truck — merge", key=f"merge_{cand['id']}"):
                    keep = dedup.merge_vehicles(c, vid, other)
                    st.session_state["selected_vehicle"] = keep
                    st.rerun()
                if b2.button("Different trucks", key=f"reject_{cand['id']}"):
                    dedup.reject_candidate(c, cand["id"])
                    st.rerun()

    # ---------------------------------------------------------- change log
    with t_log:
        ev = pd.read_sql_query(
            "SELECT created_at, event_type, old_value, new_value, listing_id FROM change_events WHERE vehicle_id=?"
            " ORDER BY id DESC", c, params=[vid])
        if ev.empty:
            st.write("No changes recorded.")
        else:
            ev["event"] = ev["event_type"].map(pipeline.EVENT_LABELS).fillna(ev["event_type"])
            ev["created_at"] = ev["created_at"].map(common.local_time)
            st.dataframe(ev[["created_at", "event", "old_value", "new_value", "listing_id"]], hide_index=True,
                         column_config={"created_at": "When", "event": "Change", "old_value": "Old", "new_value": "New",
                                        "listing_id": "Listing #"})


def link_check_line(where, row) -> None:
    """Result of the last 'Check listing links' run for this truck's link."""
    from .. import linkcheck
    res = row.get("link_result")
    if not res:
        return
    text = (f"Link check {common.local_time(row['link_checked_at'])}: **{linkcheck.label(res)}** — "
            f"{linkcheck.explain(res)}" + (f" ({row['link_note']})" if row.get("link_note") else ""))
    (where.warning if res in linkcheck.PROBLEMS else where.caption)(text)


def where_sold(c, row, vid: int) -> None:
    """Prominent answer to 'where is this truck actually for sale?'."""
    with st.container(border=True):
        if row["seller_url"]:
            a, b = st.columns([4, 1.4])
            status = "" if row["link_status"] == "seller" else " — that listing is no longer active"
            host = links.host_of(row["seller_url"])
            a.markdown(f"**Where it's sold:** {row['sold_by'] or 'seller unknown'} · {row['location'] or 'location unknown'}"
                       f"{status}  \n<small>{host}</small>", unsafe_allow_html=True)
            if row["found_on"]:
                a.caption(f"Also seen on: {row['found_on']}")
            link_check_line(a, row)
            b1, b2 = b.columns([3, 1], gap="small")
            b1.link_button("Open seller's listing ↗", row["seller_url"], type="primary", width="stretch")
            with b2.popover("", icon=":material/edit:", type="tertiary", help="Wrong link? Fix or remove it",
                            key=f"edit_link_{vid}"):
                edit_seller_link(c, vid, row)
            from .. import linkcheck
            if row.get("link_result") in linkcheck.PROBLEMS:
                if row["find_seller_url"]:
                    b.link_button("Find seller (web search) ↗", row["find_seller_url"], width="stretch")
                a.caption("Found it at a new address? Paste it here — the truck keeps its history.")
                _link_form(a, c, vid, row)
            return
        a, b = st.columns([4, 1.4])
        if row["found_on"]:
            a.markdown(f"**Where it's sold:** not linked yet — only found on **{row['found_on']}** "
                       f"(seller: {row['seller'] or 'unknown'}, {row['location'] or 'location unknown'}).")
            a.caption("Aggregators re-list dealer inventory. Search for the VIN or dealer to find the seller's own page, "
                      "then paste it below. Once linked, price checks and questions go straight to the seller.")
            b.link_button(f"Open on {row['found_on'].split(',')[0]} ↗", row["found_on_url"], width="stretch")
        else:
            a.markdown("**Where it's sold:** no link recorded for this truck.")
        if row["find_seller_url"]:
            b.link_button("Find seller (web search) ↗", row["find_seller_url"], width="stretch")
        if row["dealer_website"]:
            b.link_button("Dealer website ↗", row["dealer_website"], width="stretch")
        _link_form(a, c, vid, row)


def edit_seller_link(c, vid: int, row) -> None:
    """Fix or remove the seller link (kept through every search)."""
    st.caption("Paste the right link for this truck's listing, or remove the wrong one.")
    new = st.text_input("Seller's listing link", row["seller_url"], key=f"fix_link_{vid}")
    s1, s2 = st.columns(2)
    action = None
    if s1.button("Save link", type="primary", key=f"fix_link_save_{vid}", disabled=new.strip() == row["seller_url"]):
        action = new
    if s2.button("Remove link", key=f"fix_link_remove_{vid}"):
        action = ""
    if action is not None:
        try:
            result = services.set_seller_link(c, vid, row.get("seller_listing_id"), action)
            common.flash({"fixed": "Seller link fixed.", "overridden": "Seller link corrected — searches won't change it back.",
                          "removed": "Wrong link removed.", "hidden": "Seller link removed — use Find seller to look it up."}[result])
            st.rerun()
        except ValueError as e:
            st.error(str(e))


def _link_form(where, c, vid: int, row) -> None:
    """Paste the seller's own listing URL (new truck page, or a listing that moved)."""
    with where.form(f"seller_link_{vid}", clear_on_submit=True, border=False):
        x1, x2, x3 = st.columns([4, 1.3, 1])
        url = x1.text_input("Seller's listing URL", placeholder="https://dealer-site.example/used/2024-rivian-r1t-…",
                            label_visibility="collapsed")
        price = x2.number_input("Price there ($, optional)", 0, 300000, 0, 100, label_visibility="collapsed",
                                help="Price shown on the seller's page, if different")
        if x3.form_submit_button("Link it"):
            try:
                services.add_listing_link(c, vid, url, price=int(price) or None, seller_name=row["seller"] or None)
                common.flash("Seller's listing linked.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def history_tab(c, row, vid: int) -> None:
    st.subheader("Vehicle history report")
    reports = [l for l in c.execute("SELECT source_key, seller_name, history_report_url FROM listings WHERE vehicle_id=?"
                                    " AND history_report_url IS NOT NULL", (vid,)).fetchall()]
    if reports:
        for r in reports:
            st.link_button(f"Carfax report (provided by {r['seller_name'] or queries.source_label(r['source_key'])}) ↗",
                           r["history_report_url"])
        st.caption("Dealer-supplied links usually open the full report free. Check title brands, accidents, owner count, "
                   "and the first-sold date (that's the warranty in-service date — enter it under Verify equipment).")
        with st.expander("CARFAX access help"):
            st.write("If CARFAX restricts access, copy the report link into your usual browser with JavaScript and "
                     "cookies enabled. If you opened it in an automated browser, try your regular browser without "
                     "developer tools attached. Avoid repeated retries; CARFAX controls access.")
            st.link_button("Contact CARFAX support ↗", "https://support.carfax.com/contact-us/general/")
            st.caption("Include the restriction ID shown on their page when requesting help.")
    else:
        st.write("No dealer-provided history report link for this truck. Ask the seller for a Carfax/AutoCheck, or buy one "
                 "with the VIN" + (f" **{row['vin']}**." if row["vin"] else "."))
    if row["owners"] or row["title_status"] != "unknown":
        st.caption(f"From listing data: title {queries.label_title(row['title_status'])}"
                   + (f" · {row['owners']}" if row["owners"] else ""))

    st.subheader("Safety recalls")
    if row.get("make") != "Rivian":
        st.caption("Automatic model-year recall caching currently covers Rivian R1T only. Check this truck's VIN with NHTSA or its manufacturer.")
        st.link_button("Open NHTSA VIN recall lookup ↗", row["recall_lookup_url"])
        return
    year = int(row["year"]) if pd.notna(row["year"]) else None
    items = recalls.for_year(c, year)
    a, b = st.columns([3, 1])
    if b.button("Refresh recalls", key=f"rc_{vid}", help="Ask NHTSA for the latest recalls for this model year"):
        res = recalls.refresh(c, [year], force=True) if year else {"errors": ["unknown model year"]}
        if res.get("errors"):
            st.error(f"Could not reach NHTSA: {', '.join(res['errors'])}")
        st.rerun()
    if not year:
        a.write("Model year unknown, so recalls can't be looked up.")
        return
    if not items:
        a.write(f"No recalls cached for {year} R1T yet. They load during the next Run Search, or click Refresh.")
    else:
        ota = sum(1 for r in items if r["ota"])
        a.markdown(f"**{len(items)} recall(s)** issued for the {year} R1T ({ota} fixed over the air). Not every truck of "
                   "a model year is affected, and completed repairs don't show here.")
        st.dataframe(pd.DataFrame([{"Date": r["report_date"], "Campaign": r["campaign"], "Component": r["component"],
                                    "Over the air": bool(r["ota"]), "Summary": r["summary"], "Remedy": r["remedy"]}
                                   for r in items]), hide_index=True,
                     column_config={"Summary": st.column_config.TextColumn(width="large"),
                                    "Remedy": st.column_config.TextColumn(width="large")})
    st.markdown(f"**Is anything still open on this exact truck?** Paste the VIN"
                + (f" `{row['vin']}`" if row["vin"] else "") + " into NHTSA's lookup (it shows unrepaired recalls only), "
                "or ask Rivian service.")
    st.link_button("Open NHTSA VIN recall lookup ↗", row["recall_lookup_url"])


def negotiation_strip(row) -> None:
    with st.container(border=True):
        n = st.columns([1, 1, 1, 2.2])
        dl = row["days_listed"]
        n[0].metric("Days listed", f"{int(dl)}" if pd.notna(dl) else "—",
                    help=f"Source: {row['listed_source'] or 'none'}"
                         + (f" · listed since {row['listed_since']}" if row["listed_since"] else ""))
        drops = int(row["price_drops"])
        n[1].metric("Price drops", drops, delta=f"-${int(row['dropped_total']):,}" if drops else None,
                    delta_color="inverse", help="Price cuts Truck Finder has observed on this listing")
        n[2].metric("Leverage", row["leverage"],
                    help="Heuristic: High = listed 60+ days or 2+ price cuts; Medium = 30+ days or 1 cut")
        lines = [f"**Negotiation:** {common.md(row['leverage_text'])}."]
        if row["flip_text"]:
            lines.append(f"🔁 **{row['flags']}:** {row['flip_text']} Ask why, and check Carfax for auction/ownership history.")
        if row["last_drop_at"]:
            lines.append(f"Last cut {common.local_time(row['last_drop_at'])}.")
        if row["seller_phone"]:
            lines.append(f"Seller phone: **{row['seller_phone']}**")
        n[3].markdown("  \n".join(lines))


def deal_strip(row) -> None:
    with st.container(border=True):
        d = st.columns([1, 1, 1, 2.2])
        mp = row["market_price"]
        d[0].metric("Market estimate", common.money(mp) if pd.notna(mp) else "—",
                    help="Expected price for this year/miles/battery/motor/tonneau, from your collected listings")
        dd = row["deal_delta"]
        d[1].metric("vs. market", (f"-${abs(dd):,.0f}" if dd < 0 else f"+${dd:,.0f}") if pd.notna(dd) else "—",
                    delta=f"{row['deal_pct']:+.1%}" if pd.notna(row["deal_pct"]) else None, delta_color="inverse")
        d[2].metric("Deal rating", row["deal_label"])
        lines = [row["deal_note"]] if row["deal_note"] else []
        if row["comps_text"]:
            lines.append(row["comps_text"])
        d[3].markdown(common.md("  \n".join(lines)) or "—")


def photo_manager(c, vid: int, row) -> None:
    with st.expander("Photo", expanded=not row["photo_url"]):
        photo_form(c, vid, row, key="tab")


def photo_form(c, vid: int, row, key: str = "top") -> None:
    """Pick a different photo: an image URL or an uploaded file. Your choice is kept through every search."""
    st.caption("Wrong or missing photo? On the listing, right-click the truck's photo → **Copy image address** and "
               "paste it here, or save the picture and upload it. Your choice is kept through every search.")
    with st.form(f"photo_{key}_{vid}", clear_on_submit=True, border=False):
        url = st.text_input("Image URL", placeholder="https://…/photo.jpg")
        up = st.file_uploader("…or upload a picture", type=["jpg", "jpeg", "png", "webp"])
        if st.form_submit_button("Use this photo", type="primary"):
            try:
                if up is not None:
                    photos.set_user_photo(c, vid, data=up.getvalue())
                elif url.strip():
                    photos.set_user_photo(c, vid, url=url.strip())
                else:
                    raise ValueError("Paste an image URL or choose a file.")
                common.flash("Photo updated.")
                st.rerun()
            except Exception as e:  # network or image errors
                st.error(f"Couldn't use that photo: {e}")
        if st.form_submit_button("Go back to the listing's photo"):
            photos.set_user_photo(c, vid)
            photos.path_for(vid, "t").unlink(missing_ok=True)
            photos.path_for(vid, "m").unlink(missing_ok=True)
            photos.cache_missing(c, limit=5)
            st.rerun()


def checklist_tab(c, vid: int, row) -> None:
    st.subheader("Pre-purchase checklist")
    st.caption("Work through these before you buy. OK on tonneau/title/accidents/config records verified values; "
               "Problem on title or accidents records a branded title / reported accident. Mark N/A for equipment or checks that do not apply.")
    state = checklist.get(c, vid)
    keys = list(checklist.STATUSES)
    with st.form(f"chk_{vid}"):
        answers = {}
        for key, label, hint in checklist.items_for(row):
            a, b, n = st.columns([3.2, 1.2, 3])
            a.markdown(f"**{label}**" + (f"  \n<small>{hint}</small>" if hint else ""), unsafe_allow_html=True)
            cur = state[key]
            status = b.selectbox("Status", keys, index=keys.index(cur["status"]), format_func=checklist.STATUSES.get,
                                 key=f"chk_{vid}_{key}", label_visibility="collapsed")
            note = n.text_input("Note", cur["note"], key=f"chkn_{vid}_{key}", label_visibility="collapsed",
                                placeholder="note")
            answers[key] = (status, note.strip())
        if st.form_submit_button("Save checklist", type="primary"):
            fed = checklist.save(c, vid, answers)
            msg = "Checklist saved." + (f" Verified: {', '.join(fed)}." if fed else "")
            common.flash(msg)
            if answers["title"][0] == "problem" and not row["hidden"]:
                common.flash("Title problem recorded. To drop this truck: 🚫 Not interested → Branded title.", "info")
            st.rerun()

    st.subheader("Calls & messages")
    with st.form(f"contact_{vid}", clear_on_submit=True):
        a, b, d = st.columns([1, 2, 1.4])
        channel = a.selectbox("How", checklist.CHANNELS)
        person = b.text_input("With", placeholder=f"e.g. sales at {row['seller'] or 'the dealer'}")
        follow = d.date_input("Follow up on", value=None, format="MM/DD/YYYY")
        summary = st.text_area("What was said", height=90,
                               placeholder="Price flexibility, tonneau works?, in-service date, title, fees, delivery…")
        if st.form_submit_button("Add to log"):
            if summary.strip() or person.strip():
                checklist.add_contact(c, vid, channel, person, summary, follow)
                st.rerun()
    if row["seller_phone"]:
        st.caption(f"Seller phone: **{row['seller_phone']}**")
    for ct in checklist.contacts(c, vid):
        with st.container(border=True):
            x, y = st.columns([6, 1])
            x.markdown(f"**{ct['channel'].title()}** {('with ' + ct['person']) if ct['person'] else ''} · "
                       f"{common.local_time(ct['at'])}"
                       + (f" · follow up **{ct['follow_up']}**" if ct["follow_up"] else "")
                       + (f"  \n{ct['summary']}" if ct["summary"] else ""))
            if y.button("Delete", key=f"ctdel_{ct['id']}"):
                checklist.delete_contact(c, ct["id"])
                st.rerun()


SOURCES = "As listed"


def quick_verify(c, vid: int, row) -> None:
    """The facts you look up yourself — saved as verified values that no search ever overwrites."""
    from datetime import date as _date
    from ..extract import parse_warranty
    overrides = {r["field"]: r["value"] for r in c.execute("SELECT field, value FROM user_overrides WHERE vehicle_id=?",
                                                           (vid,))}
    need = not overrides.get("in_service_date") and not overrides.get("warranty_expiration")
    is_rivian = row.get("make") == "Rivian"
    with st.expander("✏️ Quick verify — in-service date, battery, motor, tonneau, warranty (stays through every "
                     "refresh)", expanded=need):
        with st.form(f"qv_{vid}", border=False):
            a, b, m, t = st.columns(4)
            cur = overrides.get("in_service_date")
            isd = a.date_input("In-service date (Carfax 'first sold' or manufacturer)",
                               _date.fromisoformat(cur) if cur else None, min_value=_date(2021, 1, 1),
                               max_value=_date.today(), key=f"qv_isd_{vid}", format="MM/DD/YYYY")
            sources_say = {"battery": "Uncertain" if row["battery_uncertain"] else row["battery"],
                           "motor": "Uncertain" if row["motor_uncertain"] else row["motor"]}
            picked = {}
            for col, field, choices in ((b, "battery", BATTERIES), (m, "motor", MOTORS)):
                if not is_rivian:
                    picked[field] = col.text_input(f"{field.title()} (sources: {sources_say[field]}) — blank = as listed",
                                                   overrides.get(field) or "", key=f"qv_{field}_{vid}") or SOURCES
                    continue
                opts = [SOURCES] + [x for x in choices if x != "Unknown"]
                now = overrides.get(field)
                picked[field] = col.selectbox(f"{field.title()} (sources: {sources_say[field]})", opts,
                                              index=opts.index(now) if now in opts else 0, key=f"qv_{field}_{vid}",
                                              help="Pick what the window sticker / Rivian / seller's Vehicle screen "
                                                   "confirms. 'As listed' goes back to what the sources say.")
            wheel_opts = [SOURCES, '20" Road wheels', '20" All-Terrain wheels', '21" Road wheels', '22" Sport wheels']
            cur_w = overrides.get("wheels")
            if is_rivian:
                wheel = st.selectbox(f"Wheels (sources: {row['wheels'] or 'unknown'}) — sets the EPA range", wheel_opts,
                                     index=wheel_opts.index(cur_w) if cur_w in wheel_opts else 0,
                                     format_func=lambda o: "As listed" if o == SOURCES else o, key=f"qv_wheels_{vid}")
                sub_opts = [SOURCES, "cast", "welded"]
                sub = st.selectbox(f"Front subframe (estimate: {row['subframe']} — {row['subframe_note']})", sub_opts,
                               index=sub_opts.index(overrides["front_subframe"])
                               if overrides.get("front_subframe") in sub_opts else 0,
                               format_func=lambda o: "As estimated from the VIN" if o == SOURCES else o.title(),
                               key=f"qv_subframe_{vid}",
                               help="If the seller or service records confirm it (e.g. replaced with the cast "
                                    "subframe under warranty), record it here.")
                picked["front_subframe"] = sub
            else:
                wheel = st.text_input(f"Wheels (sources: {row['wheels'] or 'unknown'}) — blank = as listed",
                                      cur_w or "", key=f"qv_wheels_{vid}") or SOURCES
            opts = list(TONNEAU_STATUSES)
            cur_t = overrides.get("tonneau") or row["tonneau"]
            ton = t.selectbox("Powered tonneau", opts, index=opts.index(cur_t) if cur_t in opts else opts.index("unknown"),
                              format_func=TONNEAU_STATUSES.get, key=f"qv_ton_{vid}")
            wtxt = st.text_area("Paste warranty info (optional)", key=f"qv_w_{vid}", height=90,
                                placeholder="Comprehensive\nApr 2028 or 60k mi\nBattery pack & drivetrain\nApr 2031 or 175k mi")
            if st.form_submit_button("Save", type="primary"):
                note = "Quick verify"
                if (isd.isoformat() if isd else None) != cur:
                    attributes.set_override(c, vid, "in_service_date", isd.isoformat() if isd else None, note)
                if ton != (overrides.get("tonneau") or row["tonneau"]) or (ton != "unknown" and "tonneau" not in overrides):
                    attributes.set_override(c, vid, "tonneau", None if ton == "unknown" else ton, note)
                for field, value in {**picked, "wheels": wheel}.items():
                    if (None if value == SOURCES else value) != overrides.get(field):
                        attributes.set_override(c, vid, field, None if value == SOURCES else value, note)
                parsed = parse_warranty(wtxt)
                for field, value in parsed.items():
                    attributes.set_override(c, vid, field, str(value), "Pasted warranty info")
                if wtxt.strip() and not parsed:
                    st.error("Couldn't read dates from that warranty text — enter the warranty expiration under Verify equipment.")
                else:
                    common.flash("Saved. Warranty and tonneau now use your values." if (isd or parsed or ton != "unknown")
                                 else "Saved.")
                    st.rerun()
