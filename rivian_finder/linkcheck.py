"""Check that listing links still lead to the truck's page — politely, and only where sites allow it.

One GET per link with an honest User-Agent; robots.txt is respected; requests to the same site are spaced out.
A site that answers with a bot check ("Access Denied", "Just a moment…") is not retried or worked around: the
rest of its links are marked "check manually" without another request. Only the HTTP status, the final URL and
a short note are stored — never page content.
"""
from __future__ import annotations

import re
import sqlite3
import time
import urllib.robotparser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

import requests

from .db import utcnow
from .sources.base import USER_AGENT

# result -> (short label for tables, explanation)
RESULTS = {
    "ok": ("✓ live", "The page loads and still points at this truck."),
    "gone": ("✗ dead link", "This address no longer works (the site answered 'not found' / 'gone'). Often the truck "
                            "sold — but dealers sometimes move a listing to a new address, so look on the dealer's "
                            "site (Find seller) before hiding it."),
    "moved": ("↪ moved", "The link now redirects to a general inventory page — often the truck sold, but check the "
                         "dealer's inventory before hiding it."),
    "maybe_gone": ("⚠ sold?", "The page loads but its heading says the vehicle is no longer available."),
    "blocked": ("? check", "This site blocks automated checks — open the link yourself."),
    "not_allowed": ("? check", "This site's robots.txt asks tools not to open these pages — open the link yourself."),
    "not_checkable": ("? check", "A search-results or listing-network link (Autolist, Vast): a status check can't "
                                 "tell whether the truck is still for sale — open it yourself."),
    "error": ("? check", "Couldn't reach the site — try again later or open the link yourself."),
}
PROBLEMS = ("gone", "moved", "maybe_gone")
SEARCH_ONLY_HOSTS = ("autolist.com", "autotempest.com")      # links are search pages; the truck is in the #fragment
EXPIRING_HOSTS = ("vast.com",)          # click-through links with a token that expires — a 410 says nothing about the truck
BOT_MARKERS = re.compile(r"just a moment|attention required|access denied|are you a robot|captcha|verify you are "
                         r"human|request unsuccessful|pardon our interruption", re.I)
GONE_HEADINGS = re.compile(r"page not found|\b404\b|not found|no longer available|has been sold|vehicle (?:is )?sold|"
                           r"no longer in (?:our )?inventory|vehicle not available|listing (?:has )?(?:expired|ended)",
                           re.I)
VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
READ_LIMIT = 300_000
PER_HOST_DELAY = 2.5


def label(result: str | None) -> str:
    return RESULTS.get(result or "", ("", ""))[0]


def explain(result: str | None) -> str:
    return RESULTS.get(result or "", ("", ""))[1]


def host_of(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def not_checkable(url: str) -> bool:
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in SEARCH_ONLY_HOSTS + EXPIRING_HOSTS) or \
        bool(re.search(r"(?:^|&)(?:vin|listing)=", parts.fragment))


def identifiers(url: str) -> list[str]:
    """Bits of the URL that name this truck: a VIN, or a long listing number / hash at the end of the path."""
    parts = urlsplit(url)
    ids = VIN_RE.findall(url.upper())
    last = re.sub(r"\.\w{2,5}$", "", parts.path.rstrip("/").split("/")[-1])
    for token in re.split(r"[-_]", last) + [last]:
        if re.fullmatch(r"\d{5,}", token) or re.fullmatch(r"[0-9a-f]{12,}", token, re.I):
            ids.append(token)
    return list(dict.fromkeys(i.lower() for i in ids))


def _text(html: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.I | re.S)
    return re.sub(r"<[^>]+>|\s+", " ", m.group(1)).strip() if m else ""


def classify(url: str, status: int, final_url: str, html: str) -> tuple[str, str]:
    """(result, note) from one response. Pure function — easy to test."""
    title, h1 = _text(html, "title"), _text(html, "h1")
    if status in (404, 410):
        return "gone", f"HTTP {status}"
    if status in (401, 403, 429, 503) or (status == 200 and BOT_MARKERS.search(title)):
        return "blocked", f"HTTP {status}" + (f" — “{title[:60]}”" if title else "")
    if status >= 500:
        return "error", f"HTTP {status}"
    if status != 200:
        return "error", f"HTTP {status}"
    if GONE_HEADINGS.search(title) or GONE_HEADINGS.search(h1):
        return "maybe_gone", f"page heading: “{(h1 or title)[:80]}”"
    ids = identifiers(url)
    moved_path = urlsplit(final_url).path.rstrip("/").lower() != urlsplit(url).path.rstrip("/").lower()
    if moved_path and ids and not any(i in final_url.lower() for i in ids):
        return "moved", f"redirects to {urlsplit(final_url).netloc}{urlsplit(final_url).path or '/'}"
    vin = VIN_RE.findall(url.upper())
    return "ok", "page shows this VIN" if vin and vin[0] in html.upper() else "page loads"


