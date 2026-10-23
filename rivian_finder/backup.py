"""Database backup/restore and portable JSON export."""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from . import config

KEEP_BACKUPS = 30
EXPORT_TABLES = ["sources", "runs", "source_runs", "vehicles", "listings", "observations", "change_events",
                 "vehicle_attributes", "user_overrides", "match_candidates", "merges", "saved_searches", "preferences",
                 "watchlist", "capture_queue"]


def backup_db(conn: sqlite3.Connection, directory: Path | None = None, label: str = "manual") -> Path:
    """Consistent online copy via SQLite's backup API."""
    directory = directory or config.BACKUP_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rivian_finder_{datetime.now():%Y%m%d_%H%M%S}_{label}.db"
    dest = sqlite3.connect(path)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    prune(directory)
    return path


def daily_backup(conn: sqlite3.Connection, directory: Path | None = None) -> Path | None:
    """Back up once per day before the first run of the day."""
    directory = directory or config.BACKUP_DIR
    today = datetime.now().strftime("%Y%m%d")
    if directory.exists() and any(directory.glob(f"rivian_finder_{today}_*_auto.db")):
        return None
    return backup_db(conn, directory, "auto")


def prune(directory: Path, keep: int = KEEP_BACKUPS) -> None:
    files = sorted(directory.glob("rivian_finder_*.db"))
    for old in files[:-keep]:
        old.unlink(missing_ok=True)


def list_backups(directory: Path | None = None) -> list[Path]:
    directory = directory or config.BACKUP_DIR
    return sorted(directory.glob("rivian_finder_*.db"), reverse=True) if directory.exists() else []


def restore_db(backup_path: Path, db_path: Path | None = None) -> Path:
    """Replace the live database with a backup. The current database is backed up first."""
    db_path = db_path or config.DB_PATH
    check = sqlite3.connect(backup_path)
    try:
        if check.execute("SELECT name FROM sqlite_master WHERE name='vehicles'").fetchone() is None:
            raise ValueError("that file is not a Truck Finder database")
    finally:
        check.close()
    if db_path.exists():
        live = sqlite3.connect(db_path)
        try:
            backup_db(live, db_path.parent / "backups", label="before_restore")
        finally:
            live.close()
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    shutil.copyfile(backup_path, db_path)
    return db_path


def export_json(conn: sqlite3.Connection) -> str:
    data = {"format": "rivian-finder-export", "version": 1, "exported_at": datetime.now().isoformat(timespec="seconds"),
            "tables": {}}
    for t in EXPORT_TABLES:
        data["tables"][t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]  # noqa: S608 - fixed table list
    return json.dumps(data, indent=1, default=str)


def import_json(conn: sqlite3.Connection, payload: str) -> dict:
    """Load a full JSON export into an EMPTY database (use restore/backup to replace an existing one)."""
    data = json.loads(payload)
    if data.get("format") != "rivian-finder-export":
        raise ValueError("not a Truck Finder JSON export")
    if conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]:
        raise ValueError("database is not empty; back it up and start a fresh data folder before importing")
    counts = {}
    conn.execute("PRAGMA foreign_keys = OFF")
    with conn:
        for t in EXPORT_TABLES:
            rows = data["tables"].get(t, [])
            if t in ("sources", "saved_searches", "preferences"):
                conn.execute(f"DELETE FROM {t}")  # noqa: S608
            for r in rows:
                cols = ",".join(r)
                conn.execute(f"INSERT OR REPLACE INTO {t} ({cols}) VALUES ({','.join('?' * len(r))})",  # noqa: S608
                             list(r.values()))
            counts[t] = len(rows)
    conn.execute("PRAGMA foreign_keys = ON")
    return counts
