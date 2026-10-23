"""Reusable review form for a listing draft (manual entry, paste capture, extension capture)."""
from __future__ import annotations

import streamlit as st

from ..config import TONNEAU_STATUSES, US_STATES
from ..db import SOURCE_SEED
from ..extract import identify_site
from ..models import AttributeClaim, NormalizedListing
from ..vin import validate_vin

SITE_CHOICES = [k for k, _, kind, _ in SOURCE_SEED if kind == "site"]
SITE_NAMES = {k: n for k, n, _, _ in SOURCE_SEED}
FORM_TONNEAU = ["unknown", "yes", "no"]


def listing_review_form(draft: dict, key: str, import_method: str, submit_label: str = "Save listing",
                        show_claims: bool = True) -> NormalizedListing | None:
    """Show editable fields prefilled from `draft`. Returns a NormalizedListing when submitted and valid."""
    claims: list[AttributeClaim] = list(draft.get("claims") or [])
    claim_map = {cl.field: cl for cl in claims}
    if show_claims and claims:
        with st.expander(f"What we parsed ({len(claims)} equipment claims — check them)", expanded=True):
            for cl in claims:
                label = TONNEAU_STATUSES.get(cl.value, cl.value) if cl.field == "tonneau" else cl.value
                st.markdown(f"- **{cl.field}**: {label} · *{cl.confidence}* — “{cl.evidence or ''}”")
    with st.form(key):
        c1, c2, c3 = st.columns(3)
        url = c1.text_input("Listing URL (stored as a link only; never fetched)", draft.get("url") or "")
        detected, _ = identify_site(url) if url else (draft.get("source") or "other", None)
        default_site = draft.get("source") if draft.get("source") in SITE_CHOICES else detected
        site = c2.selectbox("Site", SITE_CHOICES, index=SITE_CHOICES.index(default_site) if default_site in SITE_CHOICES else SITE_CHOICES.index("other"),
                            format_func=lambda k: SITE_NAMES.get(k, k))
        vin = c3.text_input("VIN", draft.get("vin") or "")
        c1, c2 = st.columns(2)
        make = c1.text_input("Make", draft.get("make") or "", placeholder="e.g. Toyota, Ford, Ram")
        model = c2.text_input("Model", draft.get("model") or "",
                              placeholder="e.g. Tacoma, F-150, 1500")
        c1, c2, c3, c4 = st.columns(4)
        year = c1.number_input("Year", 0, 2030, int(draft.get("year") or 0), help="0 = unknown")
        trim = c2.text_input("Trim", draft.get("trim") or "")
        price = c3.number_input("Price ($)", 0, 300000, int(draft.get("price") or 0), 100, help="0 = unknown")
        miles_known = draft.get("miles") is not None
        miles = c4.number_input("Mileage", 0, 500000, int(draft.get("miles") or 0), 100)
        c1, c2, c3, c4 = st.columns(4)
        seller = c1.text_input("Seller", draft.get("seller_name") or "")
        seller_type = c2.selectbox("Seller type", ["unknown", "dealer", "private", "manufacturer", "retailer"],
                                   index=["unknown", "dealer", "private", "manufacturer", "retailer"].index(draft.get("seller_type") or "unknown")
                                   if (draft.get("seller_type") or "unknown") in ["unknown", "dealer", "private", "manufacturer", "retailer"] else 0)
        city = c3.text_input("City", draft.get("city") or "")
        st_opts = [""] + US_STATES
        state = c4.selectbox("State", st_opts, index=st_opts.index(draft.get("state")) if draft.get("state") in st_opts else 0)
        c1, c2, c3, c4 = st.columns(4)
        zip_code = c1.text_input("ZIP", draft.get("zip") or "")
        color = c2.text_input("Exterior color", (claim_map.get("exterior_color").value if claim_map.get("exterior_color") else draft.get("exterior_color")) or "")
        bat_default = claim_map["battery"].value if "battery" in claim_map else "Unknown"
        battery = c3.text_input("Battery (as listed)", "" if bat_default == "Unknown" else bat_default,
                                placeholder="e.g. Large, Extended Range, Max Range") or "Unknown"
        mot_default = claim_map["motor"].value if "motor" in claim_map else "Unknown"
        motor = c4.text_input("Motor (as listed)", "" if mot_default == "Unknown" else mot_default) or "Unknown"
        c1, c2 = st.columns(2)
        range_default = claim_map.get("epa_range")
        tow_default = claim_map.get("tow_capacity_lbs")
        epa_range = c1.number_input("EPA range (mi, 0 = unknown)", 0, 600, int(range_default.value) if range_default else 0)
        tow = c2.number_input("Tow capacity (lb, 0 = unknown)", 0, 40000, int(tow_default.value) if tow_default else 0, 100,
                              help="Enter this truck's rating from its listing or sticker. Do not use a model's advertised maximum.")
        c1, c2, c3 = st.columns(3)
        ton_default = claim_map["tonneau"].value if "tonneau" in claim_map else "unknown"
        tonneau = c1.selectbox("Powered tonneau (per listing)", FORM_TONNEAU,
                               index=FORM_TONNEAU.index(ton_default) if ton_default in FORM_TONNEAU else 0,
                               format_func=lambda k: TONNEAU_STATUSES[k],
                               help="To mark it confirmed working, use Vehicle details → Verify equipment after you check it yourself.")
        transport = c2.number_input("Transport estimate ($)", 0, 20000, int(draft.get("transport_cost") or 0), 50)
        miles_unknown = c3.checkbox("Mileage unknown", value=not miles_known and not draft.get("miles"))
        desc = st.text_area("Listing text / notes", draft.get("description") or "", height=120)
        photo = st.text_input("Photo URL (optional — right-click the listing photo → Copy image address)",
                              draft.get("photo_url") or "")
        submitted = st.form_submit_button(submit_label, type="primary")
    if not submitted:
        return None
    if not make.strip() or not model.strip():
        st.error("Enter the vehicle's make and model before saving.")
        return None
    if url.strip() and site == "other":
        # the Site box can't react to a URL typed inside the form, so detect it on submit
        site = identify_site(url.strip())[0]
    if vin.strip():
        ok, why = validate_vin(vin)
        if not ok:
            st.warning(f"VIN not validated ({why}). The listing will be saved without automatic VIN matching.")
    if not any((price, vin.strip(), url.strip(), year)):
        st.error("Enter at least a URL, VIN, year or price.")
        return None

    def keep(field, value, user_choice_default):
        """Keep the parsed claim if the user left the parsed value, otherwise record the user's edit."""
        parsed = claim_map.get(field)
        if parsed and parsed.value == value:
            return parsed
        if value in (None, "", user_choice_default):
            return None
        return AttributeClaim(field, value, "medium", "Entered by user from listing")

    new_claims = [cl for cl in claims if cl.field not in ("battery", "motor", "tonneau", "exterior_color", "epa_range", "tow_capacity_lbs")]
    for cl in (keep("battery", battery, "Unknown"), keep("motor", motor, "Unknown"), keep("tonneau", tonneau, "unknown"),
               keep("exterior_color", color.strip(), ""), keep("epa_range", str(epa_range) if epa_range else None, None),
               keep("tow_capacity_lbs", str(tow) if tow else None, None)):
        if cl:
            new_claims.append(cl)
    _, site_id = identify_site(url) if url else (None, None)
    return NormalizedListing(
        source_key=site, import_method=import_method, source_listing_id=site_id if site_id and site == identify_site(url)[0] else None,
        url=url.strip() or None, vin=vin.strip() or None, year=int(year) or None, make=make.strip(), model=model.strip(),
        trim=trim.strip() or None, price=int(price) or None, miles=None if miles_unknown else int(miles),
        seller_name=seller.strip() or None, seller_type=seller_type, city=city.strip() or None, state=state or None,
        zip=zip_code.strip() or None, exterior_color=color.strip() or None, transport_cost=int(transport) or None,
        title=draft.get("title") or None, description=desc.strip() or None, attributes=new_claims,
        photo_url=photo.strip() if photo.strip().lower().startswith(("http://", "https://")) else None,
    )
