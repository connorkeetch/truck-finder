"""Persistent listing updates from the latest search and activity recorded afterward."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import compare, queries
from . import common


def _signed_money(value) -> str:
    return "—" if pd.isna(value) else f"{'+' if value >= 0 else '-'}${abs(value):,.0f}"


def render(c=None, s: dict | None = None) -> None:
    c = c if c is not None else common.conn()
    s = s if s is not None else common.settings()
    result = queries.refresh_changes(c)
    run, events = result["run"], result["events"]
    with st.container(border=True):
        st.subheader("Updated since last refresh")
        if run is None:
            st.info("No refresh yet. Use Run Search to start tracking changes.")
            return
        st.caption("Changes found in the latest Run Search and updates recorded afterward. Browser reloads do not clear this section.")
        st.caption(f"Latest Run Search: {common.local_time(run.get('started_at'))} · {run.get('status', 'unknown')}")
        st.caption("Inventory filters do not hide these updates. Rows describe a source listing; another listing for the same truck may still be active.")
        if run.get("first_refresh") and run.get("status") != "failed":
            st.info("This first refresh establishes a baseline. New means first seen in this app, including new source listings for known trucks.")
        sources = run.get("summary", {}).get("sources", [])
        if sources:
            st.caption("Source coverage: " + " · ".join(f"{source.get('name') or source.get('source', 'Source')}: {source.get('status', 'unknown')}"
                                                       for source in sources))
        for source in sources:
            name, status = source.get("name") or source.get("source", "Source"), source.get("status", "unknown")
            if status in ("partial", "failed", "skipped"):
                st.warning(f"{name}: {status}. Listings not seen in an incomplete or failed search are left unchanged."
                           + (f" {source['error']}" if source.get("error") else ""))
            for note in source.get("notes", []):
                if "scope changed" in note.lower() or ("disappearance" in note.lower() and "skip" in note.lower()):
                    st.caption(note)
        if not s.get("filters", {}).get("show_demo", True) and not events.empty:
            events = events[~events["is_demo"].fillna(False).astype(bool)]
        if events.empty:
            if run.get("status") == "failed":
                st.warning("No changes were recorded; this is not confirmation that listings are unchanged.")
            else:
                st.info("No recorded changes in this refresh window.")
            return
        groups = [("New listings", "new"), ("Price changes", "price"), ("Sold or removed", "removed"), ("Not seen", "missing")]
        tabs = st.tabs([f"{label} ({int(events['category'].eq(category).sum())})" for label, category in groups])
        for tab, (_, category) in zip(tabs, groups):
            with tab:
                if category == "missing":
                    st.caption("Not seen in a complete search; a sale is unconfirmed. Failed, incomplete and unsearched scopes do not establish disappearance.")
                if category == "removed":
                    st.caption("A provider or user reported this listing sold or removed. This does not establish that every listing for the truck is gone.")
                rows = events[events["category"].eq(category)]
                if rows.empty:
                    st.write("No updates in this category.")
                    continue
                view = pd.DataFrame(index=rows.index)
                view["Vehicle"] = [("[DEMO] " if row.get("is_demo") else "") + compare.vehicle_name(row)
                                   for _, row in rows.iterrows()]
                view["Update"] = rows["event_type"].map(queries.EVENT_LABELS).fillna(rows["event_type"])
                view["Source"], view["Seller"] = rows["source"], rows["seller_name"]
                if category == "price":
                    view["Before"], view["After"] = rows["old_price"], rows["new_price"]
                    view["Change ($)"] = rows["price_delta"].map(_signed_money)
                elif category == "new":
                    view["Listed price"] = rows["new_price"]
                elif category == "removed":
                    view["Details"] = rows["new_value"]
                view["Listing status"] = rows["listing_status"]
                view["Recorded"] = rows["update_origin"]
                view["When"] = rows["created_at"].map(common.local_time)
                view["Listing"] = rows["url"]
                st.dataframe(view, hide_index=True, width="stretch", key=f"refresh_changes_{category}", column_config={
                    "Before": st.column_config.NumberColumn(format="dollar", step=1),
                    "After": st.column_config.NumberColumn(format="dollar", step=1),
                    "Listed price": st.column_config.NumberColumn(format="dollar", step=1),
                    "Listing": st.column_config.LinkColumn(display_text="Open listing ↗"),
                })
