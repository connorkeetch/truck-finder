"""Shipping estimates, flip detector, checklist/call log, alerts, notifications, scheduler, phone access."""
import base64
import json
import sqlite3
from datetime import date
from types import SimpleNamespace

import pytest
from conftest import FakeAdapter, listing, vin

from rivian_finder import (access, alerts, attributes, checklist, cli, db, flips, notifier, pipeline, queries,
                           scheduler, services, shipping)
from rivian_finder.models import FetchResult

# ------------------------------------------------------------------ shipping

CFG = {**shipping.DEFAULTS, "fee_sellers": ["carvana", "carmax"],
       "fly_drive": {**shipping.DEFAULTS["fly_drive"], "enabled": False}}   # shipping rules alone


@pytest.mark.parametrize("lst,dist,cost,basis", [
    ({"source_key": "carvana", "url": "https://www.carvana.com/vehicle/1"}, 900, 990, "Carvana delivery fee est."),
    ({"source_key": "carvana", "url": "https://www.carvana.com/vehicle/1"}, 345, 290, "Carvana delivery fee est."),  # Vegas
    ({"source_key": "carvana", "url": "https://www.carvana.com/vehicle/1"}, None, 990, "Carvana delivery fee est."),
    ({"source_key": "marketcheck", "seller_name": "Carmax Salt Lake (South Jordan)", "url": "https://x.example"}, 20, 0,
     "Local pickup"),
    ({"source_key": "autodev", "url": "https://www.carmax.com/car/123"}, 900, 990, "CarMax delivery fee est."),
    ({"source_key": "carvana", "url": "https://www.carvana.com/vehicle/1", "transport_cost": 390}, 900, 390,
     "Your estimate"),                                                   # the exact fee you typed from the listing
    ({"source_key": "dealer", "url": "https://d.example"}, 80, 0, "Local pickup"),
    ({"source_key": "dealer", "url": "https://d.example"}, 1000, 1450, "Shipping est."),   # 300 + .95*1200 = 1440 → 1450
    ({"source_key": "dealer", "url": "https://d.example"}, 200, 600, "Shipping est."),     # minimum applies
    ({"source_key": "dealer", "url": "https://d.example", "transport_cost": 0}, 1000, 0, "Your estimate"),
    ({"source_key": "dealer", "url": "https://d.example"}, None, 250, "Distance unknown"),
])
def test_shipping_rules(lst, dist, cost, basis):
    got_cost, got_basis = shipping.estimate(lst, dist, CFG, fallback=250)
    assert got_cost == cost and got_basis.startswith(basis)


def test_fly_and_drive_when_cheaper():
    cfg = {**CFG, "fly_drive": {**shipping.DEFAULTS["fly_drive"], "enabled": True}}
    cost, basis = shipping.estimate({"source_key": "dealer", "url": "https://d.example"}, 345, cfg)   # ~414 road mi
    assert cost == 170 and basis.startswith("Fly & drive: flight $60 + charging $59")                  # vs ~$700 shipping
    assert "cheaper than shipping ($700)" in basis


def test_fly_and_drive_limits():
    cfg = {**CFG, "fly_drive": {**shipping.DEFAULTS["fly_drive"], "enabled": True}}
    carvana = {"source_key": "carvana", "url": "https://www.carvana.com/vehicle/1"}
    assert shipping.estimate(carvana, 345, cfg)[0] == 290                     # Carvana delivers — no fly & drive
    far = shipping.estimate({"source_key": "dealer", "url": "https://d.example"}, 1000, cfg)       # 1,200 road mi
    assert far[1].startswith("Shipping est.")
    typed = shipping.estimate({"source_key": "dealer", "url": "https://d.example", "transport_cost": 900}, 345, cfg)
    assert typed == (900.0, "Your estimate")
    carmax = shipping.estimate({"source_key": "carmax", "url": "https://www.carmax.com/car/1"}, 345, cfg)
    assert carmax[0] == 170                                                      # cheaper than CarMax's $290 fee


def test_seller_fee_schedule_is_editable():
    cfg = {**CFG, "fee_sellers": ["carvana"], "fee_far": 1200.0}
    assert shipping.estimate({"source_key": "carvana", "url": "https://www.carvana.com/vehicle/1"}, 1000, cfg)[0] == 1200
    # CarMax no longer on the fee list → ordinary per-mile estimate
    assert shipping.estimate({"source_key": "carmax", "url": "https://www.carmax.com/car/1"}, 1000, cfg)[1].startswith(
        "Shipping est.")


def test_inventory_uses_shipping_in_total_cost(conn, settings):
    pipeline.import_listings(conn, [listing("dealer", import_method="manual", url="https://far.example/1", vin=vin(1),
                                            zip="98101", state="WA", city="Seattle", price=50000)], "manual_entry")
    row = queries.inventory_frame(conn, settings).iloc[0]
    assert row["transport_cost"] > 600 and row["transport_basis"].startswith("Shipping est.")
    assert row["total_cost"] == pytest.approx(50000 + 3725 + 400 + row["transport_cost"])


