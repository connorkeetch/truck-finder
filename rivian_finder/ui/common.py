"""Shared UI plumbing: connection, settings, formatting, capture server, sidebar actions."""
from __future__ import annotations

import json
import logging
import logging.handlers
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from .. import compare, config, db, export_xlsx, photos, queries, services
from ..credentials import RedactingFilter
from ..importers.capture_server import CaptureServer
from ..sources.base import configured_brands, search_targets

TONNEAU_ICON = {"yes": "✅", "no": "❌", "unknown": "❔"}


@st.cache_resource
def _setup_logging() -> bool:
    config.ensure_dirs()
    handler = logging.handlers.RotatingFileHandler(config.LOG_DIR / "rivian_finder.log", maxBytes=1_000_000,
                                                   backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger("rivian_finder")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return True


@st.cache_resource
def _conn():
    return db.connect(config.DB_PATH)


def conn():
    return _conn()


@st.cache_data(show_spinner=False, max_entries=3)
def _inventory(_c, fingerprint: tuple, settings_json: str) -> pd.DataFrame:
    return queries.inventory_frame(_c, json.loads(settings_json))


def inventory(s: dict | None = None) -> pd.DataFrame:
    """queries.inventory_frame, recomputed only when the database, the settings or the date change.

    total_changes counts every write made through this app's connection; data_version changes when another
    connection commits (the scheduled search, the extension receiver)."""
    c = conn()
    s = s if s is not None else settings()
    fingerprint = (c.total_changes, c.execute("PRAGMA data_version").fetchone()[0], date.today().isoformat())
    return _inventory(c, fingerprint, json.dumps(s, sort_keys=True, default=str))


def reset_connection() -> None:
    try:
        _conn().close()
    except Exception:
        pass
    _conn.clear()


@st.cache_resource
def capture_server() -> CaptureServer | None:
    try:
        return CaptureServer(config.DB_PATH, config.CAPTURE_HOST, config.CAPTURE_PORT).start()
    except OSError:
        logging.getLogger("rivian_finder").warning("capture server port %s unavailable", config.CAPTURE_PORT)
        return None


@st.cache_resource
def _upgrade_thumbs() -> int:
    return photos.upgrade_table_thumbs()


def boot() -> None:
    _setup_logging()
    capture_server()
    _upgrade_thumbs()
    st.markdown(
        """<style>
        div[data-testid="stMetricValue"] {font-size: 1.6rem;}
        .rf-badge {display:inline-block;padding:1px 8px;border-radius:10px;font-size:0.78rem;margin-right:4px;
                   background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.10);}
        .rf-demo {background:#3a2a00;color:#ffd27a;border-color:#5c4300;}
        </style>""", unsafe_allow_html=True)


def remote_gate() -> None:
    """Devices other than this computer must enter the PIN (and phone access must be turned on)."""
    if st.context.ip_address is None or st.session_state.get("remote_ok"):
        return
    from .. import access
    import time
    st.title("🛻 Truck Finder")
    if not access.load().get("lan"):
        st.error("Phone access is turned off. Turn it on in Settings → Phone access on your computer.")
        st.stop()
    with st.form("pin_gate"):
        pin = st.text_input("PIN", type="password")
        if st.form_submit_button("Unlock", type="primary"):
            if access.check_pin(pin):
                st.session_state["remote_ok"] = True
                st.rerun()
            time.sleep(1.5)        # slow down guessing
            st.error("Wrong PIN")
    st.stop()


def settings() -> dict:
    return db.load_settings(conn())


def save_settings(s: dict) -> None:
    db.save_settings(conn(), s)


# ----------------------------------------------------------------- formatting

def md(text: str) -> str:
    """Escape $ so Streamlit markdown doesn't treat '$800 … $400' as a math formula."""
    return (text or "").replace("$", "\\$")


def money(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"${v:,.0f}"


def miles(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{int(v):,} mi"


def local_time(iso: str | None) -> str:
    if not isinstance(iso, str) or not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%b %d, %Y %I:%M %p")
    except ValueError:
        return iso


def vehicle_label(row) -> str:
    bits = [compare.vehicle_name(row)]
    bits.append(money(row.get("price")))
    if pd.notna(row.get("miles")):
        bits.append(miles(row.get("miles")))
    if row.get("location"):
        bits.append(row["location"])
    if row.get("vin"):
        bits.append("…" + row["vin"][-6:])
    if row.get("is_demo"):
        bits.append("DEMO")
    return " · ".join(bits)


@st.cache_data(show_spinner=False, max_entries=2000)
def _thumb(vehicle_id: int, size: str, mtime: float) -> str | None:
    return photos.data_uri(vehicle_id, size)


STATIC_PHOTOS = Path(__file__).resolve().parents[2] / "static" / "photos"   # served at app/static/photos/


def _static_photo(p: Path) -> str:
    """Mirror a cached thumbnail into Streamlit's static folder and return its URL, so the browser downloads it
    once and caches it (embedding every photo in every refresh was ~3.5 MB per click)."""
    src = p.stat()
    dest = STATIC_PHOTOS / p.name
    try:
        d = dest.stat()
        fresh = d.st_size == src.st_size and d.st_mtime >= src.st_mtime
    except FileNotFoundError:
        fresh = False
    if not fresh:
        STATIC_PHOTOS.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    return f"app/static/photos/{p.name}?v={int(src.st_mtime)}"


def photo_src(vehicle_id: int, remote_url: str | None = "", size: str = "t") -> str | None:
    """Local thumbnail (a cached static file, or a data URI if static serving is off), else the provider's URL."""
    p = photos.path_for(int(vehicle_id), size)
    if p.exists():
        if st.get_option("server.enableStaticServing"):
            try:
                return _static_photo(p)
            except OSError:
                pass
        return _thumb(int(vehicle_id), size, p.stat().st_mtime)
    return _web_url(remote_url)


def _web_url(url) -> str | None:
    """Only a real web address — 'upload' marks a photo you added, whose local file may be missing."""
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None


def photo_image(vehicle_id: int, remote_url: str | None = "") -> str | None:
    """For st.image: the local detail thumbnail if cached, else the provider's image URL."""
    p = photos.path_for(int(vehicle_id), "m")
    return str(p) if p.exists() else _web_url(remote_url)


PHOTO_SIZES = {"S": 64, "M": 120, "L": 180, "XL": 260}     # table row height in px; photo is 4:3


def photo_size() -> str:
    return (settings().get("ui") or {}).get("photo_size", "L")


def photo_size_control(key: str) -> str:
    """S/M/L/XL picker that remembers the choice."""
    current = photo_size()
    choice = st.segmented_control("Photo size", list(PHOTO_SIZES), default=current, key=key) or current
    if choice != current:
        s = settings()
        s.setdefault("ui", {})["photo_size"] = choice
        save_settings(s)
    return choice


def table_height(n_rows: int, row_height: int) -> int:
    """Tall enough to show every row (so only the page scrolls); Streamlit caps tables at 10,000 px."""
    return min(10_000, (n_rows + 1) * row_height + 4) if n_rows else 120


def add_photo_column(df):
    df = df.copy()
    df["photo"] = [photo_src(v, u) for v, u in zip(df["vehicle_id"], df["photo_url"])]
    return df


def flash(message: str, kind: str = "success") -> None:
    """Queue a message that survives the next st.rerun()."""
    st.session_state.setdefault("_flash", []).append((kind, message))


def show_flash() -> None:
    for kind, message in st.session_state.pop("_flash", []):
        getattr(st, kind)(message)


def table_key(name: str) -> str:
    """Widget key for a selectable table; bumping the nonce clears its selection."""
    return f"{name}_{st.session_state.get(name + '_nonce', 0)}"


def open_vehicle(vehicle_id: int, from_table: str | None = None) -> None:
    st.session_state["selected_vehicle"] = int(vehicle_id)
    if from_table:
        st.session_state[from_table + "_nonce"] = st.session_state.get(from_table + "_nonce", 0) + 1
    st.switch_page(st.session_state["_pages"]["vehicle"])


# ----------------------------------------------------------------- sidebar

@st.dialog("Which trucks should we refresh?")
def search_dialog(keys: list[str] | None = None) -> None:
    s = settings()
    try:
        available = configured_brands(s["collection"])
        targets = search_targets(s["collection"])
    except ValueError as exc:
        st.error(f"Check your makes and models in Settings → Collection scope: {exc}")
        return
    labels = {make: f"{make} ({', '.join(t['model'] for t in targets if t['make'].casefold() == make.casefold())})"
              for make in available}
    previous = [b for b in st.session_state.get("last_search_brands", []) if b in available]
    selected = st.multiselect("Brands to refresh", ["All brands", *available],
                              default=previous or available[:1],
                              format_func=lambda brand: labels.get(brand, brand), key="search_brands",
                              help="Choose one or more configured makes, or All brands for every configured make/model.")
    brands = available if "All brands" in selected else [b for b in selected if b in available]
    st.caption("Only the selected brands will be refreshed. Your saved price, mileage, distance and range limits still apply.")
    if not brands:
        st.info("Choose at least one brand to start.")
    start, cancel = st.columns(2)
    if cancel.button("Cancel", key="search_cancel", width="stretch"):
        st.rerun()
    if start.button("Start search", type="primary", disabled=not brands, key="search_start", width="stretch") and brands:
        with st.spinner("Searching… (respecting provider rate limits)"):
            summary = services.run_sources(conn(), keys, s, brands=brands)
        st.session_state["last_search_brands"] = brands
        st.session_state["last_summary"] = summary
        flash(summary.get("text", "Done"), "error" if summary.get("status") == "failed" else "success")
        st.rerun()


def sidebar() -> None:
    c = conn()
    with st.sidebar:
        st.markdown("### 🛻 Truck Finder")
        st.session_state["_actions_box"] = st.container()   # filled by pages when table rows are ticked
        ready = [s for s in services.available_sources(c) if s["enabled"] and s["configured"]]
        names = ", ".join(s["name"] for s in ready) or "none"
        if st.button("▶ Run Search", type="primary", width="stretch",
                     help=f"Choose brands, then search with enabled, configured connectors: {names}"):
            search_dialog()
        st.caption(f"Connectors ready: {names}")
        if st.button("🔗 Check listing links", width="stretch",
                     help="Opens each listing link once — only where the site allows automated checks — to find dead "
                          "or moved pages. Sites that block bots are marked 'check manually', never worked around. "
                          "Takes a few minutes."):
            from .. import linkcheck
            bar = st.progress(0.0, text="Checking links…")
            summary = linkcheck.check_all(c, progress=lambda d, n: bar.progress(d / max(n, 1), text=f"Checked {d} of {n}"))
            bar.empty()
            flash(linkcheck.summary_text(summary) + (" Sort by **Link problems first** to see them." if summary["problems"]
                                                      else ""), "warning" if summary["problems"] else "success")
            st.rerun()
        if st.button("📊 Prepare Excel export", width="stretch"):
            with st.spinner("Building workbook…"):
                s = settings()
                data = export_xlsx.export_bytes(c, s)
                target = Path(s["export"]["export_dir"]) if s["export"].get("export_dir") else config.EXPORT_DIR
                target.mkdir(parents=True, exist_ok=True)
                path = target / f"rivian_finder_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
                path.write_bytes(data)
            st.session_state["export_bytes"] = data
            st.session_state["export_path"] = str(path)
        if st.session_state.get("export_bytes"):
            st.download_button("⬇ Download .xlsx", st.session_state["export_bytes"],
                               file_name=st.session_state["export_path"].split("\\")[-1].split("/")[-1],
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               width="stretch")
            st.caption(f"Also saved to `{st.session_state['export_path']}`")
        demo = c.execute("SELECT COUNT(*) FROM vehicles WHERE is_demo=1").fetchone()[0]
        if demo:
            st.markdown(f"<span class='rf-badge rf-demo'>Includes {demo} synthetic demo vehicles</span>",
                        unsafe_allow_html=True)
        st.caption(f"Data: `{config.DB_PATH}`")


def selection_actions(c, selected, table: str) -> None:
    """Actions for ticked table rows, shown at the top of the sidebar so they're visible at any scroll position."""
    from .. import hiding
    if selected.empty:
        return
    box = st.session_state.get("_actions_box")
    ids = [int(v) for v in selected["vehicle_id"]]
    target = box if box is not None else st.container()
    with target.container(border=True):
        names = [str(n) for n in selected.get("sold_by", selected.get("location", []))][:3]
        st.markdown(f"**{len(ids)} truck{'s' if len(ids) != 1 else ''} selected**"
                    + (f"  \n<small>{', '.join(names)}{'…' if len(ids) > 3 else ''}</small>" if names else ""),
                    unsafe_allow_html=True)
        if len(ids) == 1 and st.button("🔎 Open details", type="primary", width="stretch", key=f"{table}_open"):
            open_vehicle(ids[0], table)
        if 2 <= len(ids) <= 4 and st.button("⚖ Compare", type="primary", width="stretch", key=f"{table}_cmp"):
            st.session_state["compare_ids"] = ids
            _bump(table)
            st.switch_page(st.session_state["_pages"]["compare"])
        all_fav = bool(selected["favorite"].all()) if "favorite" in selected else False
        if st.button("☆ Unfavorite" if all_fav else "★ Favorite", width="stretch", key=f"{table}_fav"):
            for vid in ids:
                services.toggle_favorite(c, vid, not all_fav)
            _bump(table)
            st.rerun()
        reason = st.selectbox("Not interested because", list(hiding.HIDE_REASONS), format_func=hiding.reason_label,
                              key=f"{table}_reason")
        if st.button("🚫 Not interested", width="stretch", key=f"{table}_hide",
                     help="Hides the truck(s) from Dashboard, Inventory and Excel. 'Title issues' also records "
                          "the title as branded. Undo: Inventory → 🚫 Hidden → tick → Restore."):
            for vid in ids:
                hiding.hide_vehicle(c, vid, reason)
            flash(f"Hid {len(ids)} truck(s): {hiding.reason_label(reason)}. Inventory → 🚫 Hidden shows them.", "info")
            _bump(table)
            st.rerun()
        hidden_ids = [int(v) for v, h in zip(selected["vehicle_id"], selected.get("hidden", [])) if h]
        if hidden_ids and st.button("↩ Restore", width="stretch", key=f"{table}_restore"):
            for vid in hidden_ids:
                hiding.restore_vehicle(c, vid)
            _bump(table)
            st.rerun()
        if st.button("Clear selection", width="stretch", key=f"{table}_clear"):
            _bump(table)
            st.rerun()


def _bump(table: str) -> None:
    st.session_state[table + "_nonce"] = st.session_state.get(table + "_nonce", 0) + 1
