"""Financing: calculator for any price plus a payment comparison across matching vehicles."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import compare, finance, queries
from . import common


def render() -> None:
    c = common.conn()
    s = common.settings()
    fa = finance.FinanceAssumptions.from_settings(s["finance"])
    st.title("Financing")
    st.caption(common.md(f"Assumptions: target ${fa.target_monthly:,.0f}/mo · tax {fa.sales_tax_rate}% · DMV ${fa.dmv_fees:,.0f} · "
               f"payoff ${fa.trade_payoff:,.0f} on the {fa.current_vehicle} · trade-in ${fa.trade_in_low:,.0f}–"
               f"${fa.trade_in_high:,.0f} · cash offer ${fa.cash_offer:,.0f}. Edit in Settings → Loan assumptions."))

    st.subheader("Calculator")
    c1, c2, c3 = st.columns(3)
    price = c1.number_input("Vehicle price ($)", 0, 300000, 60000, 500)
    transport = c2.number_input("Transport ($)", 0, 20000, int(fa.default_transport_cost), 50)
    scen = c3.selectbox("Scenario", list(finance.SCENARIO_LABELS), format_func=finance.SCENARIO_LABELS.get)
    res = finance.scenario(float(price), fa, scen, float(transport))
    m = st.columns(5)
    m[0].metric("Taxable amount", common.money(res.taxable_amount))
    m[1].metric("Sales tax", common.money(res.sales_tax))
    m[2].metric("Total acquisition cost", common.money(res.total_acquisition_cost))
    m[3].metric("Equity applied", common.money(res.equity))
    m[4].metric("Amount financed", common.money(res.amount_financed))
    grid = []
    for k, pay in res.payments.items():
        term, apr = k.split("@")
        grid.append({"Term (mo)": int(term), "APR %": float(apr), "Monthly": pay,
                     f"Cash needed for ${fa.target_monthly:,.0f}/mo": res.cash_to_target[k],
                     "Total interest": res.total_interest[k]})
    st.dataframe(pd.DataFrame(grid), hide_index=True, column_config={
        "Monthly": st.column_config.NumberColumn(format="dollar", step=0.01),
        f"Cash needed for ${fa.target_monthly:,.0f}/mo": st.column_config.NumberColumn(format="dollar", step=1),
        "Total interest": st.column_config.NumberColumn(format="dollar", step=1)})
    budget = {k: finance.max_principal(fa.target_monthly, float(k.split('@')[1]), int(k.split('@')[0])) for k in res.payments}
    st.caption("Max amount financed at your target payment: "
               + " · ".join(f"{k.replace('@', ' mo @ ')}% → {common.money(v)}" for k, v in budget.items()))

    st.subheader("Matching vehicles compared")
    inv = common.inventory(s)
    df = queries.apply_filters(inv, s["filters"]) if not inv.empty else inv
    if df.empty:
        st.write("No matching vehicles.")
        return
    c1, c2, c3 = st.columns(3)
    term = c1.selectbox("Term", fa.terms, index=fa.terms.index(fa.primary_term) if fa.primary_term in fa.terms else len(fa.terms) - 1)
    apr = c2.selectbox("APR %", fa.aprs, index=fa.aprs.index(fa.primary_apr) if fa.primary_apr in fa.aprs else len(fa.aprs) - 1)
    scen2 = c3.selectbox("Scenario ", list(finance.SCENARIO_LABELS), format_func=finance.SCENARIO_LABELS.get,
                         index=list(finance.SCENARIO_LABELS).index(fa.primary_scenario))
    rows = []
    for r in df.itertuples(index=False):
        if not r.price:
            continue
        sc = finance.scenario(float(r.price), fa, scen2, float(r.transport_cost or 0))
        k = f"{term}@{apr:g}"
        rows.append({"Vehicle": ("[DEMO] " if r.is_demo else "") + compare.vehicle_name(r._asdict()),
                     "Price": r.price, "Miles": r.miles, "Tonneau": common.TONNEAU_ICON.get(r.tonneau, ""),
                     "Battery": r.battery, "Total cost": sc.total_acquisition_cost, "Financed": sc.amount_financed,
                     "Monthly": sc.payments[k], "Cash for target": sc.cash_to_target[k],
                     "Under target": sc.payments[k] <= fa.target_monthly, "Seller": r.seller, "Listing": r.url})
    out = pd.DataFrame(rows).sort_values("Monthly")
    st.dataframe(out, hide_index=True, column_config={
        "Price": st.column_config.NumberColumn(format="dollar", step=1), "Miles": st.column_config.NumberColumn(format="%,d"),
        "Total cost": st.column_config.NumberColumn(format="dollar", step=1), "Financed": st.column_config.NumberColumn(format="dollar", step=1),
        "Monthly": st.column_config.NumberColumn(format="dollar", step=0.01),
        "Cash for target": st.column_config.NumberColumn(format="dollar", step=1),
        "Under target": st.column_config.CheckboxColumn(), "Listing": st.column_config.LinkColumn(display_text="open")})
