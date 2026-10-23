"""One photo per truck: pick the best image URL and keep a small local thumbnail so it survives delisting.

Image URLs come from provider data (Auto.dev primaryImage, MarketCheck media), alert emails, the page preview image
the browser extension sends, or the user. Only that one image is downloaded per truck.
"""
from __future__ import annotations

import base64
import io
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image, UnidentifiedImageError

from . import config, links
from .sources.base import USER_AGENT

log = logging.getLogger(__name__)
MAX_BYTES = 8_000_000
SIZES = {"t": (400, 300), "m": (640, 480)}       # table thumbnail, detail image
UPLOAD = "upload"


def photo_dir() -> Path:
    d = config.DATA_DIR / "photos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(vehicle_id: int, size: str = "t") -> Path:
    return photo_dir() / f"{vehicle_id}_{size}.jpg"


def best_url(vehicle: dict, listings: list[dict]) -> str | None:
    """User's choice first, then an active seller listing's photo, then any listing photo."""
    if vehicle.get("photo_url"):
        return vehicle["photo_url"]
    rank = {"active": 0, "missing": 1, "removed": 2}
    candidates = [l for l in listings if (l.get("photo_url") or "").startswith(("http://", "https://"))]
    candidates.sort(key=lambda l: (rank.get(l.get("status"), 3),
                                   0 if links.listing_role(l.get("url"), l.get("seller_type"))[0] == "seller" else 1))
    return candidates[0]["photo_url"] if candidates else None


def save_image(vehicle_id: int, data: bytes) -> None:
    """Write the table and detail thumbnails. Raises ValueError for anything that isn't a readable image."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ValueError(f"not a usable image ({type(e).__name__})") from None
    img = img.convert("RGB")
    for size, box in SIZES.items():
        copy = img.copy()
        copy.thumbnail(box)
        copy.save(path_for(vehicle_id, size), "JPEG", quality=82, optimize=True)


def download(url: str, session: requests.Session | None = None, timeout: int = 15) -> bytes:
    s = session or requests.Session()
    with s.get(url, timeout=timeout, stream=True, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        if not (r.headers.get("Content-Type") or "image/").lower().startswith("image/"):
            raise ValueError("URL did not return an image")
        chunks, total = [], 0
        for chunk in r.iter_content(65536):
            total += len(chunk)
            if total > MAX_BYTES:
                raise ValueError("image too large")
            chunks.append(chunk)
    return b"".join(chunks)


def _todo(conn: sqlite3.Connection, limit: int, brands: list[str] | None = None) -> list[tuple[int, str]]:
    wanted = {brand.lower() for brand in brands} if brands is not None else None
    vehicles = {r["id"]: dict(r) for r in conn.execute(
        "SELECT * FROM vehicles WHERE merged_into_id IS NULL AND is_demo = 0")
        if wanted is None or (r["make"] or "").lower() in wanted}
    by_vehicle: dict[int, list[dict]] = {}
    for r in conn.execute("SELECT vehicle_id, url, status, seller_type, photo_url FROM listings WHERE photo_url IS NOT NULL"):
        by_vehicle.setdefault(r["vehicle_id"], []).append(dict(r))
    out = []
    for vid, v in vehicles.items():
        url = best_url(v, by_vehicle.get(vid, []))
        if not url or url == UPLOAD:
            continue
        if v.get("photo_cached_from") == url and path_for(vid).exists():
            continue
        out.append((vid, url))
        if len(out) >= limit:
            break
    return out


def cache_missing(conn: sqlite3.Connection, limit: int = 300, workers: int = 6,
                  session: requests.Session | None = None, brands: list[str] | None = None) -> dict:
    """Download and thumbnail photos for trucks that don't have a current local copy. Failures are skipped."""
    todo = _todo(conn, limit, brands)
    if not todo:
        return {"cached": 0, "failed": 0}

    def work(item):
        vid, url = item
        try:
            save_image(vid, download(url, session))
            return vid, url, None
        except (requests.RequestException, ValueError) as e:
            return vid, url, type(e).__name__

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(work, todo))
    ok = [(url, vid) for vid, url, err in results if err is None]
    with conn:
        conn.executemany("UPDATE vehicles SET photo_cached_from=? WHERE id=?", ok)
    return {"cached": len(ok), "failed": len(results) - len(ok)}


def set_user_photo(conn: sqlite3.Connection, vehicle_id: int, url: str | None = None, data: bytes | None = None) -> None:
    """Use a photo the user picked: an image URL or uploaded bytes. url=None and data=None clears the choice."""
    if data is not None:
        save_image(vehicle_id, data)
        with conn:
            conn.execute("UPDATE vehicles SET photo_url=?, photo_cached_from=? WHERE id=?", (UPLOAD, UPLOAD, vehicle_id))
        return
    if url:
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("Enter a full image URL starting with http(s)://")
        save_image(vehicle_id, download(url))
        with conn:
            conn.execute("UPDATE vehicles SET photo_url=?, photo_cached_from=? WHERE id=?", (url, url, vehicle_id))
        return
    with conn:
        conn.execute("UPDATE vehicles SET photo_url=NULL, photo_cached_from=NULL WHERE id=?", (vehicle_id,))


def data_uri(vehicle_id: int, size: str = "t") -> str | None:
    p = path_for(vehicle_id, size)
    if not p.exists():
        return None
    return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()


def upgrade_table_thumbs() -> int:
    """Rebuild old small table thumbnails (200 px) from the saved detail image — no downloads."""
    n = 0
    for t in photo_dir().glob("*_t.jpg"):
        m = t.with_name(t.name.replace("_t.jpg", "_m.jpg"))
        try:
            with Image.open(t) as im:
                if im.width >= SIZES["t"][0] - 20 or not m.exists():
                    continue
            with Image.open(m) as big:
                img = big.convert("RGB")
                img.thumbnail(SIZES["t"])
                img.save(t, "JPEG", quality=82, optimize=True)
                n += 1
        except (OSError, UnidentifiedImageError):
            continue
    return n