# ------------------------------------------------------------------ flips

def L(seller, first, last, status="active", **kw):
    return {"seller_name": seller, "first_seen_at": first, "last_seen_at": last, "status": status, **kw}


def test_flip_changed_dealers():
    r = flips.detect([L("Dealer A", "2026-08-01", "2026-09-01", "missing"), L("Dealer B", "2026-09-20", "2026-10-20")], [])
    assert r["flags"] == ["Changed dealers"] and "Dealer A" in r["text"] and "now Dealer B" in r["text"]


def test_same_dealer_on_two_sites_is_not_a_flip():
    r = flips.detect([L("AutoMatch", "2026-10-01", "2026-10-20"), L("Automatch", "2026-10-02", "2026-10-20")], [])
    assert not r["flip"]


def test_flip_relisted_and_listed_elsewhere_first():
    r = flips.detect([L("X", "2026-10-01", "2026-10-20", days_on_market=156, days_on_market_here=126)],
                     [{"event_type": "returned", "created_at": "2026-10-10T00:00:00Z"}])
    assert r["flags"] == ["Relisted after a gap", "Listed elsewhere first"]
    assert "about 30 days somewhere else" in r["text"]


def test_flip_from_seller_change_event():
    r = flips.detect([L("New Dealer", "2026-09-01", "2026-10-20")],
                     [{"event_type": "seller_change", "old_value": "Old Dealer", "created_at": "2026-10-01T00:00:00Z"}])
    assert "Changed dealers" in r["flags"]


# ------------------------------------------------------------------ checklist & contacts

def _truck(conn, **kw):
    pipeline.import_listings(conn, [listing("dealer", import_method="manual", url="https://d.example/1", vin=vin(1), **kw)],
                             "manual_entry")
    return conn.execute("SELECT id FROM vehicles").fetchone()[0]


def test_checklist_answers_feed_verified_values(conn):
    from rivian_finder.models import AttributeClaim
    vid = _truck(conn, attributes=[AttributeClaim("battery", "Large", "medium", "listing"),
                                   AttributeClaim("motor", "Quad", "medium", "listing")])
    answers = {k: ("todo", "") for k, _, _ in checklist.ITEMS}
    answers.update(tonneau=("ok", "opened/closed twice"), title=("problem", "rebuilt per Carfax"), config=("ok", ""))
    fed = checklist.save(conn, vid, answers)
    r = attributes.resolve(conn, vid)
    assert r["tonneau"].value == "yes" and r["tonneau"].confidence == "verified"
    assert r["title_status"].value == "branded"
    assert r["battery"].value == "Large" and r["battery"].confidence == "verified"
    assert set(fed) >= {"tonneau = yes", "title_status = branded", "battery = Large", "motor = Quad"}
    p = checklist.progress(conn)[vid]
    assert (p["done"], p["problems"]) == (3, 1) and p["text"] == f"3/{len(checklist.ITEMS)} · 1 problem"
    assert checklist.save(conn, vid, answers) == []          # unchanged answers don't re-feed


def test_contact_log(conn, settings):
    vid = _truck(conn)
    checklist.add_contact(conn, vid, "call", "Jake (sales)", "Will take $1k off; tonneau works", date(2026, 10, 25))
    cid = checklist.add_contact(conn, vid, "text", "", "Sent offer")
    row = queries.inventory_frame(conn, settings).iloc[0]
    assert row["follow_up"] == "2026-10-25" and row["last_contact"]
    assert len(checklist.contacts(conn, vid)) == 2
    checklist.delete_contact(conn, cid)
    assert len(checklist.contacts(conn, vid)) == 1


# ------------------------------------------------------------------ alerts

def test_alert_contents(conn, settings):
    a = FakeAdapter("autodev", [FetchResult([listing(vin=vin(1), price=60000)], True, "s"),
                                FetchResult([listing(vin=vin(1), price=58500), listing(vin=vin(2), price=55000)], True, "s")])
    pipeline.run_search(conn, [a], {})
    v1 = conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin(1),)).fetchone()[0]
    services.toggle_favorite(conn, v1, True)
    s2 = pipeline.run_search(conn, [a], {})
    out = alerts.collect(conn, s2["run_id"], settings)
    assert out["count"] == 2
    assert out["title"] == "MotorSift: 1 new vehicle, 1 favorite price drop"
    assert any(l.startswith("★ −$1,500") for l in out["lines"]) and any(l.startswith("New: 2024") for l in out["lines"])
    settings["alerts"] = {**alerts.DEFAULTS, "min_drop": 2000}
    assert alerts.collect(conn, s2["run_id"], settings)["count"] == 1


# ------------------------------------------------------------------ notifications

