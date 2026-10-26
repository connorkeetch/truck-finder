"""Inventory — the main workspace. Find, filter, compare and add trucks without leaving this page.

The table keeps to columns that help compare trucks. Motor, transport and notes are edited right in it (saved as
your verified values, kept through every search). Clicking a truck's name opens its full details in a pop-up —
favorite, not interested, battery, in-service date and warranty live there. The ✓ column selects trucks to
compare or hide together.
"""
from __future__ import annotations

import copy
import re
from datetime import date

import pandas as pd
import streamlit as st

from .. import adjust, attributes, compare, config, deals, hiding, linkcheck, matching, queries, services, subframe, warranty
from ..config import BATTERIES, GENERATIONS, MOTORS, TONNEAU_STATUSES, US_STATES
from ..sources.base import SUPPORTED_BRANDS, search_targets
from . import add_truck, cards, common, compare_page, refresh_changes, vehicle

EDITABLE = ["pick", "motor_edit", "transport_edit", "notes"]
SELECTED = "inv_selected"          # vehicle ids ticked in the ✓ column (compare / hide several at once)
CARDS_PAGE = 40                    # cards shown before "Show more"


def filter_controls(f: dict, key: str = "inv", trim_options: list[str] | None = None,
                    brand_options: list[str] | None = None, model_options: list[str] | None = None) -> dict:
    """Render filter widgets initialised from `f`; returns the edited copy."""
    f = copy.deepcopy(f)
    brands = sorted(set(SUPPORTED_BRANDS if brand_options is None else brand_options) | set(f.get("brands") or []))
    f["brands"] = st.multiselect("Brands (empty = all trucks)", brands,
                                  f.get("brands") or [], key=f"{key}_brands")
    selected_models = f.get("models") or []
    f["models"] = st.multiselect("Models (empty = all)", sorted(set(model_options or []) | set(selected_models)),
                                  selected_models, key=f"{key}_models")
    show_rivian = any(brand.casefold() == "rivian" for brand in (f["brands"] or brands))
    selected_trims = f.get("trims") or []
    f["trims"] = st.multiselect("Trims (empty = all)", sorted(set(trim_options or []) | set(selected_trims)),
                                 selected_trims, key=f"{key}_trims",
                                 help="Trims from stored inventory, grouped by brand. Collection-scope exclusions still apply.")
    c1, c2, c3 = st.columns(3)
    f["deal_types"] = c1.multiselect("Deal rating (empty = all)", deals.DEAL_TYPES, f.get("deal_types") or [],
                                      key=f"{key}_deal_types",
                                      help="Based on similar vehicles in your saved inventory. Not rated can mean there is not enough data. Accident warnings remain visible.")
    f["seller_types"] = c2.multiselect("Seller type (empty = all)", queries.SELLER_TYPES,
                                        f.get("seller_types") or [], key=f"{key}_seller_types",
                                        format_func=lambda value: {"private": "Private seller"}.get(value, value.title()))
    f["price_drops_only"] = c3.checkbox("Only listings with price drops", f.get("price_drops_only", False),
                                         key=f"{key}_price_drops",
                                         help="At least one price drop anywhere in the app's recorded history, including before the latest refresh.")
    f["match_statuses"] = st.multiselect("My requirements (empty = all)", matching.MATCH_STATUSES,
                                          f.get("match_statuses") or [], key=f"{key}_match_statuses",
                                          help="Set must-haves and preferences in My shortlist. Unverified equipment needs proof before it meets a requirement.")
    c1, c2, c3, c4 = st.columns(4)
    f["min_range"] = c1.number_input("Minimum EPA range (mi, 0 = any)", 0, 600, int(f.get("min_range") or 0),
                                      key=f"{key}_range")
    f["include_unknown_range"] = c2.checkbox("Include unknown range", f.get("include_unknown_range", True),
                                             key=f"{key}_unknown_range",
                                             help="Unverified range stays visible so good candidates aren't lost. Untick for a strict range filter.")
    if show_rivian:
        st.caption("Generation, battery, motor and front-subframe filters apply to Rivians. Other brands use their own listed specifications.")
    c1, c2, c3, c4 = st.columns(4)
    f["max_price"] = c1.number_input("Max price ($)", 0, 250000, int(f["max_price"]), 1000, key=f"{key}_price")
    f["max_miles"] = c2.number_input("Max mileage", 0, 300000, int(f["max_miles"]), 1000, key=f"{key}_miles")
    f["year_min"], f["year_max"] = c3.slider("Model years", min(1900, int(f["year_min"])), max(2027, int(f["year_max"])), (int(f["year_min"]), int(f["year_max"])),
                                             key=f"{key}_years")
    f["max_distance"] = c4.number_input("Max distance from home (mi, 0 = any)", 0, 4000, int(f.get("max_distance") or 0),
                                        50, key=f"{key}_dist")
    c1, c2, c3, c4 = st.columns(4)
    if show_rivian:
        f["generations"] = c1.multiselect("Rivian generation", GENERATIONS, f["generations"], key=f"{key}_gen")
        f["batteries"] = c2.multiselect("Rivian battery", BATTERIES, f["batteries"], key=f"{key}_bat",
                                    help="Trucks whose sources disagree on battery are kept if any claimed pack matches")
        f["motors"] = c3.multiselect("Rivian motor", MOTORS, f["motors"], key=f"{key}_mot")
    f["tonneau"] = c4.multiselect("Powered tonneau", list(TONNEAU_STATUSES), f["tonneau"],
                                  format_func=lambda k: TONNEAU_STATUSES[k], key=f"{key}_ton")
    c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 1, 1])
    f["states"] = c1.multiselect("States (empty = nationwide)", US_STATES, f["states"], key=f"{key}_states")
    if show_rivian:
        f["subframes"] = c1.multiselect(
        "Rivian front subframe", list(subframe.LABELS), f.get("subframes") or list(subframe.LABELS),
        format_func=subframe.LABELS.get, key=f"{key}_subframe",
        help="Early R1Ts had a welded front subframe that could crack; Rivian switched to a cast one in early 2023. "
             "Estimated from the VIN (2022 welded, 2024+ cast, 2023 by build serial — 'Unsure' near the switch). "
             "A welded one may have been replaced with cast under warranty.")
    f["hide_branded_title"] = c2.checkbox("Hide branded titles", f["hide_branded_title"], key=f"{key}_brand")
    f["hide_reported_accidents"] = c3.checkbox("Hide reported accidents", f["hide_reported_accidents"], key=f"{key}_acc")
    f["include_missing"] = c4.checkbox("Show missing/removed", f["include_missing"], key=f"{key}_missing")
    f["show_hidden"] = c5.checkbox("Show 'not interested'", f.get("show_hidden", False), key=f"{key}_hidden")
    c1, c2, c3, c4 = st.columns(4)
    f["near_misses"] = c1.checkbox("Include near misses", f.get("near_misses", True), key=f"{key}_near",
                                   help="Also show trucks slightly over your max price or miles (marked ⚠ next to the "
                                        "truck's name; the reason is at the top of its details)")
    f["near_miss_price_pct"] = c2.number_input("…up to % over max price", 0, 30, int(f.get("near_miss_price_pct", 5)),
                                               key=f"{key}_nearp")
    f["near_miss_miles_pct"] = c3.number_input("…up to % over max miles", 0, 50, int(f.get("near_miss_miles_pct", 10)),
                                               key=f"{key}_nearm")
    f["count_discounts"] = c4.checkbox("Use my price after discounts", f.get("count_discounts", True), key=f"{key}_disc",
                                       help="e.g. Carvana's trade-in discount (Settings → Loan assumptions)")
    return f