def _robots(session, url: str, timeout: int) -> urllib.robotparser.RobotFileParser:
    parts = urlsplit(url)
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = session.get(f"{parts.scheme}://{parts.netloc}/robots.txt", timeout=timeout, headers={"User-Agent": USER_AGENT})
        if r.status_code in (401, 403):
            rp.disallow_all = True
        elif r.status_code == 200:
            rp.parse(r.text.splitlines())
        else:
            rp.allow_all = True
    except requests.RequestException:
        rp.allow_all = True
    return rp


def _fetch(session, url: str, timeout: int) -> tuple[int, str, str]:
    with session.get(url, timeout=timeout, allow_redirects=True, stream=True,
                     headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}) as r:
        chunks, size = [], 0
        for chunk in r.iter_content(chunk_size=65536):
            chunks.append(chunk)
            size += len(chunk)
            if size >= READ_LIMIT:
                break
        enc = r.encoding or "utf-8"
        return r.status_code, r.url, b"".join(chunks).decode(enc, "ignore")


def check_host(urls: list[str], session=None, delay: float = PER_HOST_DELAY, timeout: int = 15,
               sleep=time.sleep) -> dict[str, tuple[str, int | None, str | None, str]]:
    """Check one site's links in order. Returns url -> (result, http_status, final_url, note)."""
    session = session or requests.Session()
    out: dict[str, tuple[str, int | None, str | None, str]] = {}
    rp = None
    blocked_note = None
    for i, url in enumerate(urls):
        if not_checkable(url):
            out[url] = ("not_checkable", None, None, "listing-network link that expires" if
                        any(host_of(url).endswith(h) for h in EXPIRING_HOSTS) else "search-results link")
            continue
        if blocked_note:
            out[url] = ("blocked", None, None, f"not retried — {blocked_note}")
            continue
        if rp is None:
            rp = _robots(session, url, timeout)
        if not rp.can_fetch(USER_AGENT, url):
            out[url] = ("not_allowed", None, None, "robots.txt disallows automated access")
            continue
        if any(v[1] is not None for v in out.values()):
            sleep(delay)                            # space out requests to the same site
        try:
            status, final, html = _fetch(session, url, timeout)
        except requests.RequestException as e:
            out[url] = ("error", None, None, type(e).__name__)
            continue
        result, note = classify(url, status, final, html)
        out[url] = (result, status, final, note)
        if result == "blocked":
            blocked_note = f"the site blocked the first check ({note})"
    return out


def urls_to_check(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT l.url FROM listings l JOIN vehicles v ON v.id = l.vehicle_id"
                        " WHERE l.url IS NOT NULL AND l.url != '' AND l.status IN ('active', 'missing')"
                        " AND l.is_demo = 0 AND v.merged_into_id IS NULL")
    return [r[0] for r in rows if r[0].lower().startswith(("http://", "https://"))]


def check_all(conn: sqlite3.Connection, urls: list[str] | None = None, progress=None, session_factory=requests.Session,
              max_sites_at_once: int = 6, **kw) -> dict:
    """Check every active listing link (one site at a time per worker), save the results, return a summary."""
    urls = urls if urls is not None else urls_to_check(conn)
    by_host: dict[str, list[str]] = defaultdict(list)
    for u in urls:
        by_host[host_of(u)].append(u)
    results: dict[str, tuple] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max_sites_at_once) as pool:
        futures = {pool.submit(check_host, group, session_factory(), **kw): host for host, group in by_host.items()}
        for fut in as_completed(futures):
            results.update(fut.result())
            done += len(by_host[futures[fut]])
            if progress:
                progress(done, len(urls))
    now = utcnow()
    with conn:
        conn.executemany("INSERT OR REPLACE INTO link_checks(url, checked_at, result, http_status, final_url, note)"
                         " VALUES (?,?,?,?,?,?)", [(u, now, *r) for u, r in results.items()])
    counts: dict[str, int] = defaultdict(int)
    for r in results.values():
        counts[r[0]] += 1
    return {"checked": len(results), "counts": dict(counts),
            "problems": sorted(u for u, r in results.items() if r[0] in PROBLEMS)}


def summary_text(summary: dict) -> str:
    c = summary["counts"]
    manual = sum(c.get(k, 0) for k in ("blocked", "not_allowed", "not_checkable", "error"))
    bad = sum(c.get(k, 0) for k in PROBLEMS)
    return (f"Checked {summary['checked']} links: {c.get('ok', 0)} live, {bad} dead or moved (look on the dealer's "
            f"site before hiding — the truck may just have a new address), "
            f"{manual} need a manual look (sites that block automated checks, robots.txt limits, search-page links).")


def latest(conn: sqlite3.Connection) -> dict[str, dict]:
    return {r["url"]: dict(r) for r in conn.execute("SELECT * FROM link_checks")}
