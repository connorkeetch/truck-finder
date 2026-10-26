"""Compare 2–4 trucks side by side."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import compare, db, finance, queries
from . import common

BEST_STYLE = "background-color: #12351f; color: #8fe0a2; font-weight: 600;"


def render() -> None:
    c = common.conn()
    s = common.settings()
    st.title("Compare")
    inv = common.inventory(s)
    if inv.empty:
        st.info("No vehicles yet.")
        return
    visible = queries.apply_filters(inv, dict(s["filters"], include_missing=True))
    wanted = [v for v in st.session_state.get("compare_ids", []) if v in set(inv["vehicle_id"])]
    if not wanted:
        favs = visible[visible["favorite"]]["vehicle_id"].tolist()
        wanted = favs[:4] if len(favs) >= 2 else visible["vehicle_id"].head(3).tolist()
    pool = inv[inv["vehicle_id"].isin(set(visible["vehicle_id"]) | set(wanted))]
    labels = {int(r["vehicle_id"]): common.vehicle_label(r) for _, r in pool.iterrows()}
    chosen = st.multiselect("Trucks to compare (up to 4)", list(labels), default=wanted, max_selections=4,
                            format_func=lambda i: labels[i], key="compare_select",
                            help="Defaults to your favorites. In Inventory, tick 2–4 rows and press ⚖ Compare.")
    st.session_state["compare_ids"] = chosen
    if len(chosen) < 2:
        st.write("Pick at least two trucks.")
        return
    render_compare(inv, chosen)


def render_compare(inv, chosen: list[int], on_details=None) -> None:
    """Side-by-side table for the chosen trucks (used by this page and the Inventory pop-up).
    `on_details(vehicle_id)` replaces the default 'go to Vehicle details page' for the Details buttons."""
    trucks = inv.set_index("vehicle_id").loc[chosen].reset_index()
    compact = st.toggle("Compact comparison", False, key="compare_compact",
                         help="A shorter comparison for phone screens. Turn off for every field and full-size photos.")
    essentials = {"My requirements", "Personal score", "Price", "Est. monthly", "Mileage", "EPA range", "Tow capacity",
                  "Tow confidence", "Warranty left", "Title", "Accidents", "Distance from home", "Total acquisition cost"}
    table, best = compare.build(trucks, rows=[row for row in compare.ROWS if row[0] in essentials] if compact else None)

    cols = st.columns(len(chosen))
    for col, name, (_, t) in zip(cols, table.columns, trucks.iterrows()):
        with col.container(border=True):
            src = common.photo_image(t["vehicle_id"], t["photo_url"])
            if src and not compact:
                st.image(src, width="stretch")
            st.markdown(f"**{name}**" + ("  \n<span class='rf-badge rf-demo'>DEMO</span>" if t["is_demo"] else ""),
                        unsafe_allow_html=True)
            if t["seller_url"]:
                st.link_button("Seller's listing ↗", t["seller_url"], width="stretch")
            elif t["find_seller_url"]:
                st.link_button("Find seller ↗", t["find_seller_url"], width="stretch")
            if t["history_report_url"]:
                st.link_button("Carfax ↗", t["history_report_url"], width="stretch")
            if st.button("Details", key=f"cmp_open_{t['vehicle_id']}", width="stretch"):
                (on_details or common.open_vehicle)(int(t["vehicle_id"]))

    styles = best.map(lambda b: BEST_STYLE if b else "")
    st.dataframe(table.style.apply(lambda _: styles, axis=None), height=35 * (len(table) + 1) + 3,
                 column_config={"_index": st.column_config.TextColumn("", width="medium")})
    st.caption("Green = best among these trucks for that row (lowest price/miles/cost/distance/recalls; highest "
               "battery, warranty, range, tow capacity; confirmed tonneau, clean title, no accidents). Unknown values are never "
               "highlighted.")
    if compact:
        with st.expander("Payment scenarios"):
            payments_section(trucks)
    else:
        payments_section(trucks)


def _signed(v: float) -> str:
    return f"−${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def payments_section(trucks: pd.DataFrame) -> None:
    """💵 Payments: each truck's monthly payment depending on what your current truck sells for — plus the selling
    dealer's trade-in offer when you have one (it also lowers the sales tax). Inputs are remembered."""
    c, s = common.conn(), common.settings()
    fa = finance.FinanceAssumptions.from_settings(s["finance"])
    saved = {**finance.PAYMENT_TABLE_DEFAULTS, **db.get_pref(c, "payment_table", {})}
    aprs = (list(saved["aprs"]) + [5.0, 5.0])[:2]
    # widgets start from what you saved (only when they aren't on screen already, so edits aren't overwritten)
    for key, value in {"pt_sale_from": float(saved["sale_from"]), "pt_sale_to": float(saved["sale_to"]),
                       "pt_sale_step": float(saved["sale_step"]), "pt_apr_a": float(aprs[0]),
                       "pt_apr_b": float(aprs[1]), "pt_term": int(saved["term"])}.items():
        st.session_state.setdefault(key, value)
    if "pt_offers" not in st.session_state:
        st.session_state["pt_offers_base"] = pd.DataFrame(saved["trade_offers"], columns=["dealer", "amount"])
    short = next((w for w in fa.current_vehicle.split() if w.isalpha()), "Your truck")

    st.markdown("#### 💵 Payments")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.number_input(f"{short} sells for, from", 0.0, 500000.0, step=500.0, format="%.0f", key="pt_sale_from")
    c2.number_input("to", 0.0, 500000.0, step=500.0, format="%.0f", key="pt_sale_to")
    c3.number_input("step", 100.0, 100000.0, step=500.0, format="%.0f", key="pt_sale_step")
    c4.number_input("APR (%)", 0.0, 30.0, step=0.25, format="%.2f", key="pt_apr_a")
    c5.number_input("2nd APR (%)", 0.0, 30.0, step=0.25, format="%.2f", key="pt_apr_b")
    c6.number_input("Months", 12, 96, step=6, key="pt_term")
    with st.expander(f"🤝 Dealer trade-in offers for your {short}"):
        edited = st.data_editor(st.session_state["pt_offers_base"], num_rows="dynamic", hide_index=True,
                                key="pt_offers", width="stretch", column_config={
                                    "dealer": st.column_config.TextColumn("Dealer", required=True,
                                                                          help="Matched to the truck's seller name"),
                                    "amount": st.column_config.NumberColumn("Offer ($)", min_value=0, step=500,
                                                                            format="dollar")})
        st.caption(f"Adds a row to that dealer's trucks: they pay off your {_signed(fa.trade_payoff)} loan, and trading "
                   "in to the selling dealer lowers the taxable price"
                   + (" (Utah)" if fa.trade_in_reduces_taxable else " — off in Settings → Loan assumptions")
                   + "; a private sale doesn't.")
    offers = [{"dealer": str(r["dealer"]).strip(), "amount": float(r["amount"])} for r in edited.to_dict("records")
              if str(r.get("dealer") or "").strip() and pd.notna(r.get("amount")) and r.get("amount")]
    cfg = {"sale_from": st.session_state["pt_sale_from"], "sale_to": st.session_state["pt_sale_to"],
           "sale_step": st.session_state["pt_sale_step"],
           "aprs": [st.session_state["pt_apr_a"], st.session_state["pt_apr_b"]],
           "term": int(st.session_state["pt_term"]), "trade_offers": offers}
    if cfg != {k: saved[k] for k in cfg}:
        db.set_pref(c, "payment_table", cfg)

    term = cfg["term"]
    for _, t in trucks.iterrows():
        name = " · ".join(x for x in (compare.vehicle_name(t),
                                      t["sold_by"], t["location"]) if x)
        if pd.isna(t["price"]) or not t["price"]:
            st.caption(f"**{name}** — no price yet")
            continue
        offer = finance.trade_offer_for(offers, t["seller"], t["sold_by"])
        transport = float(t["transport_cost"]) if pd.notna(t["transport_cost"]) else 0.0
        rows = finance.payment_table(float(t["price"]), fa, cfg, transport, t["seller_key"], offer)
        r0 = rows[0]
        st.markdown(common.md(f"**{name}** · {common.money(r0['price'])} + {common.money(r0['sales_tax'])} tax + "
                              f"{common.money(r0['fees'])} fees"
                              + (f" + {common.money(r0['transport'])} shipping" if r0["transport"] else "")
                              + f" = **{common.money(r0['out_the_door'])}** out the door"))
        st.dataframe(pd.DataFrame([{
            f"{short} sells for": (f"🤝 Trade to {r['dealer']}: {common.money(r['credit'])}" if r["kind"] == "trade"
                                   else common.money(r["credit"])),
            "Cash left after payoff": _signed(r["cash_left"]),
            "Amount financed": common.money(r["financed"]),
            **{f"{apr:g}% APR / {term} months": f"{common.money(p)}/month" for apr, p in r["payments"].items()},
        } for r in rows]), hide_index=True, width="stretch")
        trade = next((r for r in rows if r["kind"] == "trade"), None)
        if trade:
            st.caption(common.md(f"Trading in to {trade['dealer']} saves {common.money(trade['tax_saved'])} in sales "
                                 f"tax — like selling your {short} yourself for "
                                 f"{common.money(trade['same_as_selling_for'])}."))
