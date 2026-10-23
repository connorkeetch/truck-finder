"""SQLite connection handling, migrations, settings storage, and seed data."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open (and migrate) the database. Pass ':memory:' for tests."""
    path = str(db_path or config.DB_PATH)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    seed(conn)
    from . import repairs
    repairs.run_all(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    newly = []
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = sql_file.stem
        if version in applied:
            continue
        with conn:
            conn.executescript(sql_file.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, utcnow()))
        newly.append(version)
    return newly


SOURCE_SEED = [
    # key, name, kind, enabled
    ("autodev", "Auto.dev Listings API", "api", 1),
    ("marketcheck", "MarketCheck Inventory API", "api", 1),
    ("demo", "Demo data (synthetic)", "demo", 1),
    ("rivian", "Rivian Pre-Owned (rivian.com)", "site", 1),
    ("carmax", "CarMax", "site", 1),
    ("carvana", "Carvana", "site", 1),
    ("autotrader", "AutoTrader", "site", 1),
    ("autotempest", "AutoTempest", "site", 1),
    ("ksl", "KSL Cars", "site", 1),
    ("facebook", "Facebook Marketplace", "site", 1),
    ("cars_com", "Cars.com", "site", 1),
    ("cargurus", "CarGurus", "site", 1),
    ("truecar", "TrueCar", "site", 1),
    ("dealer", "Independent dealer website", "site", 1),
    ("other", "Other / unknown site", "site", 1),
]

SAVED_SEARCH_SEED = [
    ("Rivian Pre-Owned inventory", "rivian",
     "https://rivian.com/configurations/list?INVENTORY_TYPE=PRE_OWNED_VEHICLE",
     "Optional EV-truck source. Check eligibility and equipment for the specific vehicle."),
    ("CarMax search", "carmax", "https://www.carmax.com/cars",
     "Template. Save the search in your CarMax account to get email alerts."),
    ("Carvana search", "carvana", "https://www.carvana.com/cars",
     "Template. Carvana supports saved searches/alerts when signed in."),
    ("AutoTrader search", "autotrader",
     "https://www.autotrader.com/cars-for-sale/",
     "Template. Use 'Save search' on AutoTrader to receive email alerts, then import them here."),
    ("AutoTempest search", "autotempest",
     "https://www.autotempest.com/",
     "Meta-search across several sites. Results link out to the original listings."),
    ("KSL Cars search", "ksl", "https://cars.ksl.com/",
     "Template. KSL saved searches can send email alerts."),
    ("Facebook Marketplace search", "facebook",
     "https://www.facebook.com/marketplace/",
     "Manual only: Meta's terms prohibit automated collection. Copy details by hand."),
    ("Cars.com search", "cars_com",
     "https://www.cars.com/shopping/",
     "Template. Cars.com saved searches send email alerts."),
    ("CarGurus search", "cargurus", "https://www.cargurus.com/",
     "Template: choose your make and model on CarGurus and paste your saved-search URL here."),
    ("TrueCar search", "truecar", "https://www.truecar.com/used-cars-for-sale/listings/",
     "Template."),
]


def seed(conn: sqlite3.Connection) -> None:
    with conn:
        for key, name, kind, enabled in SOURCE_SEED:
            conn.execute(
                "INSERT OR IGNORE INTO sources(key, name, kind, enabled) VALUES (?, ?, ?, ?)",
                (key, name, kind, enabled),
            )
        if conn.execute("SELECT COUNT(*) FROM saved_searches").fetchone()[0] == 0:
            now = utcnow()
            for name, source_key, url, notes in SAVED_SEARCH_SEED:
                conn.execute(
                    "INSERT INTO saved_searches(name, source_key, url, notes, is_template, created_at)"
                    " VALUES (?, ?, ?, ?, 1, ?)",
                    (name, source_key, url, notes, now),
                )


# ---------------------------------------------------------------- preferences

def get_pref(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_pref(conn: sqlite3.Connection, key: str, value) -> None:
    with conn:
        conn.execute(
            "INSERT INTO preferences(key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


def load_settings(conn: sqlite3.Connection) -> dict:
    return config.merge_settings(get_pref(conn, "settings", {}))


def save_settings(conn: sqlite3.Connection, settings: dict) -> None:
    set_pref(conn, "settings", settings)
