"""Dashboard: totals, latest run summary, recent changes, inventory mix, source health."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

from .. import compare, queries
from . import common


def render() -> None:
    c = common.conn()
    s = common.settings()
    st.title("Dashboard")

    inv = common.inventory(s)
    if inv.empty:
        st.info("No vehicles yet. Add an Auto.dev API key in **Settings → API credentials** and press **Run Search**, "
                "or press Run Search now to load clearly-labeled **synthetic demo data** and explore the app.")
        return
    matching = queries.apply_filters(inv, s["filters"])

    summary = st.session_state.get("last_summary")
    last = queries.last_search_run(c)
    if summary and summary.get("text"):
        st.success(f"**Latest run:** {summary['text']}")
    elif last:
        st.info(f"**Last run ({common.local_time(last['started_at'])}):** "
                f"{queries.summary_text(last['summary'], len(matching))}")

    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev7 = queries.events_frame(c, since=week_ago)
    matching_ids = set(matching["vehicle_id"])
    ev7m = ev7[ev7["vehicle_id"].isin(matching_ids)] if not ev7.empty else ev7
    n_new = int((ev7m["event_type"] == "new_listing").sum()) if not ev7m.empty else 0
    n_drop = int((ev7m["event_type"] == "price_drop").sum()) if not ev7m.empty else 0
    in_view = queries.apply_filters(inv, dict(s["filters"], include_missing=True))
    missing = int(((in_view["status"] == "missing") & ~in_view["status_reason"].str.startswith("Not re-checked")).sum())

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Matching vehicles", len(matching), help="Active vehicles passing your current filters")
    k2.metric("New (7 days)", n_new)
    k3.metric("Price drops (7 days)", n_drop)
    k4.metric("Missing from last scan", missing, help="Matching trucks not seen in the latest complete scan (not confirmed "
                                                       "sold). Trucks outside the collection scope aren't counted.")
    k5.metric("Tonneau listed/confirmed",
              int(matching["tonneau"].eq("yes").sum()))
    if inv["is_demo"].any():
        st.caption("⚠️ Includes synthetic demo data (marked DEMO). Purge it in Settings → Backup & data.")

    left, right = st.columns([3, 2])
    with left:
        h1, h2 = st.columns([2, 1.2])
        h1.subheader("Top matches")
        with h2:
            size = common.photo_size_control("dash_photo_size")
        row_h = common.PHOTO_SIZES[size]
        top = matching.head(10)
        if top.empty:
            st.write("Nothing matches your filters. Loosen them on the Inventory page.")
        else:
            show = common.add_photo_column(top)[["photo", "sold_by", "location", "fit_score", "year", "make", "model", "trim", "price",
                                                 "deal_label", "miles", "battery", "motor", "tonneau", "warranty",
                                                 "distance_mi", "est_monthly", "seller_url", "found_on", "favorite",
                                                 "hidden", "vehicle_id"]].copy()
            show["tonneau"] = show["tonneau"].map(lambda t: f"{common.TONNEAU_ICON.get(t, '')} {t.replace('_', ' ')}")
            ev = st.dataframe(
                show, hide_index=True, on_select="rerun", selection_mode="multi-row", key=common.table_key("dash_top"),
                row_height=row_h, height=common.table_height(len(show), row_h),
                column_config={
                    "photo": st.column_config.ImageColumn("Photo", width=int(row_h * 4 / 3)),
                    "sold_by": st.column_config.TextColumn("Sold by", width="medium"),
                    "favorite": None, "hidden": None,
                    "fit_score": st.column_config.ProgressColumn("Fit", min_value=0, max_value=100, format="%d"),
                    "year": st.column_config.NumberColumn("Year", format="%d"),
                    "price": st.column_config.NumberColumn("Price", format="dollar", step=1),
                    "miles": st.column_config.NumberColumn("Miles", format="%,d"),
                    "distance_mi": st.column_config.NumberColumn("Dist (mi)", format="%,d"),
                    "est_monthly": st.column_config.NumberColumn("Est. /mo", format="dollar", step=1),
                    "tonneau": "Powered tonneau", "vehicle_id": None, "trim": "Trim", "battery": "Battery",
                    "motor": "Motor", "make": "Brand", "model": "Model", "warranty": "Warranty left", "location": "Location",
                    "seller_url": st.column_config.LinkColumn("Seller listing", display_text="seller ↗"),
                    "deal_label": "Deal",
                    "found_on": "Found on",
                })
            selected = show.iloc[ev.selection.rows] if ev.selection.rows else show.iloc[0:0]
            common.selection_actions(c, selected, "dash_top")
            st.caption("Tick a row's checkbox → open, compare, favorite or hide it from the top of the left sidebar. "
                       "Fit score weights tonneau, battery, warranty, price, miles, location and history.")
        st.subheader("Recent changes")
        if ev7.empty:
            st.write("No changes in the last 7 days.")
        else:
            recent = ev7.head(25)[["created_at", "event", "year", "old_value", "new_value", "seller_name", "state",
                                   "source", "url"]].copy()
            recent["created_at"] = recent["created_at"].map(common.local_time)
            st.dataframe(recent, hide_index=True, column_config={
                "created_at": "When", "event": "Change", "year": st.column_config.NumberColumn("Year", format="%d"),
                "old_value": "Old", "new_value": "New", "seller_name": "Seller", "state": "State",
                "source": "Source", "url": st.column_config.LinkColumn("Listing", display_text="open")})
    with right:
        st.subheader("Inventory mix (matching)")
        if not matching.empty:
            tab1, tab2, tab3, tab4 = st.tabs(["Price", "Year", "Generation", "Battery"])
            with tab1:
                st.altair_chart(alt.Chart(matching.dropna(subset=["price"])).mark_bar().encode(
                    x=alt.X("price:Q", bin=alt.Bin(step=2500), title="Price ($)"),
                    y=alt.Y("count():Q", title="Vehicles"), color=alt.Color("generation:N", title="Gen")),
                    width="stretch")
            for tab, col in ((tab2, "year"), (tab3, "generation"), (tab4, "battery")):
                with tab:
                    data = matching[col].astype(str).value_counts().rename_axis(col).reset_index(name="count")
                    st.altair_chart(alt.Chart(data).mark_bar().encode(
                        x=alt.X(f"{col}:N", sort="-y", title=col.title()), y=alt.Y("count:Q", title="Vehicles")),
                        width="stretch")
        today = datetime.now().date().isoformat()
        due = inv[(inv["follow_up"] != "") & (inv["follow_up"] <= today) & ~inv["hidden"]]
        if not due.empty:
            st.subheader("Follow-ups due")
            for r in due.sort_values("follow_up").itertuples():
                if st.button(f"{r.follow_up} · {compare.vehicle_name(r._asdict())} · {r.seller}",
                             key=f"fu_{r.vehicle_id}", width="stretch"):
                    common.open_vehicle(int(r.vehicle_id))
        flagged = matching[matching["flip"]]
        if not flagged.empty:
            st.caption(f"🔁 {len(flagged)} matching truck(s) changed dealers or were relisted — see the History flags "
                       "column in Inventory.")
        st.subheader("Source status")
        ss = queries.source_status(c)
        ss = ss[(ss["last_attempt_at"].notna()) | (ss["active_listings"] > 0) | (ss["kind"] == "api")]
        icon = {"success": "🟢", "partial": "🟡", "failed": "🔴", "skipped": "⚪"}
        for r in ss.itertuples():
            last_status = r.last_status if isinstance(r.last_status, str) else None
            status = f"{icon.get(last_status, '⚪')} {last_status or 'never run'}"
            st.markdown(f"**{r.name}** — {status} · {r.active_listings} active"
                        + (f" · {r.missing_listings} missing" if r.missing_listings else "")
                        + (f"  \n<small>Last success: {common.local_time(r.last_success_at)}</small>"
                           if isinstance(r.last_success_at, str) else ""), unsafe_allow_html=True)
            if isinstance(r.last_error, str) and r.last_error:
                st.caption(f"⚠️ {r.last_error}")
