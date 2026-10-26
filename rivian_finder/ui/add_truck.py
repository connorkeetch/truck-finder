"""Ways to add a truck, shared by the Inventory page and the Sources page."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import pipeline, queries, services
from ..extract import extract_attributes, parse_location
from ..importers import capture, email_alerts, forum_listing, rivian_page
from ..models import NormalizedListing
from ..sources.base import search_targets
from ..vin import clean_vin, validate_vin
from . import common
from .forms import listing_review_form


def save_listings(listings: list[NormalizedListing], trigger: str) -> dict | None:
    if not listings:
        st.warning("Nothing to save.")
        return None
    summary = pipeline.import_listings(common.conn(), listings, trigger)
    c = summary["counts"]
    msg = (f"Saved {len(listings)} listing(s): {c.get('new_listing', 0)} new truck(s), "
           f"{c.get('new_source_for_vin', 0)} new link(s) for trucks you already had, {c.get('price_drop', 0)} price drop(s).")
    st.success(msg)
    common.flash(msg)
    pend = common.conn().execute("SELECT COUNT(*) FROM match_candidates WHERE status='pending'").fetchone()[0]
    if pend:
        common.flash(f"{pend} possible duplicate(s) waiting in **More → Sources → Review duplicates**.", "info")
    return summary


def vin_lookup_block(prefix: str, inv: pd.DataFrame | None = None) -> None:
    st.caption("Already have it? It shows up below even if your filters hide it. Not in your data yet? Ask Auto.dev "
               "for that VIN (1 API call).")
    vin = clean_vin(st.text_input("VIN", key=f"{prefix}_vin", placeholder="7FCT…"))
    if not vin:
        return
    ok, why = validate_vin(vin)
    if not ok:
        st.warning(f"That VIN doesn't check out: {why}.")
        return
    if inv is not None and not inv.empty and (inv["vin"] == vin).any():
        st.success("Already in your inventory — search for it above to see it and why it's hidden, if it is.")
        st.session_state["inv_search"] = vin
        return
    if st.button("Look it up on Auto.dev (1 API call)", key=f"{prefix}_vinbtn", type="primary"):
        with st.spinner("Asking Auto.dev…"):
            res = services.lookup_vin(common.conn(), vin)
        if res.get("error"):
            st.error(res["error"])
        elif not res.get("found"):
            st.info("Auto.dev doesn't have a listing for that VIN. Use **Paste listing** or **Manual** instead.")
        else:
            common.flash(f"Added from Auto.dev: {res['title']}.")
            st.session_state["inv_search"] = vin
            st.rerun()


def paste_block(prefix: str) -> None:
    st.caption("On the listing page press Ctrl+A, Ctrl+C, then paste here with the URL. Only the text you paste is "
               "read — the page is never fetched.")
    url = st.text_input("Listing URL", key=f"{prefix}_url")
    blocked = capture.blocked_reason(url)
    if blocked:
        st.warning(blocked)
    text = st.text_area("Listing text", height=160, key=f"{prefix}_text")
    pages = rivian_page.split_pages(text) if text else []
    if pages:
        rivian_block(prefix, pages, url if len(pages) == 1 else None)
        return
    if forum_listing.is_forum_url(url):
        st.caption("RivianForums thread: the title and first post are read; replies are ignored.")
    if st.button("Read pasted text", key=f"{prefix}_parse", disabled=bool(blocked)):
        st.session_state[f"{prefix}_draft"] = capture.draft_from_text(text, url or None)
    draft = st.session_state.get(f"{prefix}_draft")
    if draft:
        draft_notes(draft)
        nl = listing_review_form(draft, f"{prefix}_form", "capture")
        if nl:
            save_draft(nl, draft, "capture")
            st.session_state.pop(f"{prefix}_draft", None)


def draft_notes(draft: dict) -> None:
    """Warnings about a parsed draft: nothing recognizable, or a forum thread that's sold or a wanted ad."""
    reason = capture.blank_draft_reason(draft)
    if reason:
        st.warning(reason)
    note = forum_listing.STATUS_NOTES.get(draft.get("forum_status"))
    if note:
        st.warning(note)


def save_draft(nl: NormalizedListing, draft: dict, trigger: str) -> dict | None:
    """Save a reviewed draft. A forum thread marked SOLD is recorded as sold right away."""
    summary = save_listings([nl], trigger)
    if summary and draft.get("forum_status") == "sold":
        pipeline.mark_removed(common.conn(), summary["listing_ids"][0], "Forum thread is marked SOLD")
    return summary


def rivian_block(prefix: str, pages: list[str], url: str | None) -> None:
    """Pasted Rivian Pre-Owned page(s): add or update each truck by VIN, with Rivian's build and warranty."""
    parsed = [rivian_page.parse(p) for p in pages]
    st.info(f"**{len(pages)} Rivian Pre-Owned page{'s' if len(pages) != 1 else ''}** — battery, motor, powered "
            "tonneau and warranty dates are saved as verified values; price, miles, location and build are updated.")
    st.dataframe(pd.DataFrame([{"VIN": p["vin"], "Truck": f"{p['year']} {p['title']}", "Price": p["price"],
                                "Miles": p["miles"], "Pickup": f"{p['city']}, {p['state']}" if p["city"] else "",
                                "Tonneau": p["tonneau"].title(),
                                "Warranty": p["warranty"].get("warranty_expiration", "")[:7]} for p in parsed]),
                 hide_index=True, column_config={"Price": st.column_config.NumberColumn(format="dollar"),
                                                 "Miles": st.column_config.NumberColumn(format="%,d")})
    if st.button(f"Save {len(pages)} from Rivian", type="primary", key=f"{prefix}_rivian"):
        added = updated = 0
        for page in pages:
            res = rivian_page.apply(common.conn(), page, url)
            added += res["added"]
            updated += not res["added"]
        common.flash(f"Rivian pages saved: {added} new truck(s), {updated} updated with Rivian's build, tonneau "
                     "and warranty.")
        st.rerun()