def test_windows_toast_command_escapes_text():
    cmd = notifier.command("Rivian <Finder>", "New: 2024 R1T $58,990 & up\nline2", "http://127.0.0.1:8501", "Windows")
    assert cmd[0] == "powershell.exe" and "-EncodedCommand" in cmd
    script = base64.b64decode(cmd[-1]).decode("utf-16-le")
    assert "Rivian &lt;Finder&gt;" in script and "$58,990 &amp; up" in script and "launch=\"http://127.0.0.1:8501\"" in script
    assert notifier.WIN_APP_ID in script


def test_mac_and_linux_commands():
    mac = notifier.command("T", 'say "hi"', system="Darwin")
    assert mac[0] == "osascript" and '\\"hi\\"' in mac[2]


# ------------------------------------------------------------------ scheduler

def test_scheduler_commands_and_validation():
    cmds = scheduler.create_commands(["08:00", "18:30"])
    assert cmds[0][:7] == ["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", "08:00"]
    assert cmds[1][cmds[1].index("/TN") + 1] == "RivianFinder\\Search 1830"
    assert cmds[0][-1].endswith('run_alerts.pyw"')
    with pytest.raises(ValueError):
        scheduler.create_commands(["8am"])


def test_scheduler_install_and_remove_with_fake_runner(monkeypatch):
    monkeypatch.setattr(scheduler, "supported", lambda: True)
    calls = []

    def run(cmd):
        calls.append(cmd)
        if cmd[:2] == ["schtasks", "/Query"]:
            return SimpleNamespace(returncode=0, stdout='"\\RivianFinder\\Search 0800","10/21/2026 8:00:00 AM","Ready"\n'
                                                       '"\\Other\\Task","N/A","Ready"\n', stderr="")
        return SimpleNamespace(returncode=0, stdout="SUCCESS", stderr="")

    assert scheduler.installed(run) == [{"name": "RivianFinder\\Search 0800", "next_run": "10/21/2026 8:00:00 AM",
                                         "status": "Ready"}]
    ok, msg = scheduler.install(["08:00"], run)
    assert ok and any(c[:2] == ["schtasks", "/Delete"] for c in calls) and any(c[:2] == ["schtasks", "/Create"] for c in calls)


# ------------------------------------------------------------------ phone access

def test_access_pin(tmp_path):
    with pytest.raises(ValueError):
        access.save(True)                       # no PIN yet
    with pytest.raises(ValueError):
        access.save(True, "12a4")
    access.save(True, "482913")
    data = json.loads(access.path().read_text())
    assert data["lan"] and "482913" not in json.dumps(data)
    assert access.check_pin("482913") and not access.check_pin("000000") and not access.check_pin("")
    access.save(False)
    assert not access.load()["lan"] and access.check_pin("482913")   # PIN kept when turning off


def test_launcher_reads_lan_flag(tmp_path, monkeypatch):
    import launcher
    monkeypatch.setenv("RIVIAN_FINDER_DATA_DIR", str(tmp_path))
    assert not launcher.lan_enabled()
    (tmp_path / "app_access.json").write_text(json.dumps({"lan": True}))
    assert launcher.lan_enabled()


# ------------------------------------------------------------------ budget guard + migration

def test_budget_guard_skips_low_sources(conn, monkeypatch):
    monkeypatch.setattr(services, "available_sources", lambda c: [
        {"key": "autodev", "name": "Auto.dev", "enabled": True, "configured": True},
        {"key": "demo", "name": "Demo", "enabled": True, "configured": True}])
    pipeline.run_search(conn, [FakeAdapter("autodev", [FetchResult([listing(vin=vin(1))], True, "s", api_calls=24)])], {})
    for _ in range(990):
        conn.execute("INSERT INTO api_usage(source_key, called_at, endpoint, status_code) VALUES ('autodev', ?, 'x', 200)",
                     (pipeline.utcnow(),))
    keep, skipped = cli.budget_ok_sources(conn, {})
    assert keep == ["demo"] and skipped and "10 calls left" in skipped[0]


def test_migration_005_backfills_dom_active(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    for name in ("001_initial", "002_seller_links_and_hiding", "003_history_recalls_market", "004_photos"):
        c.executescript((db.MIGRATIONS_DIR / f"{name}.sql").read_text())
        c.execute("INSERT INTO schema_migrations VALUES (?, 'x')", (name,))
    c.execute("INSERT INTO vehicles(id, vin, created_at, updated_at) VALUES (1, 'X', 'x', 'x')")
    c.execute("INSERT INTO listings(vehicle_id, source_key, import_method, first_seen_at, last_seen_at, raw_json)"
              " VALUES (1, 'marketcheck', 'api', 'x', 'x', ?)", (json.dumps({"dom": 156, "dom_active": 126}),))
    c.commit()
    c.close()
    c = db.connect(path)
    assert c.execute("SELECT days_on_market_here FROM listings").fetchone()[0] == 126
    assert c.execute("SELECT COUNT(*) FROM checklist").fetchone()[0] == 0