def _close_details():
    st.session_state.pop("dialog_vid", None)


def _close_compare():
    st.session_state.pop("compare_open", None)


@st.dialog("Truck details", width="large", on_dismiss=_close_details)
def details_dialog(vid: int, note: str = "") -> None:
    c = common.conn()
    s = common.settings()
    inv = common.inventory(s)
    if vid not in set(inv["vehicle_id"]):
        st.write("That truck isn't available any more.")
        return
    if note:
        st.info(note)
    vehicle.render_truck(c, s, inv, vid)


@st.dialog("Compare", width="large", on_dismiss=_close_compare)
def compare_dialog(ids: list[int]) -> None:
    inv = common.inventory()
    ids = [i for i in ids if i in set(inv["vehicle_id"])]
    if len(ids) < 2:
        st.write("Select at least two trucks with ✓.")
        return
    compare_page.render_compare(inv, ids, on_details=_details_from_compare)


def _details_from_compare(vid: int) -> None:
    st.session_state.pop("compare_open", None)
    st.session_state["dialog_vid"] = vid
    st.rerun()


def _looks_like_lookup(q: str) -> bool:
    q = q.strip()
    return bool(q) and (q.lower().startswith(("http://", "https://")) or bool(re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", q.upper()))
                        or bool(re.fullmatch(r"\d{6,}", q)))


def _money(v) -> str:
    return "" if v is None or pd.isna(v) else f"${v:,.0f}"


def _signed_money(v) -> str:
    return "" if v is None or pd.isna(v) else f"{'+' if v > 0 else '−' if v < 0 else ''}${abs(v):,.0f}"


def table_view(df: pd.DataFrame, picks: set[int]) -> pd.DataFrame:
    """Display columns for the Inventory table (combined where two values belong together)."""
    view = common.add_photo_column(df)
    view["pick"] = view["vehicle_id"].isin(picks)
    view["updates"] = [" · ".join(b["text"] for b in r.get("refresh_badges", [])) for r in view.to_dict("records")]
    view["name"] = [("★ " if r["favorite"] else "") + compare.vehicle_name(r)
                    + (" ⚠" if r["_near"] else "") + "  ›" for _, r in view.iterrows()]
    view["location_dist"] = [loc + (f" · {d:,.0f} mi" if d == d and d is not None else "")
                             for loc, d in zip(view["location"], view["distance_mi"])]
    view["price_text"] = [_money(yp) + (f" (list {_money(p)})" if yp == yp and p == p and yp < p else "")
                          if yp == yp else _money(p) for p, yp in zip(view["price"], view["your_price"])]
    view["adjusted_text"] = [_money(a) for a in view["adjusted_price"]]
    view["adjust_note"] = [" · ".join(x for x in (n, f"❓ confirm {c}" if c else "") if x)
                           for n, c in zip(view["adjust_note"], view["to_confirm"])]
    view["market_text"] = [_signed_money(d) + (f" (mkt {_money(m)})" if m == m else "")
                           for d, m in zip(view["deal_delta"], view["market_price"])]
    view["battery_range"] = [("Uncertain" if unsure else b) + (f" · {rt}" if rt else " · range unknown — verify")
                             for b, unsure, rt in zip(view["battery"], view["battery_uncertain"], view["range_text"])]
    view["motor_edit"] = view.apply(lambda r: "Uncertain" if r["motor_uncertain"] else r["motor"], axis=1)
    view["warranty_ends"] = [warranty.ends_text(e, m) for e, m in zip(view["warranty_expires"],
                                                                        view["warranty_miles_limit"])]
    view["warranty_left"] = [re.sub(r"\s*\(to [^)]*\)$", "", w) if e else ""
                             for w, e in zip(view["warranty"], view["warranty_expires"])]
    view["link"] = view["link_result"].map(linkcheck.label)
    view["subframe_label"] = view["subframe"].map(lambda s: subframe.LABELS.get(s, s))
    view["transport_edit"] = view["transport_cost"]
    view["flags"] = view["flags"].map(lambda x: f"🔁 {x}" if x else "")
    view["match_details"] = [" · ".join([*r.get("match_failures", []), *r.get("match_missing", []),
                                        *r.get("match_reasons", [])]) for r in view.to_dict("records")]
    view["first_seen"] = view["first_seen"].str.slice(0, 10)
    return view


# pinned (stay put while you scroll right): ✓, photo, truck (click = details), sold by
COLUMNS = ["pick", "photo", "name", "sold_by", "updates", "location_dist", "match_status", "match_score", "match_details", "seller_url", "link", "deal_label",
           "price_text", "adjusted_text", "adjust_note",
           "est_monthly", "transport_edit", "market_text", "miles", "battery_range", "tow_capacity_lbs", "tow_src", "tow_conf", "battery_note", "motor_edit",
           "warranty_ends", "warranty_left", "subframe_label", "notes", "days_listed", "price_drops", "leverage", "generation", "color",
           "flags", "history_report_url", "find_seller_url", "status", "first_seen", "vin", "vehicle_id", "listing_id"]
LABELS = {"name": "Truck", "sold_by": "Sold by", "updates": "Updates", "location_dist": "Location",
          "match_status": "My requirements", "match_score": "Personal score", "match_details": "Match details",
          "seller_url": "Seller listing", "link": "Link", "deal_label": "Deal", "adjusted_text": "Adjusted price",
          "adjust_note": "Adjustments", "price_text": "Price", "est_monthly": "Est. /mo",
          "transport_edit": "Transport", "market_text": "vs market", "miles": "Miles",
          "battery_range": "Battery · EPA range (mi)", "battery_note": "Battery sources", "motor_edit": "Motor",
          "tow_capacity_lbs": "Tow capacity (lb)", "tow_src": "Tow source", "tow_conf": "Tow confidence",
          "warranty_ends": "Warranty ends", "warranty_left": "Warranty left", "subframe_label": "Front subframe",
          "notes": "Notes",
          "days_listed": "Days listed", "price_drops": "Drops", "leverage": "Leverage", "generation": "Gen",
          "color": "Color", "flags": "History flags", "history_report_url": "Carfax", "find_seller_url": "Find seller",
          "status": "Status", "first_seen": "First seen", "vin": "VIN"}


def column_config(view: pd.DataFrame, row_h: int) -> dict:
    return {
        "pick": st.column_config.CheckboxColumn("✓", width=40, pinned=True,
                                                help="Select trucks to compare (2–4) or hide several at once — the "
                                                     "actions appear above the results"),
        "photo": st.column_config.ImageColumn("Photo", width=int(row_h * 4 / 3), pinned=True),
        "name": st.column_config.ButtonColumn("Truck", width="medium", type="tertiary", pinned=True, alignment="left",
                                              key="inv_open_click", on_click=_open_clicked,
                                              args=([int(v) for v in view["vehicle_id"]],),
                                              help="Click for full details · ★ favorite · ⚠ near miss (a little over "
                                                   "your max price or miles)"),
        "sold_by": st.column_config.TextColumn("Sold by", width="medium", pinned=True),
        "updates": st.column_config.TextColumn("Updates", width="medium", help="Recorded changes from the latest refresh and subsequent updates."),
        "location_dist": st.column_config.TextColumn("Location", width=190, help="Straight-line distance from your ZIP"),
        "match_status": st.column_config.TextColumn("My requirements", width="medium"),
        "match_score": st.column_config.ProgressColumn("Personal score", min_value=0, max_value=100, format="%d",
                                                       help="Ranks saved preferences and room under your budget, mileage and distance limits. Proof status is shown separately."),
        "match_details": st.column_config.TextColumn("Match details", width="large"),
        "seller_url": st.column_config.LinkColumn("Seller listing", display_text="seller ↗"),
        "link": st.column_config.TextColumn("Link", width=80,
                                            help="Last 'Check listing links' result: ✓ live · ✗ gone · ↪ moved (usually "
                                                 "sold) · ⚠ sold? · ? check = open it yourself (site blocks automated "
                                                 "checks, or it's a search page). Details in the truck's pop-up."),
        "deal_label": st.column_config.TextColumn("Deal", help="Price vs. similar trucks in your data"),
        "price_text": st.column_config.TextColumn("Price", width=170, help="Your price after seller discounts that apply "
                                                                "(e.g. Carvana trade-in), with the list price"),
        "adjusted_text": st.column_config.TextColumn("Adjusted", width=95,
                                                     help="Your price + shipping − what the features are worth to you "
                                                          "(💲 My price adjustments)"),
        "adjust_note": st.column_config.TextColumn("Adjustments", width="medium"),
        "est_monthly": st.column_config.NumberColumn("Est. /mo", format="dollar", step=1),
        "transport_edit": st.column_config.NumberColumn("Transport", format="dollar", step=50, min_value=0,
                                                        help="Estimate or 'included by seller'; type your own amount"),
        "market_text": st.column_config.TextColumn("vs market", width=170, help="Asking price minus the market estimate from "
                                                                     "similar trucks in your data"),
        "miles": st.column_config.NumberColumn("Miles", format="%,d"),
        "battery_range": st.column_config.TextColumn(
            "Battery · EPA range (mi)", width=190, help="'Uncertain' = sources disagree (never filtered out; settle it in the "
                                             "truck's details). Range is listed, or the official EPA rating — a span "
                                             "when wheels or battery are unknown"),
        "battery_note": st.column_config.TextColumn("Battery sources", help="Who says what when sources disagree"),
        "tow_capacity_lbs": st.column_config.NumberColumn("Tow capacity (lb)", format="%,d",
                                                         help="Listed or verified for this truck. Confirm configuration, tow package and payload before towing."),
        "tow_src": st.column_config.TextColumn("Tow source"),
        "tow_conf": st.column_config.TextColumn("Tow confidence"),
        "motor_edit": st.column_config.TextColumn("Motor", help="Enter the motor configuration you verified; blank returns to sources."),
        "warranty_ends": st.column_config.TextColumn("Warranty ends", width=130, help="Comprehensive coverage: date or mileage, "
                                                                           "whichever comes first"),
        "warranty_left": st.column_config.TextColumn("Warranty left", width=130, help="Blank until you enter the in-service date "
                                                                           "or warranty dates in the truck's details"),
        "subframe_label": st.column_config.TextColumn("Front subframe", width="small",
                                                      help="Welded (early R1T) or cast — estimated from the VIN"),
        "notes": st.column_config.TextColumn("Notes", width="large"),
        "days_listed": st.column_config.NumberColumn("Days listed", format="%d"),
        "price_drops": st.column_config.NumberColumn("Drops", format="%d"),
        "leverage": "Leverage", "generation": "Gen", "color": "Color", "flags": "History flags",
        "history_report_url": st.column_config.LinkColumn("Carfax", display_text="report ↗"),
        "find_seller_url": st.column_config.LinkColumn("Find seller", display_text="search ↗"),
        "status": "Status", "first_seen": "First seen", "vin": "VIN", "vehicle_id": None, "listing_id": None,
    }


def render() -> None:
    c = common.conn()
    s = common.settings()
    st.title("Inventory")
    refresh = queries.refresh_changes(c)
    refresh_changes.render(c, s, refresh)
    inv = queries.attach_refresh_badges(common.inventory(s), refresh)
    add_truck.add_truck_panel(inv)
    if inv.empty:
        st.info("No trucks yet. Press **Run Search** in the sidebar, or add one above.")
        refresh_changes.render_retired(c, s, inv, refresh, key="inv_retired")
        return

    if "inv_filters" not in st.session_state:
        st.session_state["inv_filters"] = copy.deepcopy(s["filters"])
    with st.expander("Filters", expanded=False):
        try:
            targets = search_targets(s["collection"])
        except ValueError:
            targets = []
            st.warning("Repair your make/model searches in Settings → Collection scope.")
        f = filter_controls(st.session_state["inv_filters"], trim_options=inv["trim_filter"].unique().tolist(),
                            brand_options=inv["make"].dropna().tolist() + [t["make"] for t in targets],
                            model_options=inv["model"].dropna().tolist() + [t["model"] for t in targets])
        b1, b2, _ = st.columns([1, 1, 4])
        if b1.button("Save as my default filters"):
            s["filters"] = f
            common.save_settings(s)
            st.toast("Default filters saved")
        if b2.button("Reset to defaults"):
            st.session_state.pop("inv_filters", None)
            for k in list(st.session_state):
                if k.startswith("inv_") and k != "inv_search":
                    st.session_state.pop(k, None)
            st.rerun()
    st.session_state["inv_filters"] = f
    adjustments_editor(s)

    search = st.text_input("Search — or paste a VIN / listing link to find any truck", key="inv_search",
                            placeholder="e.g. Blue, Denver, 7FCTGBAL2RN900101, https://www.carvana.com/vehicle/…")
    n_hidden = int(inv["hidden"].sum())
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        sort = st.selectbox("Sort by", queries.SORT_OPTIONS, key="inv_sort", width=230)
        updates = st.selectbox("Updates", ["All trucks", "Changed since refresh", "New / new source", "Price changes",
                                           "Listing status changes"], key="inv_updates", width=230,
                               help="Filter recorded changes from the latest refresh and later updates. Other filters still apply. Unavailable trucks are below the results.")
        f["favorites_only"] = st.toggle("★ Favorites only", f.get("favorites_only", False))
        f["hidden_only"] = st.toggle(f"🚫 Hidden ({n_hidden})", False, key="inv_hidden_only",
                                      help="Only trucks marked Not interested. Select and Restore, or restore from the truck's details.")
        if st.button("▶ Refresh", key="inv_refresh", help="Choose which brands to refresh before starting a search."):
            common.search_dialog()
    with st.expander("Display options"):
        size = common.photo_size_control("inv_photo_size")
        layout = _view_control(s)
    row_h = common.PHOTO_SIZES[size]

    # ---- which trucks to show
    lookup = _looks_like_lookup(search)
    strict = {**f, "near_misses": False}
    if lookup:
        df = queries.find_trucks(inv, search)
        shown = set(queries.apply_filters(inv, f)["vehicle_id"])
        if df.empty:
            st.warning("No truck in your data matches that VIN or link. Use **➕ Add a truck → By VIN** to look it up.")
        for _, r in df.iterrows():
            why = queries.why_hidden(r, strict)
            if r["vehicle_id"] in shown and not why:
                st.success(common.md(f"Found: {common.vehicle_label(r)} — it's in your list."))
            else:
                st.info(common.md(f"Found: {common.vehicle_label(r)} — hidden by your filters: " + "; ".join(why)))
        df = df.assign(_near=False)
        if updates != "All trucks":
            st.caption("Exact VIN and listing-link lookups also include trucks outside the Updates filter.")
    else:
        df = queries.apply_filters(inv, f, search)
        categories = {"All trucks": [], "Changed since refresh": ["new", "price", "removed", "missing"],
                      "New / new source": ["new"], "Price changes": ["price"],
                      "Listing status changes": ["removed", "missing"]}
        df = queries.filter_refresh_changes(df, categories[updates])
        in_filters = set(queries.apply_filters(inv, strict, search)["vehicle_id"])
        df = df.assign(_near=~df["vehicle_id"].isin(in_filters))
    df = queries.sort_inventory(df, sort)
    near = int(df["_near"].sum()) if not df.empty else 0
    hint = (" · **click a photo or name** for full details · ☆ adds a favorite · tick a photo's box to compare or "
            "hide several"
            if layout == "Cards" else " · **click a truck's name** for full details · ✓ selects trucks to compare or "
                                      "hide together · columns with a ✎ pencil are editable · scroll right for more")
    st.caption(f"Showing **{len(df)}** of {len(inv)} trucks" + (f" (incl. {near} near miss{'es' if near != 1 else ''}, "
                                                               "marked ⚠)" if near else "") + hint)
    if df.empty:
        if not lookup:
            st.info("No trucks match these filters. Unavailable trucks are listed below.")
        refresh_changes.render_retired(c, s, inv, refresh, key="inv_retired")
        return

    picks = set(st.session_state.get(SELECTED, set())) & set(inv["vehicle_id"])
    if picks:
        _selection_box(c, inv, picks)
    view = table_view(df, picks)
    if layout == "Cards":
        limit = st.session_state.get("inv_cards_limit", CARDS_PAGE)
        cards.render(cards.payload(view.head(limit), picks, f), "inv_cards", _on_card_action, size)
        if len(view) > limit:
            if st.button(f"Show {min(CARDS_PAGE, len(view) - limit)} more  ({len(view) - limit} left)", key="inv_more"):
                st.session_state["inv_cards_limit"] = limit + CARDS_PAGE
                st.rerun()
    else:
        _table(view, row_h)

    # ---- selection actions, details, compare
    csv = view[[col for col in COLUMNS if col in LABELS]].rename(columns=LABELS)
    csv["Truck"] = csv["Truck"].str.replace(r"\s*›$", "", regex=True)
    st.download_button("Download this view as CSV", csv.to_csv(index=False), file_name="rivian_inventory_view.csv",
                       mime="text/csv")
    refresh_changes.render_retired(c, s, inv, refresh, key="inv_retired")
    if st.session_state.get("dialog_vid"):
        vid = int(st.session_state["dialog_vid"])
        hit = df[df["vehicle_id"] == vid]
        note = ""
        if not hit.empty and bool(hit["_near"].iloc[0]):
            note = "⚠ Near miss: " + "; ".join(queries.why_hidden(hit.iloc[0], strict))
        details_dialog(vid, note)
    elif st.session_state.get("compare_open") and 2 <= len(picks) <= 4:
        compare_dialog(sorted(picks))


def adjustments_editor(s: dict) -> None:
    """💲 My price adjustments — what features are worth to you, and whether shipping counts."""
    cfg = s.get("adjustments") or {}
    with st.expander("💲 My price adjustments", expanded=False):
        st.caption("Your **adjusted price** = your price + shipping − what the features are worth to you. A positive "
                   "amount makes a truck more valuable to you (lower adjusted price); use a negative amount for things "
                   "you'd want a discount for, e.g. Front subframe = welded → −2000. Colors and wheels match on part of "
                   "the name (\"white\" matches Glacier White).")
        ship = st.checkbox("Count shipping", cfg.get("include_shipping", True), key="adj_ship")
        wv = {**config.DEFAULT_SETTINGS["adjustments"]["warranty_value"],
              **(cfg.get("warranty_value") or {})}
        w1, w2, w3, w4 = st.columns([1.3, 1, 1.2, 1])
        wv["enabled"] = w1.checkbox("Value warranty months", wv["enabled"], key="adj_w_on",
                                    help="Each month of comprehensive warranty beyond (or short of) the baseline "
                                         "date adjusts the price. Months = date or mileage cap, whichever runs out "
                                         "first at your driving pace. Unknown warranties are estimated from the "
                                         "model year (marked est.).")
        wv["per_month"] = w2.number_input("$ per month", 0.0, 1000.0, float(wv["per_month"]), 10.0, key="adj_w_rate",
                                          help="Your value for an extra month of confirmed coverage.")
        base = date.fromisoformat(wv["baseline"][:10]) if wv.get("baseline") else date.today()
        wv["baseline"] = w3.date_input("Baseline warranty end", base, format="MM/DD/YYYY", key="adj_w_base",
                                       help="Only decides who shows a bonus vs a penalty — it doesn't change the "
                                            "order").isoformat()
        wv["annual_miles"] = w4.number_input("Miles / year", 0, 50000, int(wv["annual_miles"]), 1000, key="adj_w_miles")
        rv = {**config.DEFAULT_SETTINGS["adjustments"]["range_value"],
              **(cfg.get("range_value") or {})}
        r1, r2, r3, r4, r5 = st.columns([1.3, 0.9, 0.9, 0.9, 0.9])
        rv["enabled"] = r1.checkbox("Penalize low range", rv["enabled"], key="adj_r_on",
                                    help="Range = your number (Verify equipment) → the official EPA rating for the "
                                         "year/motor/battery/wheels → the listed range. When wheels are unknown (or "
                                         "the battery is disputed) only the best case of the EPA span counts and the "
                                         "truck is tagged ❓ confirm wheels. Set wheels in Quick verify.")
        rv["ok_at"] = r2.number_input("No penalty from (mi)", 0, 500, int(rv["ok_at"]), 5, key="adj_r_ok")
        rv["per_mile"] = r3.number_input("$ per mile below", 0.0, 500.0, float(rv["per_mile"]), 5.0, key="adj_r_pm")
        rv["floor"] = r4.number_input("Hard floor (mi)", 0, 500, int(rv["floor"]), 5, key="adj_r_floor")
        rv["per_mile_below_floor"] = r5.number_input("Extra $ per mile under floor", 0.0, 500.0,
                                                     float(rv["per_mile_below_floor"]), 5.0, key="adj_r_extra")
        from .. import shipping as _ship
        fd = {**_ship.DEFAULTS["fly_drive"], **((s.get("shipping") or {}).get("fly_drive") or {})}
        f1, f2, f3, f4 = st.columns([1.3, 1, 1.2, 1])
        fd["enabled"] = f1.checkbox("Fly & drive when cheaper", fd["enabled"], key="adj_fd_on",
                                    help="For the EV truck presets, within a day's drive, flying out and driving it home (flight + rideshare/food "
                                         "+ fast charging after the charge it's handed over with) replaces the shipping "
                                         "estimate when it's cheaper. Not used for Carvana (they deliver).")
        fd["flight"] = f2.number_input("Flight ($)", 0.0, 1000.0, float(fd["flight"]), 10.0, key="adj_fd_flight")
        fd["price_per_kwh"] = f3.number_input("Fast charging ($/kWh)", 0.0, 2.0, float(fd["price_per_kwh"]), 0.05,
                                              format="%.2f", key="adj_fd_kwh")
        fd["max_road_miles"] = f4.number_input("Max drive (road mi)", 0, 2000, int(fd["max_road_miles"]), 50,
                                               key="adj_fd_max")
        rows = pd.DataFrame(cfg.get("rules") or [], columns=["field", "match", "amount"])
        edited = st.data_editor(rows, num_rows="dynamic", hide_index=True, key="adj_rules", width="stretch",
                                column_config={
                                    "field": st.column_config.SelectboxColumn("Feature", options=list(adjust.FIELDS),
                                                                              required=True),
                                    "match": st.column_config.TextColumn("Is / contains", required=True,
                                                                         help="e.g. white · yes · Max · Quad · welded · 2024"),
                                    "amount": st.column_config.NumberColumn("Worth to me ($)", format="dollar", step=100)})
        st.caption("Feature values: " + " · ".join(f"**{k}** = {v}" for k, v in adjust.FIELDS.items())
                   + " · tonneau: yes / no · subframe: cast / welded. Unsure / unknown values are never priced — "
                   "the truck gets a ❓ confirm tag instead.")
        if st.button("Save adjustments", type="primary", key="adj_save"):
            rules = [{"field": r["field"], "match": str(r["match"]).strip(), "amount": float(r["amount"] or 0)}
                     for r in edited.to_dict("records") if r.get("field") in adjust.FIELDS and str(r.get("match") or "").strip()]
            s["adjustments"] = {"include_shipping": bool(ship), "rules": rules, "warranty_value": wv, "range_value": rv}
            s.setdefault("shipping", {})["fly_drive"] = fd
            common.save_settings(s)
            common.flash(f"Saved {len(rules)} adjustment(s). Sort by **Adjusted price ↑** to compare.")
            st.rerun()


def _view_control(s: dict) -> str:
    """Cards / Table, remembered between visits."""
    current = (s.get("ui") or {}).get("inventory_view", "Cards")
    choice = st.segmented_control("View", ["Cards", "Table"], default=current, key="inv_view") or current
    if choice != current:
        s.setdefault("ui", {})["inventory_view"] = choice
        common.save_settings(s)
    return choice


def _on_card_action() -> None:
    """A card was clicked: open its details, or (un)select it."""
    state = st.session_state.get("inv_cards") or {}
    act = state.get("action") if hasattr(state, "get") else getattr(state, "action", None)
    if not act:
        return
    vid = int(act["vid"])
    if act.get("kind") == "fav":
        services.toggle_favorite(common.conn(), vid, bool(act.get("on")))
        common._bump("inv_editor")
    elif act.get("kind") == "toggle":
        picks = set(st.session_state.get(SELECTED, set()))
        (picks.add if act.get("on") else picks.discard)(vid)
        st.session_state[SELECTED] = picks
        common._bump("inv_editor")                  # keep the table view's ✓ column in step
    else:
        st.session_state.pop("compare_open", None)
        st.session_state["dialog_vid"] = vid


def _table(view: pd.DataFrame, row_h: int) -> None:
    editor_key = common.table_key("inv_editor")
    editor_key = common.table_key("inv_editor")
    rows = [(int(v), None if pd.isna(lid) else int(lid)) for v, lid in zip(view["vehicle_id"], view["listing_id"])]
    st.data_editor(
        view[COLUMNS], hide_index=True, key=editor_key, num_rows="fixed",
        height=common.table_height(len(view), row_h), row_height=row_h,
        disabled=[col for col in COLUMNS if col not in EDITABLE], column_config=column_config(view, row_h),
        on_change=_on_edit, args=(editor_key, rows))


def _open_clicked(vids: list[int]) -> None:
    """Truck name clicked: open its details pop-up."""
    click = st.session_state.get("inv_open_click")
    if click is not None and 0 <= int(click["row"]) < len(vids):
        st.session_state.pop("compare_open", None)
        st.session_state["dialog_vid"] = vids[int(click["row"])]


def _clear_selection() -> None:
    st.session_state[SELECTED] = set()
    common._bump("inv_editor")
    st.rerun()


def _selection_box(c, inv: pd.DataFrame, picks: set[int]) -> None:
    """Keep selection actions beside the results, including when the sidebar is closed."""
    chosen = inv[inv["vehicle_id"].isin(picks)]
    with st.container(border=True):
        st.markdown(f"**{len(chosen)} truck{'s' if len(chosen) != 1 else ''} selected**")
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            if st.button("⚖ Compare", type="primary", key="inv_sel_cmp",
                         disabled=not 2 <= len(chosen) <= 4, help="Select 2–4 trucks"):
                st.session_state.pop("dialog_vid", None)
                st.session_state["compare_open"] = True
            if st.button("Clear selection", key="inv_sel_clear"):
                _clear_selection()
            hidden = chosen[chosen["hidden"]]
            if not hidden.empty and st.button(f"↩ Restore {len(hidden)} hidden", key="inv_sel_restore"):
                for vid in hidden["vehicle_id"]:
                    hiding.restore_vehicle(c, int(vid))
                _clear_selection()
        with st.popover("🚫 Hide selected…"):
            reason = st.selectbox("Not interested because", list(hiding.HIDE_REASONS), format_func=hiding.reason_label,
                                  key="inv_sel_reason")
            if st.button(f"🚫 Hide {'these' if len(chosen) != 1 else 'it'}", width="stretch", key="inv_sel_hide",
                     help="Hides them everywhere; 'Title issues' also records the title as branded. Undo: 🚫 Hidden "
                          "toggle."):
                for vid in chosen["vehicle_id"]:
                    hiding.hide_vehicle(c, int(vid), reason, "Hidden from Inventory selection")
                common.flash(f"Hid {len(chosen)} truck(s): {hiding.reason_label(reason)}. Toggle 🚫 Hidden to see or "
                             "restore them.", "info")
                _clear_selection()


def _on_edit(editor_key: str, rows: list[tuple[int, int | None]]) -> None:
    """Save what was changed in the table before the page redraws (one redraw per edit, not two)."""
    edits = (st.session_state.get(editor_key) or {}).get("edited_rows", {})
    if edits:
        apply_edits(common.conn(), rows, edits)
        common._bump("inv_editor")


def apply_edits(c, rows: list[tuple[int, int | None]], edits: dict) -> None:
    """rows[i] = (vehicle_id, listing_id) of display row i; edits = data_editor's edited_rows."""
    picks = set(st.session_state.get(SELECTED, set()))
    note = "Edited in Inventory"
    for idx, change in edits.items():
        vid, lid = rows[int(idx)]
        for col, value in change.items():
            if col == "pick":
                (picks.add if value else picks.discard)(vid)
            elif col == "motor_edit":
                attributes.set_override(c, vid, "motor", None if value in ("Uncertain", "Unknown", "", None) else value, note)
            elif col == "transport_edit" and lid is not None:
                with c:
                    c.execute("UPDATE listings SET transport_cost=? WHERE id=?",
                              (None if value in (None, "") else int(float(value)), lid))
            elif col == "notes":
                with c:
                    c.execute("UPDATE vehicles SET notes=? WHERE id=?", (value or "", vid))
    st.session_state[SELECTED] = picks
