"""Favorites ranked against personal requirements, with evidence and a seller-request draft."""
from __future__ import annotations

import copy

import pandas as pd
import streamlit as st

from .. import attributes, compare, config, matching
from ..models import AttributeClaim
from . import common

STATES = ["Unknown", "Advertised yes", "Advertised no", "Verified yes", "Verified no"]
PRIORITIES = {"ignore": "Ignore", "prefer": "Prefer", "must": "Required"}


def profile_editor(settings: dict) -> None:
    profile = {**config.default_settings()["shopping_profile"], **settings.get("shopping_profile", {})}
    with st.expander("My shopping profile"):
        st.caption("Required items need verified evidence. Advertised equipment stays a question to check. Leave preferences empty until you choose what matters.")
        st.caption("Range and towing targets are optional. Leave them at 0 and ignore equipment that does not apply to your vehicle search.")
        with st.form("shopping_profile"):
            a, b, c, d = st.columns(4)
            range_min = a.number_input("Minimum range (mi, 0 = no target)", 0, 600, int(profile["range_min"]), key="profile_range_min")
            range_priority = b.selectbox("Range importance", list(PRIORITIES), index=list(PRIORITIES).index(profile["range_priority"]),
                                         format_func=PRIORITIES.get, key="profile_range_priority")
            tow_min = c.number_input("Minimum towing (lb, 0 = no target)", 0, 40000, int(profile["tow_min"]), 500, key="profile_tow_min")
            tow_priority = d.selectbox("Towing importance", list(PRIORITIES), index=list(PRIORITIES).index(profile["tow_priority"]),
                                       format_func=PRIORITIES.get, key="profile_tow_priority")
            must = st.multiselect("Required equipment", list(matching.FEATURES), profile["must_have"],
                                   format_func=matching.FEATURES.get, key="profile_must_have")
            prefer = st.multiselect("Preferred equipment", list(matching.FEATURES), profile["prefer"],
                                     format_func=matching.FEATURES.get, key="profile_prefer")
            if st.form_submit_button("Save shopping profile", type="primary"):
                if set(must) & set(prefer):
                    st.error("Choose each feature as either required or preferred, not both.")
                else:
                    updated = copy.deepcopy(settings)
                    updated["shopping_profile"] = {**profile, "range_min": int(range_min), "range_priority": range_priority,
                                                   "tow_min": int(tow_min), "tow_priority": tow_priority,
                                                   "must_have": must, "prefer": prefer}
                    common.save_settings(updated)
                    common.flash("Shopping profile saved.")
                    st.rerun()


def seller_request(row, proof: list[dict], tow_required: bool = False) -> str:
    features = [item["label"] for item in proof if item["field"] in matching.FEATURES and item["status"] != "Verified"]
    lines = [f"Hi, I'm interested in the {compare.vehicle_name(row)}" + (f" (VIN {row['vin']})" if row.get("vin") else "") + ".",
             "Could you please send:",
             "- The original window sticker or build sheet for this VIN.",
             "- If electric, confirmation of the battery pack and EPA range for this exact configuration.",
             "- The warranty in-service date and remaining coverage dates and mileage limits."]
    if tow_required or any(item["field"] in ("tow_package", "trailer_brake_controller") for item in proof):
        lines.append("- A photo of the door-jamb payload sticker and documentation of this vehicle's tow rating and fitted tow equipment.")
    if features:
        lines.append("- VIN-specific evidence confirming: " + ", ".join(features) + ".")
    lines.append("- A written out-the-door quote including mandatory add-ons and delivery costs.")
    return "\n".join(lines)


def _save_feature(c, vid: int, field: str, state: str, note: str) -> None:
    if field not in matching.FEATURES or state not in STATES:
        raise ValueError("Choose a supported feature and evidence state.")
    if state != "Unknown" and not note.strip():
        raise ValueError("Add the source or how you checked this feature before saving.")
    value = "yes" if state.endswith("yes") else "no"
    with c:
        if state.startswith("Advertised"):
            attributes.record_claims(c, vid, [AttributeClaim(field, value, "medium", "Seller claim recorded by user",
                                                           source="user_advertised", evidence=note.strip())])
        attributes.set_override(c, vid, field, value if state.startswith("Verified") else None, note.strip())


