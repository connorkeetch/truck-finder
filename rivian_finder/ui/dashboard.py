"""Dashboard: totals, latest run summary, recent changes, inventory mix, source health."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

from .. import compare, queries
from . import common, refresh_changes


def render() -> None:
    c = common.conn()
    s = common.settings()
    st.title("Dashboard")
    st.caption("Overview of your saved default filters. Save defaults from Inventory or edit Settings → Vehicle filters "
               "to change what is counted here.")
    refresh = queries.refresh_changes(c)
    refresh_changes.render(c, s, refresh)

    inv = queries.attach_refresh_badges(common.inventory(s), refresh)
    if inv.empty:
        st.info("Start in **Inventory**: add a listing manually, or use **Sources** to set up a provider and refresh. "
                "To explore without an API key, choose **Try demo** on the empty Inventory page.")
        refresh_changes.render_retired(c, s, inv, refresh, key="dash_retired")
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
    k1.metric("Matching vehicles", len(matching), help="Vehicles passing your saved default filters")
    k2.metric("New listings (7 days)", n_new)
    k3.metric("Price drops (7 days)", n_drop)
    k4.metric("Missing from last scan", missing, help="Matching vehicles not seen in the latest complete scan (not confirmed "
                                                       "sold). Vehicles outside the collection scope aren't counted.")
    k5.metric("Favorites", int(matching["favorite"].sum()), help="Favorites within your saved default filters")
    if inv["is_demo"].any():
        st.caption("⚠️ Includes synthetic demo data (marked DEMO). Purge it in Settings → Backup & data.")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Top matches")
        row_h = 64
        top = queries.sort_inventory(matching, "Personal match").head(10)
        if top.empty:
            st.write("Nothing matches your saved default filters. Adjust filters in Inventory and choose Save as my default filters to update this overview.")
        else:
            show = top[["price", "miles", "match_status", "deal_label", "sold_by", "location", "favorite",
                        "hidden", "vehicle_id"]].copy()
            show.insert(0, "name", [compare.vehicle_name(row) for _, row in top.iterrows()])
            show["updates"] = [" · ".join(b["text"] for b in badges) for badges in top["refresh_badges"]]
            actions = st.container()
            ev = st.dataframe(
                show, hide_index=True, on_select="rerun", selection_mode="multi-row", key=common.table_key("dash_top"),
                row_height=row_h, height=min(480, common.table_height(len(show), row_h)),
                column_config={
                    "name": st.column_config.TextColumn("Vehicle", width="medium"),
                    "sold_by": st.column_config.TextColumn("Sold by", width="medium"),
                    "updates": st.column_config.TextColumn("Updates", width="medium"),
                    "favorite": None, "hidden": None,
                    "match_status": st.column_config.TextColumn("My requirements", width="medium"),
                    "price": st.column_config.NumberColumn("Price", format="dollar", step=1),
                    "miles": st.column_config.NumberColumn("Miles", format="%,d"),
                    "vehicle_id": None, "location": "Location",
                    "deal_label": "Deal",
                })
            selected = show.iloc[ev.selection.rows] if ev.selection.rows else show.iloc[0:0]
            with actions:
                common.selection_actions(c, selected, "dash_top")
            st.caption("Tick a row's checkbox → open, compare, favorite or hide it using the actions above this table. "
                       "Top matches put requirements first, then your saved preferences and room under your budget, mileage and distance limits.")
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
            tab1, tab2, tab3, tab4 = st.tabs(["Price", "Year", "Brand", "Model"])
            with tab1:
                st.altair_chart(alt.Chart(matching.dropna(subset=["price"])).mark_bar().encode(
                    x=alt.X("price:Q", bin=alt.Bin(step=2500), title="Price ($)"),
                    y=alt.Y("count():Q", title="Vehicles"), color=alt.Color("make:N", title="Brand")),
                    width="stretch")
            for tab, col in ((tab2, "year"), (tab3, "make"), (tab4, "model")):
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
            st.caption(f"🔁 {len(flagged)} matching vehicle(s) changed dealers or were relisted — see the History flags "
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
    refresh_changes.render_retired(c, s, inv, refresh, key="dash_retired")
