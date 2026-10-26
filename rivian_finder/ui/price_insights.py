"""Read-only summaries of observed seller price cuts, with sample support kept visible."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import price_insights as insights, queries
from . import common


def _window(summary: dict) -> str:
    first, last = summary.get("first_observed"), summary.get("latest_observed")
    if not first:
        return "no priced observation window"
    return common.local_time(first) + (" → " + common.local_time(last) if last and last != first else "")


def _net(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return ("+" if value > 0 else "-" if value < 0 else "") + common.money(abs(value))


def _gap(value) -> str:
    return "Not enough history" if value is None else f"{value:.1f} days"


def render(c, vehicle_id: int) -> None:
    result = insights.for_vehicle(c, vehicle_id)
    vehicle = result["vehicle"]
    st.subheader("Price-drop patterns")
    if vehicle is None:
        st.info("No usable recorded price history for this truck.")
        return
    st.caption("These are feed observations recorded by the app. The seller's actual change time is unknown; this is not a prediction of the next price cut.")
    if vehicle.get("source"):
        st.caption(f"Selected listing: {queries.source_label(vehicle['source'])} · {vehicle.get('seller_name') or 'seller unknown'} · "
                   f"recorded status {vehicle.get('listing_status') or 'unknown'} · {_window(vehicle)}")
        if vehicle.get("source_url"):
            st.link_button("Selected listing ↗", vehicle["source_url"])
    st.caption("One listing timeline per truck is used for these summaries, so mirrored source listings do not multiply the cuts. Recorded listing status does not confirm current availability.")
    if not vehicle.get("priced_observations"):
        st.info("No priced observations yet. There is not enough history to measure cuts or their timing.")
    else:
        a, b, d, e = st.columns(4)
        a.metric("Observed cuts", vehicle["drops_count"])
        b.metric("Average cut", common.money(vehicle.get("mean_cut")) if vehicle["drops_count"] else "—")
        d.metric("Total reductions", common.money(vehicle["total_reductions"]))
        e.metric("Net price change", _net(vehicle.get("net_change")))
        st.caption("Total reductions adds the downward moves; net price change also includes increases.")
        st.caption(f"{vehicle['priced_observations']} priced observations across {vehicle['observation_days']} distinct UTC dates · "
                   f"{vehicle.get('increases_count', 0)} observed increase(s).")
        st.metric("Observed gap between cuts", _gap(vehicle.get("mean_interval_days")))
        st.caption(f"Based on {vehicle['interval_count']} observed interval(s) on this truck's selected timeline.")
        if vehicle.get("mean_interval_days") is None:
            st.info("Not enough history for a gap between cuts. A single cut, no cuts, or captures from only one UTC date do not establish a schedule.")
        elif vehicle["interval_count"] == 1:
            st.info("Only one observed interval; this does not establish a recurring schedule.")
        with st.expander("Dated price cuts for this truck"):
            cuts = vehicle.get("cuts", [])
            if not cuts:
                st.write("No price cuts observed on the selected timeline.")
            else:
                table = pd.DataFrame(cuts)
                table["previous_observed_at"] = table["previous_observed_at"].map(common.local_time)
                table["detected_at"] = table["detected_at"].map(common.local_time)
                table["Source"] = queries.source_label(vehicle.get("source"))
                table["Listing"] = vehicle.get("source_url") or ""
                st.dataframe(table.rename(columns={"previous_observed_at": "Previously observed", "detected_at": "Cut detected",
                                                    "old_price": "Before", "new_price": "After", "amount": "Cut amount"}),
                             hide_index=True, column_config={
                                 "Before": st.column_config.NumberColumn(format="dollar", step=1),
                                 "After": st.column_config.NumberColumn(format="dollar", step=1),
                                 "Cut amount": st.column_config.NumberColumn(format="dollar", step=1),
                                 "Listing": st.column_config.LinkColumn(display_text="Open ↗"),
                             })
    if str(vehicle.get("make") or "").casefold() != "rivian":
        return
    cohort = result["rivian_seller"]
    st.markdown("**Official Rivian-seller benchmark**")
    st.caption("Uses saved historical Rivian-seller records, including provider-reported seller identities, regardless of Inventory filters; this is not complete nationwide inventory or a live availability check.")
    if not cohort.get("vehicle_count"):
        st.info("No official Rivian-seller price history has been recorded yet.")
        return
    a, b = st.columns(2)
    a.metric("Rivian seller: average cut", common.money(cohort.get("mean_cut")) if cohort["total_cuts"] else "—")
    b.metric("Rivian seller: observed gap", _gap(cohort.get("mean_interval_days")))
    st.caption(f"Sample: {cohort['total_cuts']} observed cuts across {cohort['cut_bearing_vehicles']} trucks with cuts "
               f"({cohort['vehicle_count']} trucks tracked) · {_window(cohort)}.")
    st.caption(f"Timing support: {cohort['interval_count']} interval(s) from {cohort['interval_vehicles']} truck(s). "
               f"{cohort['repeat_day_vehicles']} trucks have observations on multiple UTC dates.")
    if cohort["interval_count"] < 2 or cohort["interval_vehicles"] < 2:
        st.info("Insufficient history for a typical schedule. The observed average gap is not a reliable prediction of when Rivian will cut this truck's price.")
    if result.get("caveat"):
        st.caption(result["caveat"])