def feature_form(c, vid: int, resolved: dict) -> None:
    field = st.selectbox("Feature to update", list(matching.FEATURES), format_func=matching.FEATURES.get,
                         key=f"shortlist_feature_{vid}")
    current = resolved.get(field)
    state = ("Verified " if current.confidence == "verified" else "Advertised ") + current.value if current and current.value in ("yes", "no") else "Unknown"
    key = common.table_key(f"shortlist_state_{vid}_{field}")
    with st.form(f"shortlist_proof_{vid}_{field}"):
        selected = st.selectbox("Evidence state", STATES, index=STATES.index(state), key=key)
        note = st.text_area("Evidence / source", key=key + "_note", height=80,
                            placeholder="Seller's listing URL, or what you personally checked on the vehicle or VIN-specific records")
        st.caption("Use Verified only for something you personally confirmed. Unknown removes your verified override; earlier source claims remain and may still supply an advertised answer.")
        if st.form_submit_button("Save feature evidence"):
            try:
                _save_feature(c, vid, field, selected, note)
            except ValueError as exc:
                st.error(str(exc))
            else:
                common._bump(f"shortlist_state_{vid}_{field}")
                common.flash("Evidence saved. The displayed result uses the strongest available source; source history is preserved.")
                st.rerun()


def render() -> None:
    c, s = common.conn(), common.settings()
    st.title("My shortlist")
    st.caption("Favorite vehicles in Inventory to keep them here. Use the optional shopping profile to rank requirements "
               "and preferences, then record evidence before deciding.")
    profile_editor(s)
    f = s["filters"]
    st.caption(f"Saved limits: price {common.money(f['max_price']) if f.get('max_price') else 'any'} · "
               f"mileage {str(f['max_miles']) + ' mi' if f.get('max_miles') else 'any'} · "
               f"distance {str(f['max_distance']) + ' mi' if f.get('max_distance') else 'any'}. Save as my default filters in Inventory, or edit Settings, to change these limits.")
    inv = common.inventory(s)
    favorites = inv[inv["favorite"] & ~inv["hidden"]] if not inv.empty else inv
    if favorites.empty:
        st.info("Favorite vehicles in Inventory to build your shortlist. Vehicles marked Not interested stay hidden here.")
        return
    resolved = attributes.resolve_many(c, favorites["vehicle_id"].astype(int).tolist())
    ranked = [(row, matching.evaluate(row, s, resolved.get(int(row["vehicle_id"]), {}))) for _, row in favorites.iterrows()]
    order = {status: index for index, status in enumerate(matching.MATCH_STATUSES)}
    ranked.sort(key=lambda item: (0 if item[0].get("status") == "active" else 1,
                                   order[item[1]["match_status"]], -item[1]["match_score"],
                                   item[0]["price"] if pd.notna(item[0]["price"]) else float("inf")))
    st.caption("All visible favorites are shown, including those outside other Inventory filters. Missing evidence stays visible as a question to resolve.")
    for row, match in ranked:
        vid = int(row["vehicle_id"])
        with st.container(border=True):
            head, action = st.columns([4, 1])
            head.markdown(common.md(f"**{compare.vehicle_name(row)}** · {common.money(row['price'])}"))
            head.caption(f"{match['match_status']} · {match['match_score']}/100 personal score · {row.get('sold_by') or row.get('seller') or ''}")
            head.caption(f"Stored listing: {row.get('status') or 'unknown'} · {row.get('location') or 'location unknown'} · "
                         f"last seen {common.local_time(row.get('last_seen'))}")
            if action.button("Open details", key=f"shortlist_open_{vid}", width="stretch"):
                common.open_vehicle(vid)
            if row.get("status") == "missing":
                st.warning("Availability needs checking: this listing is missing; this does not confirm a sale.")
            elif row.get("status") == "removed":
                st.warning("This listing is marked sold/removed. Confirm availability with the seller before proceeding.")
            if match["match_failures"]:
                st.warning("Does not meet: " + "; ".join(match["match_failures"]))
            if match["match_missing"]:
                st.info("Need proof: " + "; ".join(match["match_missing"]))
            if match["match_preferred"]:
                st.caption("Preferences: " + "; ".join(match["match_preferred"]))
            with st.expander("Evidence and seller request"):
                if match["match_reasons"]:
                    st.caption("Fits: " + "; ".join(match["match_reasons"]))
                proof = matching.proof_items(row, s, resolved.get(vid, {}))
                st.dataframe(pd.DataFrame(proof)[["label", "status", "evidence"]].rename(
                    columns={"label": "Item", "status": "Evidence status", "evidence": "Source / evidence"}), hide_index=True)
                st.caption("Copy this request and edit it before contacting the seller. Nothing is sent from the app.")
                st.code(seller_request(row, proof, bool(s.get("shopping_profile", {}).get("tow_min"))), language=None)
                st.caption("Record range, tow capacity and warranty dates under Open details → Verify equipment or Quick verify.")
                feature_form(c, vid, resolved.get(vid, {}))
