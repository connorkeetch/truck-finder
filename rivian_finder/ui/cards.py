"""Card view for Inventory: one lightweight HTML component for all trucks (fast), with clicks sent back to Python.

Each card: photo, title, a price tag colored by the deal rating, small icon rows (miles, listed, location, seller,
battery · EPA range, motor, warranty, monthly, shipping), warning chips, and links. Clicking the photo or title
opens the truck's details; the checkbox selects it for compare / hide.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import compare, linkcheck, warranty

# deal label -> tag color (green = good for you, red = overpriced)
DEAL_COLORS = [("Great deal", "#2ea043"), ("Good deal", "#7bc96f"), ("Fair price", "#4fa3f7"),
               ("Above market", "#f0a63a"), ("Overpriced", "#e5534b"), ("⚠ Check title", "#e3b341")]
NOT_RATED = "#7d8590"


def deal_color(label: str | None) -> str:
    for prefix, color in DEAL_COLORS:
        if (label or "").startswith(prefix):
            return color
    return NOT_RATED


def _money(v) -> str:
    return "" if v is None or pd.isna(v) else f"${v:,.0f}"


def _listed(days) -> str:
    if days is None or pd.isna(days):
        return ""
    d = int(days)
    return "listed today" if d <= 0 else "listed yesterday" if d == 1 else f"listed {d} days"


def _json_safe(v):
    """NaN / NaT / numpy scalars -> plain JSON values (the browser rejects NaN in JSON)."""
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if v is None or isinstance(v, (str, bool)):
        return v
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        return v
    return v.item() if hasattr(v, "item") else v


def _shipping_text(cost, basis: str) -> str:
    if cost is None or cost != cost:
        return ""
    if basis.startswith("Distance unknown"):
        return "shipping unknown"
    if cost == 0:
        return "ship included" if basis.startswith("Included") else "local pickup"
    if basis.startswith("Fly & drive"):
        return f"{_money(cost)} fly & drive"
    return f"{_money(cost)} ship"


def payload(df: pd.DataFrame, picks: set[int], f: dict) -> list[dict]:
    """Plain dicts for the card component (df must already have 'photo' and '_near')."""
    max_price, max_miles = f.get("max_price") or 0, f.get("max_miles") or 0
    out = []
    for r in df.to_dict("records"):
        price, yours = r.get("price"), r.get("your_price")
        chips = []
        if r.get("match_status"):
            chips.append((f"{r['match_status']} · {int(r.get('match_score') or 0)}/100",
                          "warn" if r["match_status"] == "Does not qualify" else "note"))
        if r.get("title_status") == "branded":
            chips.append(("Branded title", "warn"))
        if r.get("accident_history") == "reported":
            chips.append(("Accident reported", "warn"))
        if r.get("_near"):
            bits = []
            p = yours if f.get("count_discounts", True) and yours == yours and yours else price
            if max_price and p == p and p and p > max_price:
                bits.append(f"{_money(p - max_price)} over max")
            if max_miles and r.get("miles") == r.get("miles") and r.get("miles") and r["miles"] > max_miles:
                bits.append(f"{r['miles'] - max_miles:,.0f} mi over max")
            chips.append(("Near miss" + (": " + ", ".join(bits) if bits else ""), "note"))
        if r.get("subframe") == "welded":
            chips.append(("Welded front subframe", "warn"))
        if r.get("to_confirm"):
            chips.append((f"❓ Confirm {r['to_confirm']}", "note"))
        if r.get("link_result") in linkcheck.PROBLEMS:
            chips.append((f"Link: {linkcheck.label(r['link_result'])}", "warn"))
        if r.get("flags"):
            chips.append((f"🔁 {r['flags']}", "note"))
        if r.get("hidden"):
            chips.append(("Hidden", "muted"))
        if not r.get("range_text"):
            chips.append(("Range unknown — verify", "note"))
        ends = warranty.ends_text(r.get("warranty_expires"), r.get("warranty_miles_limit"))
        left = (r.get("warranty") or "").split(" (to ")[0] if r.get("warranty_expires") else ""
        battery = "Uncertain" if r.get("battery_uncertain") else (r.get("battery") or "Unknown")
        motor = "Uncertain" if r.get("motor_uncertain") else (r.get("motor") or "Unknown")
        drops = int(r.get("price_drops") or 0)
        transport = r.get("transport_cost")
        dist = r.get("distance_mi")
        out.append({
            "vid": int(r["vehicle_id"]), "photo": r.get("photo") or "",
            "title": compare.vehicle_name(r),
            "fav": bool(r.get("favorite")), "selected": int(r["vehicle_id"]) in picks,
            "price": _money(yours if yours == yours and yours else price),
            "list_price": _money(price) if yours == yours and yours and price and yours < price else "",
            "deal": r.get("deal_label") or "Not rated", "deal_color": deal_color(r.get("deal_label")),
            "adjusted": _money(r.get("adjusted_price")) if r.get("adjust_note") else "",
            "adjust_note": r.get("adjust_note") or "",
            "vs_market": (("−" if r["deal_delta"] < 0 else "+") + _money(abs(r["deal_delta"])) + " vs market")
                         if r.get("deal_delta") == r.get("deal_delta") and r.get("deal_delta") is not None else "",
            "fit": int(r.get("match_score") or 0),
            "match_note": " · ".join([*r.get("match_failures", []), *r.get("match_missing", [])]),
            "miles": f"{r['miles']:,.0f} mi" if r.get("miles") == r.get("miles") and r.get("miles") is not None else "",
            "listed": _listed(r.get("days_listed")),
            "drops": f"{drops} price drop{'s' if drops != 1 else ''}" if drops else "",
            "location": r.get("location") or "",
            "distance": f"{dist:,.0f} mi away" if dist == dist and dist is not None else "",
            "seller": r.get("sold_by") or r.get("seller") or "",
            "battery": battery + (f" · {r['range_text']}" if r.get("range_text") else ""),
            "battery_note": r.get("battery_note") or "",
            "motor": motor,
            "tow": f"{r['tow_capacity_lbs']:,.0f} lb tow capacity" if pd.notna(r.get("tow_capacity_lbs")) else "Tow capacity unknown",
            "tow_note": " · ".join(x for x in (r.get("tow_src"), r.get("tow_conf")) if x),
            "warranty": (f"Warranty to {ends}" + (f" · {left} left" if left and left != "Comprehensive expired" else "")
                         if ends else "Warranty: add in-service date" if (r.get("make") or "Rivian") == "Rivian"
                         else "Warranty: verify this truck's terms"),
            "warranty_known": bool(ends),
            "monthly": _money(r.get("est_monthly")) + "/mo" if r.get("est_monthly") == r.get("est_monthly") else "",
            "shipping": _shipping_text(transport, r.get("transport_basis") or ""),
            "chips": chips, "notes": (r.get("notes") or "")[:160],
            "seller_url": r.get("seller_url") or "", "find_url": r.get("find_seller_url") or "",
            "carfax_url": r.get("history_report_url") or "",
        })
    return [_json_safe(c) for c in out]


ICONS = {
    "tag": '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8Z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
    "gauge": '<path d="M12 14l4-4"/><path d="M3.3 19a10 10 0 1 1 17.4 0"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "pin": '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11Z"/><circle cx="12" cy="10" r="2.5"/>',
    "store": '<path d="M3 9l1.5-5h15L21 9"/><path d="M4 9v11h16V9"/><path d="M9 20v-6h6v6"/>',
    "battery": '<rect x="2" y="7" width="17" height="10" rx="2"/><path d="M22 11v2"/><path d="M6 10v4M10 10v4"/>',
    "bolt": '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3Z"/>',
    "dollar": '<path d="M12 2v20"/><path d="M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "truck": '<path d="M2 6h11v10H2z"/><path d="M13 9h4l4 4v3h-8"/><circle cx="6" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
    "down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
}

CSS = """
:host { display:block; min-width:0; }
.grid-root { min-width:0; }
.grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, var(--card-min, 540px)), 1fr)); gap:12px; }
.card { display:flex; background:var(--st-secondary-background-color, #26282d); border:1px solid rgba(255,255,255,.07);
        border-radius:10px; overflow:hidden; color:var(--st-text-color, #e6e6e6); font-family:var(--st-font, sans-serif);
        font-size:13px; line-height:1.35; }
.card.selected { outline:2px solid var(--st-primary-color, #f5a623); }
.card.hidden { opacity:.6; }
.photo { position:relative; flex:0 0 var(--photo-w, 210px); background:#111 center/cover no-repeat;
         min-height:calc(var(--photo-w, 210px) * .72); }
.photo-open { display:block; width:100%; height:100%; min-height:inherit; padding:0; border:0; background:transparent; cursor:pointer; }
.photo img { width:100%; height:100%; object-fit:cover; display:block; }
.photo .noimg { width:100%; height:100%; display:flex; align-items:center; justify-content:center; color:#777; font-size:12px; }
.sel { position:absolute; top:6px; left:6px; width:44px; height:44px; padding:0; border-radius:5px; background:rgba(0,0,0,.55);
       display:flex; align-items:center; justify-content:center; cursor:pointer; border:1px solid rgba(255,255,255,.35); }
.sel.on { background:var(--st-primary-color, #f5a623); border-color:transparent; }
.sel.on::after { content:"✓"; color:#111; font-weight:700; font-size:14px; }
.fit { position:absolute; bottom:6px; left:6px; background:rgba(0,0,0,.65); border-radius:4px; padding:1px 6px; font-size:11px; pointer-events:none; }
.body { flex:1; min-width:0; padding:9px 12px 8px; display:flex; flex-direction:column; gap:4px; }
.head { display:flex; align-items:center; gap:6px; min-width:0; }
.title { flex:1; min-width:0; font-size:15px; font-weight:600; color:var(--st-link-color, #f5b94a); cursor:pointer; white-space:nowrap;
         overflow:hidden; text-overflow:ellipsis; min-height:44px; padding:0; border:0; background:transparent; text-align:left; font-family:inherit; }
.title:hover { text-decoration:underline; }
.star { flex:0 0 44px; min-width:44px; min-height:44px; padding:0; border:0; background:transparent;
        font-size:19px; line-height:1; color:#8b949e; cursor:pointer; user-select:none;
        transition:transform .1s; }
.star:hover { color:#f5c542; transform:scale(1.15); }
.star.on { color:#f5c542; }
.price { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.tag { display:inline-flex; align-items:center; gap:5px; border-radius:5px; padding:2px 8px 2px 6px; font-weight:700;
       font-size:15px; color:#0d1117; }
.tag svg { stroke:#0d1117; }
.list { color:#9aa0a6; text-decoration:line-through; font-size:12px; }
.deal { font-size:12px; font-weight:600; }
.adj { font-size:12.5px; color:#e6e6e6; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.adj b { color:#f5c542; font-weight:600; }
.muted { color:#9aa0a6; font-size:12px; }
.row { display:flex; flex-wrap:wrap; gap:4px 14px; color:#c9cdd2; }
.it { display:inline-flex; align-items:center; gap:4px; white-space:nowrap; }
svg.i { width:14px; height:14px; fill:none; stroke:currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round;
        flex:0 0 auto; opacity:.85; }
.chips { display:flex; flex-wrap:wrap; gap:4px; }
.chip { border-radius:10px; padding:1px 8px; font-size:11px; border:1px solid rgba(255,255,255,.15); }
.chip.warn { background:rgba(227,179,65,.15); color:#f0c95c; border-color:rgba(227,179,65,.4); }
.chip.note { background:rgba(79,163,247,.12); color:#9ccaf9; border-color:rgba(79,163,247,.35); }
.chip.muted { color:#9aa0a6; }
.notes { color:#b8bcc2; font-style:italic; font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.links { display:flex; flex-wrap:wrap; gap:4px 12px; margin-top:auto; padding-top:2px; font-size:12px; }
.links a, .links button { display:inline-flex; align-items:center; min-width:44px; min-height:44px; padding:0 4px; border:0;
                         background:transparent; font:inherit; color:var(--st-link-color, #f5b94a); text-decoration:none; cursor:pointer; }
.links a:hover, .links button:hover { text-decoration:underline; }
button:focus-visible, a:focus-visible { outline:3px solid var(--st-primary-color, #f5a623); outline-offset:-3px; }
.empty { color:#9aa0a6; padding:12px; }
@media (max-width:640px) {
  .grid { grid-template-columns:minmax(0, 1fr); }
  .card { flex-direction:column; }
  .photo { flex:none; width:100%; min-height:0; aspect-ratio:4 / 3; }
  .photo-open { min-height:0; }
  .title, .adj, .notes { white-space:normal; overflow:visible; text-overflow:clip; overflow-wrap:anywhere; }
  .it { white-space:normal; overflow-wrap:anywhere; }
  .body { padding:10px 12px; }
}
"""

JS = """
const ICONS = __ICONS__;
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl = (u) => { u = String(u || ''); return /^(https?:\\/\\/|app\\/static\\/)/i.test(u) ? esc(u) : ''; };
const icon = (n) => `<svg class="i" viewBox="0 0 24 24">${ICONS[n] || ''}</svg>`;
const it = (n, text, title) => text ? `<span class="it" title="${esc(title || '')}">${icon(n)}${esc(text)}</span>` : '';

function card(c) {
  const photo = safeUrl(c.photo) ? `<img loading="lazy" src="${safeUrl(c.photo)}" alt="">` : '<div class="noimg">no photo</div>';
  const chips = (c.chips || []).map(([t, k]) => `<span class="chip ${esc(k)}">${esc(t)}</span>`).join('');
  const link = (u, t) => safeUrl(u) ? `<a href="${safeUrl(u)}" target="_blank" rel="noopener noreferrer">${esc(t)} ↗</a>` : '';
  return `<div class="card${c.selected ? ' selected' : ''}" data-vid="${c.vid}" data-name="${esc(c.title)}">
    <div class="photo"><button type="button" class="photo-open" data-act="open" aria-label="Open details for ${esc(c.title)}">${photo}</button>
      <button type="button" class="sel${c.selected ? ' on' : ''}" data-act="toggle" role="checkbox"
        aria-checked="${Boolean(c.selected)}" aria-label="Select ${esc(c.title)} to compare or hide" title="Select to compare or hide"></button>
      <div class="fit" title="Personal score">personal ${esc(c.fit)}</div></div>
    <div class="body">
      <div class="head"><button type="button" class="star${c.fav ? ' on' : ''}" data-act="fav" aria-pressed="${Boolean(c.fav)}"
          aria-label="${c.fav ? 'Remove' : 'Add'} ${esc(c.title)} ${c.fav ? 'from' : 'to'} favorites"
          title="${c.fav ? 'Remove from favorites' : 'Add to favorites'}">${c.fav ? '★' : '☆'}</button>
        <button type="button" class="title" data-act="open">${esc(c.title)}</button></div>
      <div class="price">
        <span class="tag" style="background:${esc(c.deal_color)}" title="${esc(c.deal)}">${icon('tag')}${esc(c.price)}</span>
        ${c.list_price ? `<span class="list" title="List price before your discount">${esc(c.list_price)}</span>` : ''}
        <span class="deal" style="color:${esc(c.deal_color)}">${esc(c.deal)}</span>
        ${c.vs_market ? `<span class="muted">${esc(c.vs_market)}</span>` : ''}
      </div>
      ${c.adjusted ? `<div class="adj" title="Your adjusted price: price + shipping − what the features are worth to you">
        <b>≈ ${esc(c.adjusted)} for you</b> <span class="muted">${esc(c.adjust_note)}</span></div>` : ''}
      <div class="row">${it('gauge', c.miles)}${it('clock', c.listed)}${it('down', c.drops)}
        ${it('pin', [c.location, c.distance].filter(Boolean).join(' · '))}${it('store', c.seller)}</div>
      <div class="row">${it('battery', c.battery, c.battery_note)}${it('bolt', c.motor, 'Motor')}
        ${it('truck', c.tow, c.tow_note)}${it('shield', c.warranty)}${it('dollar', c.monthly, 'Estimated monthly payment')}${it('truck', c.shipping)}</div>
      ${chips ? `<div class="chips">${chips}</div>` : ''}
      ${c.match_note ? `<div class="muted" title="${esc(c.match_note)}">${esc(c.match_note)}</div>` : ''}
      ${c.notes ? `<div class="notes" title="${esc(c.notes)}">“${esc(c.notes)}”</div>` : ''}
      <div class="links">${link(c.seller_url, 'Seller listing')}${!c.seller_url ? link(c.find_url, 'Find seller') : ''}
        ${link(c.carfax_url, 'Carfax')}<button type="button" data-act="open">Details</button></div>
    </div></div>`;
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  let root = parentElement.querySelector('.grid-root');
  if (!root) { root = document.createElement('div'); root.className = 'grid-root'; parentElement.appendChild(root); }
  const cards = (data && data.cards) || [];
  root.style.setProperty('--photo-w', `${(data && data.photo_w) || 210}px`);
  root.style.setProperty('--card-min', `${(data && data.card_min) || 540}px`);
  root.innerHTML = cards.length ? `<div class="grid">${cards.map(card).join('')}</div>`
                                : '<div class="empty">No trucks match.</div>';
  const onClick = (e) => {
    const el = e.target.closest('[data-act]');
    if (!el || el.tagName === 'A') return;
    const cardEl = el.closest('.card');
    if (!cardEl) return;
    const vid = Number(cardEl.dataset.vid);
    if (el.dataset.act === 'toggle') {
      e.stopPropagation();
      const on = !el.classList.contains('on');
      el.classList.toggle('on', on); cardEl.classList.toggle('selected', on);   // instant feedback
      el.setAttribute('aria-checked', String(on));
      setTriggerValue('action', { kind: 'toggle', vid, on, t: Date.now() });
    } else if (el.dataset.act === 'fav') {
      const on = !el.classList.contains('on');
      el.classList.toggle('on', on); el.textContent = on ? '★' : '☆';             // instant feedback
      el.title = on ? 'Remove from favorites' : 'Add to favorites';
      el.setAttribute('aria-pressed', String(on));
      el.setAttribute('aria-label', `${on ? 'Remove' : 'Add'} ${cardEl.dataset.name || 'this truck'} ${on ? 'from' : 'to'} favorites`);
      setTriggerValue('action', { kind: 'fav', vid, on, t: Date.now() });
    } else {
      setTriggerValue('action', { kind: 'open', vid, t: Date.now() });
    }
  };
  root.onclick = onClick;             // replace (not add): this function runs again on every refresh
  return () => { if (root.onclick === onClick) root.onclick = null; };
}
"""

PHOTO_W = {"S": 150, "M": 180, "L": 210, "XL": 260}


@st.cache_resource
def _component():
    import json
    return st.components.v2.component("rivian_truck_cards", css=CSS, js=JS.replace("__ICONS__", json.dumps(ICONS)))


def render(cards: list[dict], key: str, on_action, size: str = "L"):
    """Mount the card grid; on_action() runs when a card is clicked (read st.session_state[key]['action'])."""
    photo_w = PHOTO_W.get(size, 210)
    return _component()(key=key, data={"cards": cards, "photo_w": photo_w, "card_min": 330 + photo_w},
                        on_action_change=on_action)
