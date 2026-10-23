"""Settings: filters, collection scope, location, credentials, loan & warranty assumptions, export, backups."""
from __future__ import annotations

import copy
from pathlib import Path

import streamlit as st

import pandas as pd

from .. import access, alerts, backup, config, credentials, notifier, queries, scheduler, services, shipping, warranty
from ..config import US_STATES
from ..geo import zip_latlon
from ..sources.base import EV_TRUCK_PRESET, search_targets
from . import common
from .inventory import filter_controls


def parse_searches(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) != 2:
            raise ValueError("Use one Make | Model pair per line.")
        rows.append({"make": parts[0].strip(), "model": parts[1].strip()})
    return search_targets({"searches": rows})


def render() -> None:
    c = common.conn()
    s = common.settings()
    st.title("Settings")
    tabs = st.tabs(["Vehicle filters", "Collection scope", "Location", "API credentials", "Loan assumptions",
                    "Warranty", "Export", "Backup & data", "Shipping", "Alerts", "Phone access"])

    with tabs[0]:
        st.write("Default filters for the Dashboard, Inventory and Excel export. They only filter what is already "
                 "stored — changing them never re-queries any provider.")
        inv = common.inventory(s)
        try:
            targets = search_targets(s["collection"])
        except ValueError:
            targets = []
            st.warning("Repair your make/model searches in Collection scope.")
        f = filter_controls(s["filters"], key="set", trim_options=[] if inv.empty else inv["trim_filter"].unique().tolist(),
                            brand_options=[t["make"] for t in targets] + ([] if inv.empty else inv["make"].dropna().tolist()),
                            model_options=[t["model"] for t in targets] + ([] if inv.empty else inv["model"].dropna().tolist()))
        if st.button("Save filters", type="primary"):
            s["filters"] = f
            common.save_settings(s)
            st.session_state.pop("inv_filters", None)
            st.success("Saved.")

    with tabs[1]:
        st.write("What the API connectors ask providers for. Keep this **broader** than your filters so that "
                 "narrowing a filter doesn't make listings look like they disappeared. Changing it means the next "
                 "scan skips disappearance detection once.")
        col = copy.deepcopy(s["collection"])
        b1, b2 = st.columns(2)
        for box, key, name, cap in ((b1, "autodev", "Auto.dev", 1000), (b2, "marketcheck", "MarketCheck", 500)):
            b = queries.api_budget(c, key, cap)
            with box.container(border=True):
                st.markdown(f"**{name}** — {b['used']} of {b['cap']} free calls used this month")
                st.progress(min(b["used"] / b["cap"], 1.0))
                if b["per_run"]:
                    st.caption(f"Last complete run: {b['per_run']} calls ({b['last_run_listings']} listing rows). "
                                f"≈ {b['runs_left']} more full runs this month at that size.")
                else:
                    st.caption("No complete run yet.")
        st.caption("Each Auto.dev call returns 20 listings on the free plan. All selected makes/models share the connector's page and monthly call limits.")
        custom = st.checkbox("Choose makes and models", col.get("searches") is not None, key="collection_custom_searches",
                              help="Use any make/model pairs with common search limits. Turn off to keep the legacy EV truck search.")
        search_text = ""
        if custom:
            defaults = targets if col.get("searches") is not None else EV_TRUCK_PRESET
            initial = "\n".join(f"{row['make']} | {row['model']}" for row in defaults)
            st.session_state.setdefault("collection_searches_text", initial)
            if st.button("Use EV truck presets", key="collection_ev_presets"):
                st.session_state["collection_searches_text"] = "\n".join(f"{r['make']} | {r['model']}" for r in EV_TRUCK_PRESET)
            search_text = st.text_area("Makes and models (one Make | Model per line)",
                                       key="collection_searches_text", height=150,
                                       placeholder="Toyota | Tacoma\nFord | F-150\nRam | 1500")
            st.caption("These pairs define your API searches. Each model is searched separately so it stays paired with its make.")
        c1, c2, c3 = st.columns(3)
        col["year_min"], col["year_max"] = c1.slider("Years to collect", min(1900 if custom else 2022, int(col["year_min"])),
                                                      max(2027, int(col["year_max"])), (int(col["year_min"]), int(col["year_max"])))
        col["max_price"] = c2.number_input("Max price to collect", 1, 300000, int(col["max_price"]), 1000)
        col["max_miles"] = c3.number_input("Max miles to collect", 1, 300000, int(col["max_miles"]), 1000)
        if custom:
            a, b = st.columns(2)
            col["max_distance"] = a.number_input("Max search distance from home (mi, 0 = nationwide)", 0, 5000,
                                                   int(col.get("max_distance", 0)), 25, key="collection_max_distance")
            col["used_only"] = b.checkbox("Used vehicles only", col.get("used_only", True), key="collection_used_only")
            st.caption("Distance is centered on Home ZIP. The provider's plan radius can limit coverage further. Legacy competitor-only price, mileage, distance and minimum-range caps do not apply. Your display filters and optional EV truck preferences still apply.")
        c1, c2, c3 = st.columns(3)
        col["max_pages_per_run"] = c1.number_input("Max pages per connector per run", 1, 200, int(col["max_pages_per_run"]),
                                                   help="Caps API usage. Auto.dev free plan returns 20 results/page.")
        if not custom:
            col["marketcheck_zip"] = c2.text_input("MarketCheck search ZIP", col["marketcheck_zip"])
        else:
            c2.caption("MarketCheck searches use Home ZIP.")
        col["marketcheck_radius"] = c3.number_input("MarketCheck radius (mi, 0 = nationwide/paid)", 0, 5000,
                                                    int(col["marketcheck_radius"]), 25)
        col["vpic_enrichment"] = st.checkbox("Decode new VINs with NHTSA vPIC (free; adds motor configuration)",
                                             col["vpic_enrichment"])
        if not custom:
            st.markdown("**Similar EV trucks**")
            col["include_other_brands"] = st.checkbox("Also collect Ford F-150 Lightning, Chevrolet Silverado EV and GMC Sierra EV",
                                                  col.get("include_other_brands", True))
            c1, c2, c3 = st.columns(3)
            col["other_max_distance"] = c1.number_input("Other brands: max distance (mi)", 1, 5000,
                                                      int(col.get("other_max_distance", 650)), 25)
            col["other_max_miles"] = c2.number_input("Other brands: max mileage", 1, 300000,
                                                   int(col.get("other_max_miles", 45000)), 1000)
            col["other_min_range"] = c3.number_input("Other brands: minimum known EPA range (mi)", 0, 600,
                                                   int(col.get("other_min_range", 301)))
            st.caption("Other brands use your default vehicle-filter max price and Home ZIP. Defaults keep them within "
                   "650 miles, at 45,000 miles or less and above 300 miles of known range. Unknown range stays eligible "
                   "and is labeled for verification; untick Include unknown range in Vehicle filters to hide it. "
                   "Include unknown range does not override the Standard Range exclusion. "
                   "Provider-side price, mileage and radius limits reduce pages where supported; range is checked "
                   "after results arrive. All brands share each connector's page cap and monthly call budget.")
        with st.expander("EV truck preferences", expanded=not custom):
            col["exclude_standard_range"] = st.checkbox(
                "Exclude Standard Range trucks (Ford, Chevrolet, GMC)", col.get("exclude_standard_range", False),
                key="collection_exclude_standard_range",
                help="Exclude trucks explicitly labeled Standard Range in the listing title, trim or battery, "
                     "even when their numeric EPA range is unknown.")
            excluded = col.get("excluded_trims", {})
            c1, c2 = st.columns(2)
            col["excluded_trims"] = {
                **excluded,
                "Ford": c1.multiselect("Exclude Ford Lightning trims", ["Pro", "XLT", "Flash", "Lariat", "Platinum"],
                                       excluded.get("Ford", [])),
                "Chevrolet": c2.multiselect("Exclude Chevrolet Silverado EV trims", ["WT", "LT", "RST", "Trail Boss"],
                                            excluded.get("Chevrolet", [])),
            }
            st.caption("These preferences apply only to the matching EV truck models, including in custom searches. "
                       "WT includes 2WT, 3WT, 4WT and Work Truck. Exclusions hide stored matches and skip new matching results; "
                       "nothing is deleted. Clear an exclusion to include that trim again.")
        if st.button("Save collection scope", type="primary"):
            try:
                col["searches"] = parse_searches(search_text) if custom else None
            except ValueError as exc:
                st.error(str(exc))
            else:
                s["collection"] = col
                common.save_settings(s)
                st.success("Saved.")

    with tabs[2]:
        c1, c2 = st.columns([1, 3])
        home = c1.text_input("Home ZIP", s["home_zip"])
        if home and not zip_latlon(home):
            c1.error("Unknown ZIP")
        pri = c2.multiselect("Priority states (ranked higher)", US_STATES, s["priority_states"])
        if st.button("Save location", type="primary"):
            s["home_zip"], s["priority_states"] = home.strip(), pri
            common.save_settings(s)
            st.success("Saved.")

    with tabs[3]:
        st.write("Keys are read from environment variables / `.env` first, then from your OS credential store "
                 "(Windows Credential Manager, macOS Keychain, or Secret Service). They are never written to the "
                 "database, exports or logs.")
        info = {
            "autodev": ("Auto.dev", "https://auto.dev/pricing", "Free plan: 1,000 calls/month, no card. Create a key at auto.dev/dashboard/api-keys."),
            "marketcheck": ("MarketCheck", "https://www.marketcheck.com/apis/pricing", "Free plan: 500 calls/month, 100-mile radius."),
        }
        for key, (name, link, note) in info.items():
            with st.container(border=True):
                val, where = credentials.get_api_key(key)
                st.markdown(f"**{name}** — " + (f"configured via **{where}** ({credentials.mask(val)})" if val else "not configured"))
                st.caption(f"{note} [{link}]({link})")
                with st.form(f"key_{key}"):
                    new = st.text_input(f"{name} API key", type="password", key=f"k_{key}")
                    a, b = st.columns(2)
                    if a.form_submit_button("Save to OS credential store") and new.strip():
                        try:
                            credentials.save_api_key(key, new)
                            st.success("Saved securely.")
                        except Exception as e:
                            st.error(f"{e}")
                    if b.form_submit_button("Remove from credential store"):
                        credentials.delete_api_key(key)
                        st.success("Removed (environment variables, if any, still apply).")

    with tabs[4]:
        fin = s["finance"]
        st.write("Every number in the financing estimates comes from here. Payments use standard fixed-rate "
                 "amortization: P × r / (1 − (1 + r)^−n), r = APR/12.")
        c1, c2, c3 = st.columns(3)
        fin["target_monthly"] = c1.number_input("Target monthly payment ($)", 0.0, 10000.0, float(fin["target_monthly"]), 25.0)
        terms = c2.text_input("Loan terms (months, comma-separated)", ", ".join(map(str, fin["terms"])))
        aprs = c3.text_input("APR scenarios (%, comma-separated)", ", ".join(map(str, fin["aprs"])))
        c1, c2, c3 = st.columns(3)
        fin["current_vehicle"] = c1.text_input("Current vehicle", fin["current_vehicle"])
        fin["trade_payoff"] = c2.number_input("Current loan payoff ($)", 0.0, 200000.0, float(fin["trade_payoff"]), 100.0)
        fin["cash_offer"] = c3.number_input("Separate cash offer ($)", 0.0, 200000.0, float(fin["cash_offer"]), 100.0)
        c1, c2, c3 = st.columns(3)
        fin["trade_in_low"] = c1.number_input("Trade-in estimate, low ($)", 0.0, 200000.0, float(fin["trade_in_low"]), 100.0)
        fin["trade_in_high"] = c2.number_input("Trade-in estimate, high ($)", 0.0, 200000.0, float(fin["trade_in_high"]), 100.0)
        fin["extra_cash_down"] = c3.number_input("Extra cash down ($)", 0.0, 200000.0, float(fin["extra_cash_down"]), 100.0)
        c1, c2, c3, c4 = st.columns(4)
        fin["sales_tax_rate"] = c1.number_input("Sales tax rate (%)", 0.0, 15.0, float(fin["sales_tax_rate"]), 0.05, format="%.2f")
        fin["dmv_fees"] = c2.number_input("DMV / registration ($)", 0.0, 5000.0, float(fin["dmv_fees"]), 25.0)
        fin["doc_fee"] = c3.number_input("Dealer doc fee ($)", 0.0, 5000.0, float(fin["doc_fee"]), 25.0)
        fin["default_transport_cost"] = c4.number_input("Default transport ($)", 0.0, 20000.0,
                                                        float(fin["default_transport_cost"]), 50.0,
                                                        help="Used unless you set one per listing on Vehicle details")
        st.markdown("**Sales-tax treatment** (check with the Utah DMV / Tax Commission for your situation)")
        fin["trade_in_reduces_taxable"] = st.checkbox(
            "Trading in to the selling dealer reduces the taxable price", fin["trade_in_reduces_taxable"])
        fin["cash_sale_reduces_taxable"] = st.checkbox(
            "Selling my current vehicle separately reduces the taxable price (normally NO)", fin["cash_sale_reduces_taxable"])
        c1, c2, c3 = st.columns(3)
        scen = ["cash_sale", "trade_low", "trade_high"]
        fin["primary_scenario"] = c1.selectbox("Scenario shown in tables", scen, index=scen.index(fin["primary_scenario"]),
                                               format_func=lambda k: {"cash_sale": "Sell separately (cash offer)",
                                                                      "trade_low": "Dealer trade-in (low)",
                                                                      "trade_high": "Dealer trade-in (high)"}[k])
        fin["primary_term"] = c2.number_input("Term shown in tables (months)", 12, 96, int(fin["primary_term"]), 6)
        fin["primary_apr"] = c3.number_input("APR shown in tables (%)", 0.0, 30.0, float(fin["primary_apr"]), 0.05, format="%.2f")
        st.markdown("**Seller discounts** (e.g. Carvana takes $1,000 off when you trade in)")
        disc = pd.DataFrame(fin.get("discounts") or [], columns=["seller", "amount", "when"])
        disc = st.data_editor(disc, num_rows="dynamic", hide_index=True, key="disc_editor", column_config={
            "seller": st.column_config.SelectboxColumn("Seller", options=["carvana", "carmax", "vroom", "any"],
                                                       required=True),
            "amount": st.column_config.NumberColumn("Discount ($)", min_value=0, step=100, format="dollar"),
            "when": st.column_config.SelectboxColumn("Applies", options=["trade", "always"], required=True,
                                                     help="trade = only when you trade in to that seller")})
        if st.button("Save loan assumptions", type="primary"):
            fin["discounts"] = [{"seller": r["seller"], "amount": float(r["amount"] or 0), "when": r["when"] or "always"}
                                for _, r in disc.iterrows() if r["seller"] and (r["amount"] or 0) > 0]
            try:
                fin["terms"] = [int(x) for x in terms.replace(" ", "").split(",") if x]
                fin["aprs"] = [float(x) for x in aprs.replace(" ", "").split(",") if x]
            except ValueError:
                st.error("Terms and APRs must be comma-separated numbers.")
            else:
                s["finance"] = fin
                common.save_settings(s)
                st.success("Saved.")

    with tabs[5]:
        w = {**warranty.DEFAULT_TERMS, **s["warranty"]}
        st.write("Rivian terms only: used when an R1T has an in-service date but no warranty dates of its own. A truck's actual "
                 "warranty dates (pasted on its page) always win.")
        c1, c2 = st.columns(2)
        w["comprehensive_years"] = c1.number_input("Comprehensive: years (usual)", 1, 15, int(w["comprehensive_years"]))
        w["comprehensive_miles"] = c2.number_input("Comprehensive: miles (usual)", 1000, 500000, int(w["comprehensive_miles"]), 1000)
        c1, c2, c3 = st.columns(3)
        w["longer_motors"] = c1.multiselect("Motors with longer comprehensive coverage", ["Quad", "Tri", "Performance Dual", "Dual"],
                                            w["longer_motors"])
        w["longer_years"] = c2.number_input("…years", 1, 15, int(w["longer_years"]))
        w["longer_miles"] = c3.number_input("…miles", 1000, 500000, int(w["longer_miles"]), 1000)
        c1, c2, c3 = st.columns(3)
        w["battery_years"] = c1.number_input("Battery & drivetrain: years", 1, 15, int(w["battery_years"]))
        w["battery_miles_large_max"] = c2.number_input("Battery miles (Large/Max)", 1000, 500000, int(w["battery_miles_large_max"]), 1000)
        w["battery_miles_standard"] = c3.number_input("Battery miles (Standard)", 1000, 500000, int(w["battery_miles_standard"]), 1000)
        if st.button("Save warranty terms", type="primary"):
            s["warranty"] = w
            common.save_settings(s)
            st.success("Saved.")

    with tabs[6]:
        e = s["export"]
        e["new_listing_window_days"] = st.number_input("'New Listings' sheet covers the last N days", 1, 90,
                                                       int(e["new_listing_window_days"]))
        e["include_filtered_out"] = st.checkbox("Current Inventory sheet includes vehicles outside my filters",
                                                e["include_filtered_out"])
        e["export_dir"] = st.text_input("Also save exports to folder (blank = data/exports)", e.get("export_dir", ""))
        if st.button("Save export settings", type="primary"):
            if e["export_dir"] and not Path(e["export_dir"]).exists():
                st.error("That folder does not exist.")
            else:
                s["export"] = e
                common.save_settings(s)
                st.success("Saved.")

    with tabs[7]:
        st.markdown(f"Database: `{config.DB_PATH}` · Backups: `{config.BACKUP_DIR}` (one automatic backup per day "
                    "before the first search; last 30 kept)")
        c1, c2 = st.columns(2)
        if c1.button("Back up now"):
            st.success(f"Backup written: {backup.backup_db(c)}")
        c2.download_button("Download full JSON export", backup.export_json(c), "rivian_finder_export.json",
                           "application/json")
        backups = backup.list_backups()
        if backups:
            choice = st.selectbox("Restore from backup", backups, format_func=lambda p: p.name)
            if st.button("Restore selected backup", help="Your current database is backed up first"):
                common.reset_connection()
                backup.restore_db(choice)
                st.success("Restored. Reloading…")
                st.rerun()
        st.divider()
        demo = c.execute("SELECT COUNT(*) FROM vehicles WHERE is_demo=1").fetchone()[0]
        st.markdown(f"**Demo data:** {demo} synthetic vehicles stored.")
        c1, c2 = st.columns(2)
        if c1.button("Purge all demo data", disabled=not demo):
            n = services.purge_demo(c)
            st.success(f"Removed {n} demo vehicles.")
        demo_on = services.source_enabled(c, "demo")
        if c2.toggle("Include demo connector in Run Search", demo_on) != demo_on:
            with c:
                c.execute("UPDATE sources SET enabled=? WHERE key='demo'", (int(not demo_on),))
            st.rerun()

    with tabs[8]:
        shipping_settings(s)
    with tabs[9]:
        alert_settings(c, s)
    with tabs[10]:
        phone_settings()