def manual_block(prefix: str) -> None:
    st.caption("Any truck: a Facebook post, a dealer you called, a friend's truck. A URL is stored as a link only.")
    defaults = search_targets(common.settings()["collection"])[0]
    nl = listing_review_form(defaults, f"{prefix}_manual", "manual", "Add truck",
                             show_claims=False)
    if nl:
        if nl.description:
            typed = {a.field for a in nl.attributes}
            nl.attributes += [a for a in extract_attributes(nl.description, "Parsed from your notes", make=nl.make, model=nl.model)
                              if a.field not in typed]
            if not nl.state:
                city, state, zip_code = parse_location(nl.description)
                nl.city, nl.state, nl.zip = nl.city or city, state, nl.zip or zip_code
        save_listings([nl], "manual_entry")


def email_block(prefix: str) -> None:
    st.caption("Alert emails from AutoTrader, Cars.com, CarGurus, KSL, CarMax, Carvana, and RivianForums watched-forum "
               "notifications… In Gmail: ⋮ → Download message gives a .eml file. Or paste the email.")
    files = st.file_uploader("Alert emails (.eml)", type=["eml"], accept_multiple_files=True, key=f"{prefix}_eml")
    pasted = st.text_area("…or paste the email", height=100, key=f"{prefix}_emlpaste")
    if st.button("Read emails", key=f"{prefix}_emlparse"):
        found: list[NormalizedListing] = []
        for f in files or []:
            try:
                meta, items = email_alerts.parse_eml_bytes(f.getvalue())
                found += items
                st.caption(f"{f.name}: {len(items)} listing link(s) — {meta['subject'][:80]}")
            except Exception as e:  # malformed email
                st.error(f"{f.name}: could not read ({type(e).__name__})")
        if pasted.strip():
            found += email_alerts.parse_pasted(pasted)
        st.session_state[f"{prefix}_found"] = found
    found = st.session_state.get(f"{prefix}_found") or []
    if not found:
        return
    st.write(f"Found **{len(found)}** listing link(s). Untick anything you don't want (wanted-to-buy posts and sold "
             "forum threads start unticked), fix values, then save.")
    table = pd.DataFrame([{
        "include": email_alerts.worth_saving(nl), "site": nl.source_key, "year": nl.year,
        "make": nl.make or "", "model": nl.model or "", "title": nl.title or "",
        "price": nl.price, "miles": nl.miles, "vin": nl.vin or "",
        "location": ", ".join(x for x in (nl.city, nl.state) if x), "url": nl.url} for nl in found])
    edited = st.data_editor(table, hide_index=True, key=f"{prefix}_emleditor", column_config={
        "include": st.column_config.CheckboxColumn("Save?"),
        "price": st.column_config.NumberColumn("Price", format="dollar", step=1),
        "miles": st.column_config.NumberColumn("Miles", format="%,d"),
        "year": st.column_config.NumberColumn("Year", format="%d"),
        "url": st.column_config.LinkColumn("URL")}, disabled=["site", "url"])
    if st.button("Save selected", type="primary", key=f"{prefix}_emlsave"):
        chosen = []
        for nl, (_, row) in zip(found, edited.iterrows()):
            if not row["include"]:
                continue
            nl.year = int(row["year"]) if pd.notna(row["year"]) else None
            nl.price = int(row["price"]) if pd.notna(row["price"]) else None
            nl.miles = int(row["miles"]) if pd.notna(row["miles"]) else None
            nl.vin = row["vin"] or None
            nl.make, nl.model = row["make"] or None, row["model"] or None
            chosen.append(nl)
        summary = save_listings(chosen, "email_import")
        for nl, listing_id in zip(chosen, (summary or {}).get("listing_ids", [])):
            if nl.source_key == forum_listing.SITE and forum_listing.parse_title(nl.title)["status"] == "sold":
                pipeline.mark_removed(common.conn(), listing_id, "Forum thread is marked SOLD")
        st.session_state.pop(f"{prefix}_found", None)


def add_truck_panel(inv: pd.DataFrame) -> None:
    """The '➕ Add a truck' expander at the top of Inventory."""
    with st.expander("➕ Add a truck (VIN lookup, paste a listing, manual, alert email)"):
        t = st.tabs(["By VIN", "Paste listing", "Manual", "Alert email"])
        with t[0]:
            vin_lookup_block("add", inv)
        with t[1]:
            paste_block("add")
        with t[2]:
            manual_block("add")
        with t[3]:
            email_block("add")


__all__ = ["add_truck_panel", "email_block", "manual_block", "paste_block", "queries", "save_listings",
           "vin_lookup_block"]
