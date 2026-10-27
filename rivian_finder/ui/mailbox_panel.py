"""Sources → Email alerts → Automatic import: read alert emails from one mailbox folder on every search."""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from .. import cloud, credentials, services
from ..db import get_pref
from . import common

GMAIL_STEPS = """
**Gmail setup (about 5 minutes):**
1. Turn on [2-Step Verification](https://myaccount.google.com/signinoptions/two-step-verification), then create an
   [app password](https://myaccount.google.com/apppasswords) named *MotorSift*.
2. Make a label, e.g. **Truck alerts**, and a filter that applies it to your alert emails, e.g.
   `from:(ksl.com OR rivianforums.com OR autotrader.com OR cars.com OR cargurus.com)`.
3. Turn on saved-search alerts on those sites (KSL saved searches; RivianForums → *Rivians / Vehicles For Sale* →
   **Watch** with email notifications).
4. Enter your address, the label, and the app password below.

Only that label is read. Messages are opened read-only, so nothing is marked read, moved or deleted.
"""


def render() -> None:
    c = common.conn()
    s = common.settings()
    cfg = s["email_import"]
    with st.container(border=True):
        st.markdown("**Automatic import from your mailbox**")
        status = st.empty()              # filled in last, so it includes a check made with the button below
        with st.expander("Set up / change"):
            st.markdown(GMAIL_STEPS)
            with st.form("mailbox_settings"):
                enabled = st.toggle("Import alert emails automatically", cfg["enabled"])
                a, b = st.columns([3, 1])
                host = a.text_input("IMAP server", cfg["host"])
                port = b.number_input("Port", 1, 65535, int(cfg["port"]))
                a, b = st.columns(2)
                username = a.text_input("Email address", cfg["username"])
                folder = b.text_input("Folder or Gmail label", cfg["mailbox"])
                a, b = st.columns(2)
                lookback = a.number_input("Look back (days)", 1, 90, int(cfg["lookback_days"]),
                                          help="Emails older than this are ignored, even the first time.")
                per_run = b.number_input("Emails per check", 1, 500, int(cfg["max_per_run"]))
                if cloud.is_cloud():
                    password = ""
                    st.caption("Set the app password in this Railway service's Variables as "
                               "`TRUCK_FINDER_IMAP_PASSWORD`.")
                else:
                    password = st.text_input("App password (saved in your OS credential store)", type="password",
                                             help="Leave blank to keep the saved one.")
                if st.form_submit_button("Save", type="primary"):
                    s["email_import"].update(enabled=enabled, host=host.strip(), port=int(port),
                                             username=username.strip(), mailbox=folder.strip() or "INBOX",
                                             lookback_days=int(lookback), max_per_run=int(per_run))
                    common.save_settings(s)
                    if password.strip():
                        try:
                            credentials.save_api_key("imap", password.replace(" ", ""))
                        except Exception as e:
                            st.error(f"Couldn't save the password: {e}")
                    st.success("Saved.")
            if cfg["username"]:              # don't touch the credential store until there's a mailbox to use
                pw, where = ((os.environ.get(credentials.KEYS["imap"], ""), "env") if cloud.is_cloud()
                             else credentials.get_api_key("imap"))
                st.caption("App password: " + {"env": "set by the TRUCK_FINDER_IMAP_PASSWORD environment variable.",
                                               "keyring": "saved in your OS credential store."}.get(where if pw else "",
                                                                                                    "not set."))
                if where == "keyring" and st.button("Remove saved app password"):
                    credentials.delete_api_key("imap")
                    st.rerun()
        if st.button("Check mailbox now", disabled=not cfg["enabled"]):
            with st.spinner("Reading alert emails…"):
                summary = services.check_mailbox(c, s)
            (st.error if summary["status"] == "failed" else st.success)(summary["text"])
        last = get_pref(c, "email_import_last")
        status.caption(f"{'On' if cfg['enabled'] else 'Off'}. Checked with every Run Search and scheduled search, "
                       "without listing API calls."
                       + (f" Last check {common.local_time(last['at'])}: {last['text']}" if last else ""))
        recent = c.execute("SELECT imported_at, sender, subject, listings, saved FROM email_inbox"
                           " ORDER BY imported_at DESC, rowid DESC LIMIT 10").fetchall()
        if recent:
            st.caption("Recently imported emails")
            st.dataframe(pd.DataFrame([{**dict(r), "imported_at": common.local_time(r["imported_at"])}
                                       for r in recent]), hide_index=True, width="stretch",
                         column_config={"imported_at": "Imported", "sender": "From", "subject": "Subject",
                                        "listings": "Listings", "saved": "Saved"})