def shipping_settings(s: dict) -> None:
    sh = {**shipping.DEFAULTS, **(s.get("shipping") or {})}
    st.write("How the app estimates getting each truck home. Amounts you type on a truck's *Listings & sources* tab "
             "always win. Estimates only — get a real quote before buying.")
    sh["fee_sellers"] = st.multiselect(
        "Sellers that charge their own delivery fee", list(shipping.INCLUDED_SELLERS), sh["fee_sellers"],
        format_func=shipping.INCLUDED_SELLERS.get,
        help="Carvana and CarMax show the exact fee on the listing — type it on the truck to replace the estimate.")
    f1, f2, f3 = st.columns(3)
    sh["fee_near"] = f1.number_input("Their fee from a nearby hub ($)", 0.0, 5000.0, float(sh["fee_near"]), 10.0)
    sh["fee_near_mi"] = f2.number_input("…when within (mi)", 0, 3000, int(sh["fee_near_mi"]), 25)
    sh["fee_far"] = f3.number_input("Their fee otherwise ($)", 0.0, 5000.0, float(sh["fee_far"]), 10.0)
    sh["included_sellers"] = st.multiselect(
        "Sellers that deliver as part of the price ($0 shipping)", list(shipping.INCLUDED_SELLERS),
        [k for k in sh["included_sellers"] if k not in sh["fee_sellers"]], format_func=shipping.INCLUDED_SELLERS.get)
    c1, c2, c3 = st.columns(3)
    sh["local_radius_mi"] = c1.number_input("Local pickup radius (mi)", 0, 2000, int(sh["local_radius_mi"]), 25,
                                            help="Within this straight-line distance you'd drive to get it: $0")
    sh["base"] = c2.number_input("Shipping base fee ($)", 0.0, 5000.0, float(sh["base"]), 50.0)
    sh["per_mile"] = c3.number_input("Per road mile ($)", 0.0, 5.0, float(sh["per_mile"]), 0.05, format="%.2f")
    c1, c2, _ = st.columns(3)
    sh["road_factor"] = c1.number_input("Road miles ÷ straight-line", 1.0, 2.0, float(sh["road_factor"]), 0.05,
                                        format="%.2f")
    sh["minimum"] = c2.number_input("Minimum shipped cost ($)", 0.0, 5000.0, float(sh["minimum"]), 50.0)
    example = {"source_key": "dealer", "url": "https://dealer.example"}
    st.caption(common.md("Examples with these settings (dealer, not included): " + " · ".join(
        f"{d} mi → ${shipping.estimate(example, d, sh)[0]:,.0f}" for d in (100, 400, 800, 1500))))
    if st.button("Save shipping settings", type="primary"):
        s["shipping"] = sh
        common.save_settings(s)
        st.success("Saved.")


