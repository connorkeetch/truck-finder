"""Photo URLs from every source, and local thumbnails."""
import io
import json
import sqlite3

from PIL import Image
from conftest import FIXTURES, listing, load_json, vin
from test_sources import FakeResponse, adapter

from rivian_finder import db, photos, pipeline, queries
from rivian_finder.importers import capture, email_alerts
from rivian_finder.sources import autodev, marketcheck


def jpeg(w=800, h=600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (40, 90, 60)).save(buf, "JPEG")
    return buf.getvalue()


class ImageResponse:
    def __init__(self, data, ctype="image/jpeg", status=200):
        self.data, self.status_code, self.headers = data, status, {"Content-Type": ctype}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("requests").HTTPError(str(self.status_code))

    def iter_content(self, n):
        yield self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ImageSession:
    def __init__(self, bad=()):
        self.bad, self.urls = set(bad), []

    def get(self, url, timeout=None, stream=None, headers=None):
        self.urls.append(url)
        return ImageResponse(b"<html>", "text/html") if url in self.bad else ImageResponse(jpeg())


def test_best_url_prefers_user_then_active_seller():
    ls = [{"photo_url": "https://agg.example/a.jpg", "url": "https://www.autotrader.com/cars-for-sale/vehicle/7",
           "status": "active", "seller_type": None},
          {"photo_url": "https://dealer.example/d.jpg", "url": "https://dealer-site.example/r1t", "status": "active",
           "seller_type": "dealer"},
          {"photo_url": "https://old.example/o.jpg", "url": "https://other-dealer.example/x", "status": "removed"}]
    assert photos.best_url({}, ls) == "https://dealer.example/d.jpg"
    assert photos.best_url({"photo_url": "https://me.example/p.jpg"}, ls) == "https://me.example/p.jpg"
    assert photos.best_url({}, []) is None


def test_thumbnails_are_written_small():
    photos.save_image(1, jpeg(1600, 1200))
    for size, (w, h) in photos.SIZES.items():
        with Image.open(photos.path_for(1, size)) as im:
            assert im.width <= w and im.height <= h
    assert photos.data_uri(1).startswith("data:image/jpeg;base64,")


def test_cache_missing_downloads_once_and_skips_failures(conn):
    pipeline.import_listings(conn, [
        listing("dealer", import_method="manual", url="https://a.example/1", vin=vin(1), photo_url="https://img.example/1.jpg"),
        listing("dealer", import_method="manual", url="https://b.example/2", vin=vin(2), photo_url="https://img.example/bad"),
        listing("dealer", import_method="manual", url="https://c.example/3", vin=vin(3))], "manual_entry")
    sess = ImageSession(bad={"https://img.example/bad"})
    assert photos.cache_missing(conn, session=sess) == {"cached": 1, "failed": 1}
    v1 = conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin(1),)).fetchone()[0]
    assert photos.path_for(v1).exists()
    photos.cache_missing(conn, session=sess)
    assert sess.urls.count("https://img.example/1.jpg") == 1          # cached: not downloaded again


def test_user_upload_wins_and_can_be_cleared(conn, settings):
    pipeline.import_listings(conn, [listing("dealer", import_method="manual", url="https://a.example/1", vin=vin(1),
                                            photo_url="https://img.example/1.jpg")], "manual_entry")
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    photos.set_user_photo(conn, vid, data=jpeg())
    assert queries.inventory_frame(conn, settings).iloc[0]["photo_url"] == photos.UPLOAD
    assert photos.cache_missing(conn, session=ImageSession()) == {"cached": 0, "failed": 0}
    photos.set_user_photo(conn, vid)                                   # back to the listing photo
    assert queries.inventory_frame(conn, settings).iloc[0]["photo_url"] == "https://img.example/1.jpg"


def test_provider_photo_urls():
    a = adapter(autodev.AutoDevAdapter, [FakeResponse(200, load_json("autodev_page1.json")),
                                         FakeResponse(200, load_json("autodev_page2.json"))])
    first = a.fetch({}).listings[0]
    assert first.photo_url == "https://img.example/autodev/1.jpg" and first.photo_count == 24
    assert marketcheck._first_photo({"photo_links": ["not-a-url", "https://cdn.example/p1.jpg"]}) == "https://cdn.example/p1.jpg"
    assert marketcheck._first_photo(None) is None


def test_email_card_photo_skips_logos_and_pixels():
    html = """<table><tr><td><img src="https://cdn.example/logo.png" width="120" height="40">
      <img src="https://track.example/open.gif" width="1" height="1">
      <a href="https://www.autotrader.com/cars-for-sale/vehicle/711000123"><img src="https://img.example/truck.jpg"></a>
      <div>2024 Rivian R1T</div><div>$59,000</div><div>12,000 miles</div></td></tr></table>"""
    (item,) = email_alerts.parse_alert(html=html)
    assert item.photo_url == "https://img.example/truck.jpg"
    _, items = email_alerts.parse_eml_bytes((FIXTURES / "synthetic_autotrader_alert.eml").read_bytes())
    assert {i.source_listing_id: i.photo_url for i in items}["711000001"] == "https://img.example/1.jpg"


def test_capture_preview_image_flows_to_listing(conn):
    cid = capture.enqueue(conn, "extension", "https://dealer.example/r1t", "R1T", "$60,000", "https://dealer.example/og.jpg")
    row = conn.execute("SELECT * FROM capture_queue WHERE id=?", (cid,)).fetchone()
    d = capture.draft_from_text(row["text"], row["url"], row["title"], row["image_url"])
    assert capture.listing_from_draft(d).photo_url == "https://dealer.example/og.jpg"
    assert capture.draft_from_text("x", None, None, "javascript:alert(1)")["photo_url"] == ""


def test_migration_004_backfills_autodev_photos(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    for name in ("001_initial", "002_seller_links_and_hiding", "003_history_recalls_market"):
        c.executescript((db.MIGRATIONS_DIR / f"{name}.sql").read_text())
        c.execute("INSERT INTO schema_migrations VALUES (?, 'x')", (name,))
    c.execute("INSERT INTO vehicles(id, vin, created_at, updated_at) VALUES (1, 'X', 'x', 'x')")
    raw = {"retailListing": {"primaryImage": "https://retail.photos.vin/X-1.jpg", "photoCount": 12}}
    c.execute("INSERT INTO listings(vehicle_id, source_key, import_method, first_seen_at, last_seen_at, raw_json)"
              " VALUES (1, 'autodev', 'api', 'x', 'x', ?)", (json.dumps(raw),))
    c.commit()
    c.close()
    c = db.connect(path)
    assert tuple(c.execute("SELECT photo_url, photo_count FROM listings").fetchone()) == ("https://retail.photos.vin/X-1.jpg", 12)


def test_old_small_table_thumbs_are_rebuilt_from_detail_image():
    photos.save_image(7, jpeg(1600, 1200))
    small = photos.path_for(7, "t")
    Image.open(io.BytesIO(jpeg(200, 150))).save(small, "JPEG")      # simulate an old 200 px thumbnail
    assert photos.upgrade_table_thumbs() == 1
    with Image.open(small) as im:
        assert im.width == photos.SIZES["t"][0]
    assert photos.upgrade_table_thumbs() == 0                       # already upgraded


def test_table_height_shows_all_rows_up_to_cap():
    from rivian_finder.ui import common
    assert common.table_height(10, 180) == 11 * 180 + 4
    assert common.table_height(500, 180) == 10_000
