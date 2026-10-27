"""Sources: automatic connectors, saved searches, email alerts, assisted capture, manual/CSV import, review."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .. import cloud, config, dedup, pipeline, queries, services
from ..db import utcnow
from ..extract import extract_attributes, parse_location
from ..importers import capture, email_alerts, manual
from ..models import NormalizedListing
from . import add_truck, common, mailbox_panel
from .forms import SITE_CHOICES, SITE_NAMES, listing_review_form

COVERAGE_NOTES = {
    "rivian": "Assisted/manual. Open Rivian's pre-owned R1 Shop; copy listing details (options list shows the tonneau).",
    "carmax": "Email alerts + assisted/manual. May also appear via MarketCheck.",
    "carvana": "Email alerts + assisted/manual. May also appear via MarketCheck.",
    "autotrader": "Email alerts + assisted/manual. Dealer stock often also appears via Auto.dev/MarketCheck.",
    "autotempest": "Meta-search: open results, then capture the original listing page.",
    "ksl": "Email alerts + assisted/manual (KSL is Utah's biggest private-party market). "
           "Private sellers and title types such as Rebuilt/Reconstructed are picked up from the ad text.",
    "rivianforums": "Watched-forum emails + paste (owner listings; only the first post is read). "
                    "Its terms forbid automated access, so the app never visits the forum.",
    "roamer": "Browse only. Roamer's terms forbid feeding its data into other apps, so its pages can't be "
              "pasted or captured. Add the truck from its rivian.com listing instead.",
    "facebook": "Manual only. Meta prohibits automated collection; type or paste details yourself.",
    "cars_com": "Email alerts + assisted/manual.",
    "cargurus": "Email alerts + assisted/manual.",
    "truecar": "Assisted/manual.",
}


def _save(listings: list[NormalizedListing], trigger: str) -> dict | None:
    return add_truck.save_listings(listings, trigger)


def render() -> None:
    c = common.conn()
    s = common.settings()
    st.title("Sources")
    tabs = st.tabs(["Automatic connectors", "Saved searches", "Email alerts", "Assisted capture", "Manual entry",
                    "CSV / JSON import", "Review duplicates", "Diagnostics", "Tools"],
                   default=st.session_state.pop("sources_section", None))

    with tabs[8]:
        common.tools_panel()

    # ------------------------------------------------------------ automatic
    with tabs[0]:
        available = services.available_sources(c)
        st.write("Connect a listing provider, choose your makes and models, then refresh the brands you want. Cars, SUVs, vans, and trucks use the same search workflow.")
        with st.expander("Connect a provider and run your first search", expanded=not any(
                src["configured"] for src in available if src["key"] in services.API_SOURCES)):
            st.markdown("1. Get an API Key using the provider instructions below; either provider is enough.\n"
                        "2. Save the key in **Settings → API credentials**. Check that the provider is enabled here.\n"
                        "3. Save one **Make | Model** per line in **Settings → Collection scope** and enter your home ZIP under **Location** for radius searches.\n"
                        "4. Choose **Refresh listings**, select several brands or **All brands**, then **Start search**. Inventory filters only change saved results.")
            with st.container(horizontal=True, gap="small"):
                for section, label in (("API credentials", "Set up API keys"), ("Collection scope", "Choose makes & models")):
                    if st.button(label, key="sources_setup_" + section):
                        st.session_state["settings_section"] = section
                        st.switch_page(st.session_state["_pages"]["settings"])
            st.caption("Without an API account, use Manual entry, CSV / JSON import, or the offline demo. A failed or incomplete refresh never marks unseen listings missing.")
        for src in available:
            with st.container(border=True):
                a, b, d = st.columns([3, 1, 1])
                status = ("key configured" if src["configured"] else "API key missing") if src["key"] in services.API_SOURCES else "ready"
                a.markdown(f"**{src['name']}** — {status}")
                if not src["configured"]:
                    a.caption(src["reason"])
                if src["key"] in services.API_SOURCES:
                    a.caption(f"App requests this month: {queries.api_calls_this_month(c, src['key'])} of {services.API_CAPS[src['key']]:,} local safety budget. Provider account limits also apply.")
                    a.caption("Key presence is checked here. Your first refresh verifies provider access.")
                    with a.expander("How to get an API Key"):
                        common.api_key_help(src["key"])
                enabled = b.toggle("Enabled", src["enabled"], key=f"en_{src['key']}")
                if enabled != src["enabled"]:
                    with c:
                        c.execute("UPDATE sources SET enabled=? WHERE key=?", (int(enabled), src["key"]))
                    st.rerun()
                if d.button("Run now", key=f"run_{src['key']}", disabled=not src["configured"]):
                    common.search_dialog([src["key"]])
        if st.button("Refresh listings", type="primary"):
            common.search_dialog()
        with st.expander("Photos"):
            st.write("One photo per vehicle is saved as a small thumbnail during each refresh (from the image link "
                     "the provider supplies). Use this to fetch any that are missing now.")
            if st.button("Fetch missing photos"):
                from .. import photos
                with st.spinner("Downloading thumbnails…"):
                    st.write(photos.cache_missing(c))
        with st.expander("Check 'missing' Auto.dev listings (uses API calls)"):
            st.write("For listings not seen in the latest scan, ask Auto.dev whether the VIN was delisted. "
                     "Confirmed removals become 'removed'; anything else stays 'missing'.")
            n = st.number_input("Max VINs to check", 1, 50, 10)
            if st.button("Check now"):
                st.write(services.verify_missing_with_autodev(c, int(n)))

    # ------------------------------------------------------------ saved searches
    with tabs[1]:
        st.write("Open a search in **your own browser**. You handle sign-in, filters and any challenges. "
                 "Then bring listings back with email alerts, assisted capture or manual entry.")
        for r in c.execute("SELECT * FROM saved_searches ORDER BY id").fetchall():
            with st.container(border=True):
                a, b = st.columns([4, 1])
                a.markdown(f"**{r['name']}**" + (" · _template_" if r["is_template"] else "")
                           + f"  \n<small>{r['notes']}</small>", unsafe_allow_html=True)
                note = COVERAGE_NOTES.get(r["source_key"])
                if note:
                    a.caption(note)
                b.link_button("Open ↗", r["url"], width="stretch")
                with a.expander("Edit"):
                    with st.form(f"ss_{r['id']}"):
                        name = st.text_input("Name", r["name"])
                        url = st.text_input("URL", r["url"])
                        notes = st.text_input("Notes", r["notes"])
                        x1, x2 = st.columns(2)
                        if x1.form_submit_button("Save"):
                            with c:
                                c.execute("UPDATE saved_searches SET name=?, url=?, notes=?, is_template=0 WHERE id=?",
                                          (name, url, notes, r["id"]))
                            st.rerun()
                        if x2.form_submit_button("Delete"):
                            with c:
                                c.execute("DELETE FROM saved_searches WHERE id=?", (r["id"],))
                            st.rerun()
        with st.form("ss_new"):
            st.markdown("**Add a saved search**")
            x1, x2, x3 = st.columns([2, 1, 3])
            name = x1.text_input("Name")
            site = x2.selectbox("Site", SITE_CHOICES, format_func=lambda k: SITE_NAMES.get(k, k))
            url = x3.text_input("URL")
            if st.form_submit_button("Add") and name and url.startswith("http"):
                with c:
                    c.execute("INSERT INTO saved_searches(name, source_key, url, notes, created_at) VALUES (?,?,?,?,?)",
                              (name, site, url, "", utcnow()))
                st.rerun()

    # ------------------------------------------------------------ email alerts
    with tabs[2]:
        mailbox_panel.render()
        add_truck.email_block("src")

    # ------------------------------------------------------------ assisted capture
    with tabs[3]:
        st.markdown(
            "**Assisted capture** = you open the listing in your normal browser, *you* select or copy the details, "
            "and the app parses only that text for your review. It never navigates, paginates, or fetches pages.  \n"
            "This is different from **browser automation** (not used) and **manual entry** (typing it yourself).")
        srv = None if cloud.is_cloud() else common.capture_server()
        sub = st.tabs(["Paste from a listing", "Browser extension queue"])
        with sub[0]:
            add_truck.paste_block("src")
        with sub[1]:
            if cloud.is_cloud():
                st.info("The browser extension sends captures only to an app running on your own computer. "
                        "For this hosted app, use Copy for pasting in the extension, then Paste from a listing. "
                        "Any saved captures below can still be reviewed.")
            elif srv:
                st.success(f"Receiver running on http://{config.CAPTURE_HOST}:{srv.port} (local only).")
            else:
                st.warning(f"Capture receiver could not start on port {config.CAPTURE_PORT} (in use?). "
                           "Set RIVIAN_FINDER_CAPTURE_PORT in .env, or use paste instead.")
            with st.expander("Install the browser extension (Chrome / Edge / Brave)", expanded=False):
                if cloud.is_cloud():
                    st.write("Install the extension from your local project folder if you want its Copy for pasting "
                             "button. Send selection requires a local app; it cannot send to the hosted URL.")
                else:
                    st.markdown(
                        f"1. Open `chrome://extensions` and switch on **Developer mode**.\n"
                        f"2. Click **Load unpacked** and choose the folder `{config.PROJECT_ROOT / 'extension'}`.\n"
                        "3. On a listing page, **highlight the details you want** (price, mileage, VIN, options), "
                        "click the extension icon, then **Send selection**.\n\n"
                        "Permissions: `activeTab` + `scripting` (only after you click), and access to "
                        "`127.0.0.1:8765` to deliver the capture. Nothing else, no background activity. "
                        "It refuses to run on Facebook.")
            queue = capture.pending(c)
            if not queue:
                st.write("No pending captures.")
            for item in queue:
                with st.container(border=True):
                    st.markdown(f"**{item['title'] or item['url'] or 'Capture'}**  \n<small>{item['url']} · "
                                f"{common.local_time(item['received_at'])}</small>", unsafe_allow_html=True)
                    draft = capture.draft_from_text(item["text"] or "", item["url"] or None, item["title"] or None,
                                                    item["image_url"])
                    add_truck.draft_notes(draft)
                    nl = listing_review_form(draft, f"capq_{item['id']}", "capture", show_claims=True)
                    if nl:
                        summary = add_truck.save_draft(nl, draft, "capture")
                        if summary:
                            capture.resolve_capture(c, item["id"], "saved", summary["listing_ids"][0])
                            st.rerun()
                    if st.button("Discard", key=f"capdel_{item['id']}"):
                        capture.resolve_capture(c, item["id"], "discarded")
                        st.rerun()

    # ------------------------------------------------------------ manual
    with tabs[4]:
        add_truck.manual_block("src")

    # ------------------------------------------------------------ csv/json
    with tabs[5]:
        st.download_button("Download CSV template", manual.csv_template(), "rivian_listings_template.csv", "text/csv")
        up = st.file_uploader("CSV or JSON file", type=["csv", "json"], key="csv_upload")
        if up is not None:
            try:
                items = manual.parse_json(up.getvalue()) if up.name.lower().endswith(".json") else manual.parse_csv(up.getvalue())
            except Exception as e:
                st.error(f"Could not read file: {e}")
                items = []
            if items:
                st.dataframe(pd.DataFrame([{"site": i.source_key, "year": i.year, "price": i.price, "miles": i.miles,
                                            "vin": i.vin, "seller": i.seller_name, "url": i.url,
                                            "claims": ", ".join(f"{a.field}={a.value}" for a in i.attributes)}
                                           for i in items]), hide_index=True)
                if st.button(f"Import {len(items)} listing(s)", type="primary"):
                    _save(items, "csv_import")

    # ------------------------------------------------------------ duplicates
    with tabs[6]:
        st.write("Listings without a shared VIN that look like the same truck. Nothing is merged without you.")
        cands = c.execute("SELECT * FROM match_candidates WHERE status='pending' ORDER BY score DESC").fetchall()
        if not cands:
            st.write("No possible duplicates waiting.")
        inv = common.inventory(s) if cands else pd.DataFrame()
        for cand in cands:
            a_row = inv[inv["vehicle_id"] == cand["vehicle_id"]]
            b_row = inv[inv["vehicle_id"] == cand["candidate_vehicle_id"]]
            if a_row.empty or b_row.empty:
                continue
            with st.container(border=True):
                st.markdown(f"**Score {cand['score']:.1f}** — {cand['reasons']}")
                cols = ["year", "trim", "price", "miles", "color", "seller", "location", "vin", "sources", "url"]
                st.dataframe(pd.concat([a_row[cols], b_row[cols]]), hide_index=True,
                             column_config={"url": st.column_config.LinkColumn("Listing"),
                                            "price": st.column_config.NumberColumn(format="dollar", step=1)})
                x1, x2 = st.columns(2)
                if x1.button("Same truck — merge", key=f"m_{cand['id']}"):
                    keep_first = bool(a_row.iloc[0]["vin"]) or not bool(b_row.iloc[0]["vin"])
                    keep, gone = ((cand["vehicle_id"], cand["candidate_vehicle_id"]) if keep_first
                                  else (cand["candidate_vehicle_id"], cand["vehicle_id"]))
                    dedup.merge_vehicles(c, keep, gone)
                    st.rerun()
                if x2.button("Different vehicles", key=f"r_{cand['id']}"):
                    dedup.reject_candidate(c, cand["id"])
                    st.rerun()

    # ------------------------------------------------------------ diagnostics
    with tabs[7]:
        st.markdown(f"**Host OS:** {config.HOST_OS} · **Database:** `{config.DB_PATH}` · "
                    f"**Logs:** `{config.LOG_DIR}`")
        ss = queries.source_status(c)
        st.dataframe(ss, hide_index=True)
        st.subheader("Recent runs")
        for run in queries.latest_runs(c, 15):
            summ = run["summary"]
            with st.expander(f"#{run['id']} · {run['trigger']} · {run['status']} · {common.local_time(run['started_at'])}"):
                if summ.get("sources"):
                    st.dataframe(pd.DataFrame(summ["sources"]), hide_index=True)
                counts = {k: v for k, v in (summ.get("counts") or {}).items() if v}
                if counts:
                    st.write(counts)
                if summ.get("enrichment"):
                    st.caption(f"VIN enrichment: {json.dumps(summ['enrichment'])}")