def alert_settings(c, s: dict) -> None:
    a = {**alerts.DEFAULTS, **(s.get("alerts") or {})}
    st.write("Optional: search on a schedule and get a desktop notification. Off until you turn it on. The search "
             "runs in the background while you're logged in; this window doesn't need to be open.")
    c1, c2, c3 = st.columns(3)
    a["new_matches"] = c1.checkbox("New trucks matching my filters", a["new_matches"])
    a["favorite_drops"] = c2.checkbox("Price drops on my favorites", a["favorite_drops"])
    a["great_deals"] = c3.checkbox("Point out great/good deals", a["great_deals"])
    c1, c2, c3 = st.columns(3)
    a["min_drop"] = c1.number_input("Only drops of at least ($)", 0, 20000, int(a["min_drop"] or 0), 250)
    times = c2.text_input("Times (24h HH:MM, comma-separated)", ", ".join(a["times"]))
    a["notify_when_nothing"] = c3.checkbox("Notify even when nothing changed", a["notify_when_nothing"])
    try:
        parsed = [t.strip() for t in times.split(",") if t.strip()]
        scheduler.create_commands(parsed)          # validates HH:MM
    except ValueError as e:
        st.error(str(e))
        parsed = a["times"]
    b = queries.api_budget(c, "autodev", services.API_CAPS["autodev"])
    if b["per_run"]:
        monthly = b["per_run"] * len(parsed) * 30
        msg = (f"Budget: ~{b['per_run']} Auto.dev calls per run × {len(parsed)}/day ≈ {monthly:,} per month "
               f"(free plan: 1,000). Runs are skipped automatically when the month's calls run low.")
        (st.warning if monthly > 1000 else st.caption)(msg)
    if st.button("Save alert settings", type="primary"):
        a["times"] = parsed
        s["alerts"] = a
        common.save_settings(s)
        st.success("Saved.")

    st.divider()
    tasks = scheduler.installed() if scheduler.supported() else []
    if tasks:
        st.success("Scheduled search is ON: " + "; ".join(f"{t['name'].split(chr(92))[-1]} (next {t['next_run']})"
                                                          for t in tasks))
    else:
        st.info("Scheduled search is OFF.")
    x1, x2, x3 = st.columns(3)
    if x1.button("Turn on scheduled search", disabled=not scheduler.supported()):
        ok, msg = scheduler.install(parsed)
        (st.success if ok else st.error)(msg)
        if ok:
            s["alerts"] = {**a, "times": parsed, "enabled": True}
            common.save_settings(s)
        st.rerun()
    if x2.button("Turn off scheduled search", disabled=not tasks):
        ok, msg = scheduler.remove()
        s["alerts"] = {**a, "enabled": False}
        common.save_settings(s)
        st.success(msg)
        st.rerun()
    if x3.button("Send a test notification"):
        ok, detail = notifier.notify("Truck Finder", "Test notification — alerts are working.", "http://127.0.0.1:8501")
        (st.success if ok else st.error)("Sent — check your notifications." if ok else f"Couldn't send: {detail}")
    st.caption("Log of scheduled runs: data/logs/scheduled.log. Windows: Task Scheduler → Task Scheduler Library → "
               "RivianFinder.")


def phone_settings() -> None:
    acc = access.load()
    st.write("Open Truck Finder from your phone on the same Wi-Fi. Anyone on your network would need the PIN; this "
             "computer never asks for it. The browser-extension receiver stays private to this computer.")
    ips = access.lan_ips()
    if acc["lan"]:
        st.success("Phone access is ON (after a restart). On your phone open: "
                   + " or ".join(f"**http://{ip}:{access.port()}**" for ip in ips[:2]))
    else:
        st.info("Phone access is OFF — the app only answers on this computer.")
    with st.form("phone_access"):
        on = st.toggle("Allow access from my phone / other devices on my home network", acc["lan"])
        pin = st.text_input("PIN (4–12 digits)" + (" — leave blank to keep the current PIN" if acc["pin_hash"] else ""),
                            type="password")
        if st.form_submit_button("Save", type="primary"):
            try:
                access.save(on, pin or None)
                st.success("Saved. Restart the app (close its window and run run.bat) to apply. The first time, "
                           "Windows Firewall may ask — allow access on **private** networks only.")
            except ValueError as e:
                st.error(str(e))
    st.caption("Use this on your home Wi-Fi only — not on public or work networks.")
