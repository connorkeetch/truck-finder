"""Truck Finder — local vehicle inventory tracker. Run with: streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="Truck Finder", page_icon="🛻", layout="wide")

from rivian_finder.ui import (common, compare_page, dashboard, finance_page, inventory,  # noqa: E402
                             settings_page, shortlist, sources, vehicle)

common.boot()
common.remote_gate()
pages = {
    "inventory": st.Page(inventory.render, title="Inventory", icon="🛻", url_path="inventory", default=True),
    "shortlist": st.Page(shortlist.render, title="My shortlist", icon="⭐", url_path="shortlist"),
    "dashboard": st.Page(dashboard.render, title="Dashboard", icon="📈", url_path="dashboard"),
    "vehicle": st.Page(vehicle.render, title="Vehicle details", icon="🔎", url_path="vehicle"),
    "compare": st.Page(compare_page.render, title="Compare", icon="⚖️", url_path="compare"),
    "sources": st.Page(sources.render, title="Sources", icon="🔌", url_path="sources"),
    "finance": st.Page(finance_page.render, title="Financing", icon="💵", url_path="financing"),
    "settings": st.Page(settings_page.render, title="Settings", icon="⚙️", url_path="settings"),
}
st.session_state["_pages"] = pages
nav = st.navigation({
    "": [pages["inventory"], pages["shortlist"], pages["dashboard"]],
    "More": [pages[k] for k in ("vehicle", "compare", "sources", "finance", "settings")],
})
common.sidebar()
common.show_flash()
nav.run()
