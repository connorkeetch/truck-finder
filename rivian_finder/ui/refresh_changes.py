"""Compact refresh context and persistent, source-specific retirement history."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import compare, queries
from . import common


def render(c=None, s: dict | None = None, result=None) -> None:
    if result is None:
        result = queries.refresh_changes(c if c is not None else common.conn())
    run = result["run"]
    if run is None:
        st.caption("No refresh yet. Use Run Search to start tracking changes.")
        return
    st.caption(f"Latest Run Search: {common.local_time(run.get('started_at'))} · {run.get('status', 'unknown')}")
    if run.get("first_refresh") and run.get("status") != "failed":
        st.info("This first refresh establishes a baseline. New means first seen in this app, including new source listings for known trucks.")
    if run.get("status") == "failed":
        st.warning("This refresh failed; it is not confirmation that listings are unchanged.")
    sources = run.get("summary", {}).get("sources", [])
    if sources:
        st.caption("Source coverage: " + " · ".join(f"{source.get('name') or source.get('source', 'Source')}: {source.get('status', 'unknown')}"
                                                   for source in sources))
    for source in sources:
        name, status = source.get("name") or source.get("source", "Source"), source.get("status", "unknown")
        if status in ("partial", "failed", "skipped"):
            st.warning(f"{name}: {status}. Missing listings cannot be inferred from this incomplete search."
                       + (f" {source['error']}" if source.get("error") else ""))
        for note in source.get("notes", []):
            if "scope changed" in note.lower() or ("disappearance" in note.lower() and "skip" in note.lower()):
                st.caption(note)


def _visible_demo(rows: pd.DataFrame, s: dict) -> pd.DataFrame:
    if not rows.empty and not s.get("filters", {}).get("show_demo", True):
        return rows[~rows["is_demo"].fillna(False).astype(bool)]
    return rows


def _retired_row(row, *, key: str, known_vehicles: set, archive: bool = False,
                 active_elsewhere: bool = False) -> None:
    status = row.get("status" if archive else "listing_status")
    status = status if isinstance(status, str) and status else "unknown"
    seller = row.get("seller" if archive else "seller_name")
    seller = seller if isinstance(seller, str) and seller else "Seller unknown"
    source = row.get("source")
    source = source if isinstance(source, str) and source else "Source unknown"
    reported_removed = status == "removed" if archive else row.get("category") == "removed"
    with st.container(border=True):
        demo = pd.notna(row.get("is_demo")) and bool(row.get("is_demo"))
        st.markdown(common.md(("[DEMO] " if demo else "") + f"**{compare.vehicle_name(row)}**"))
        st.caption(f"{source} · {seller} · Current listing status: {status}")
        st.write("Active again" if status == "active" else
                 "Sold or removed (reported)" if reported_removed else "Not seen — sale unconfirmed")
        if active_elsewhere and status != "active":
            st.caption("Another source still lists this truck as active.")
        if archive:
            st.caption(f"Last seen: {common.local_time(row.get('last_seen'))}")
            for field in ("status_reason", "notes"):
                note = row.get(field)
                if isinstance(note, str) and note:
                    st.caption(note)
        else:
            st.caption(f"Recorded: {common.local_time(row.get('created_at'))} · {row.get('update_origin', 'Refresh')}")
            if isinstance(row.get("new_value"), str) and row["new_value"]:
                st.caption(row["new_value"])
        details, link = st.columns(2)
        if row["vehicle_id"] in known_vehicles and details.button("Open details", key=f"{key}_open"):
            common.open_vehicle(int(row["vehicle_id"]))
        url = common._web_url(row.get("url"))
        if url:
            link.link_button("Source listing ↗", url, key=f"{key}_link")


def render_retired(c=None, s: dict | None = None, inv=None, result=None, key: str = "retired") -> None:
    s = s if s is not None else common.settings()
    if result is None:
        result = queries.refresh_changes(c if c is not None else common.conn())
    inv = inv if inv is not None else common.inventory(s)
    events = _visible_demo(result["events"], s)
    if not events.empty:
        events = events[events["category"].isin(("removed", "missing"))]
        events = events.sort_values(["created_at", "id"], ascending=False).drop_duplicates("listing_id")
    archive = _visible_demo(inv, s)
    if not archive.empty:
        archive = archive[archive["status"].isin(("removed", "missing")) & archive["active_listings"].eq(0)]
    known_vehicles = set(inv["vehicle_id"]) if not inv.empty else set()
    active_counts = inv.set_index("vehicle_id")["active_listings"].to_dict() if not inv.empty else {}
    trucks = (set(events["vehicle_id"]) if not events.empty else set()) | (
        set(archive["vehicle_id"]) if not archive.empty else set())
    with st.expander(f"Sold, removed & not seen ({len(trucks)})", expanded=False):
        st.caption("Ordinary Inventory filters do not hide this history. Missing does not confirm a sale.")
        if not trucks:
            st.caption("No sold, removed or missing listings recorded.")
        else:
            labels = [f"Recent status changes ({len(events)})", f"All unavailable trucks ({len(archive)})"]
            labels = labels if not events.empty else labels[::-1]
            tabs = dict(zip(labels, st.tabs(labels)))
            with tabs[f"Recent status changes ({len(events)})"]:
                if events.empty:
                    st.caption("No status changes in the latest refresh window.")
                recent_limit_key = f"{key}_recent_limit"
                recent_limit = st.session_state.get(recent_limit_key, 20)
                for _, row in events.head(recent_limit).iterrows():
                    _retired_row(row, key=f"{key}_event_{row['listing_id']}_{row['id']}", known_vehicles=known_vehicles,
                                 active_elsewhere=active_counts.get(row["vehicle_id"], 0) > 0)
                if len(events) > recent_limit and st.button("Show more status changes", key=f"{key}_recent_more"):
                    st.session_state[recent_limit_key] = recent_limit + 20
                    st.rerun()
            with tabs[f"All unavailable trucks ({len(archive)})"]:
                if archive.empty:
                    st.caption("No trucks currently have only sold, removed or missing listings.")
                limit_key = f"{key}_archive_limit"
                limit = st.session_state.get(limit_key, 20)
                for _, row in archive.head(limit).iterrows():
                    _retired_row(row, key=f"{key}_archive_{row['listing_id']}_{row['vehicle_id']}",
                                 known_vehicles=known_vehicles, archive=True)
                if len(archive) > limit and st.button("Show more", key=f"{key}_archive_more"):
                    st.session_state[limit_key] = limit + 20
                    st.rerun()
        st.caption("Current availability has not been verified with the seller.")
