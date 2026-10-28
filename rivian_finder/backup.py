"""Database backup/restore and portable JSON export."""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from . import config

KEEP_BACKUPS = 30
EXPORT_TABLES = ["sources", "runs", "source_runs", "vehicles", "listings", "observations", "change_events",
                 "vehicle_attributes", "user_overrides", "match_candidates", "merges", "saved_searches", "preferences",
                 "watchlist", "capture_queue", "api_usage", "recalls", "checklist", "contacts", "link_checks",
                 "email_inbox"]


def backup_db(conn: sqlite3.Connection, directory: Path | None = None, label: str = "manual",
              *, preserve: Path | None = None) -> Path:
    """Consistent online copy via SQLite's backup API."""
    directory = directory or config.BACKUP_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    collision = 0
    while True:
        # ~ sorts repeated backups after legacy whole-second filenames.
        suffix = f"~{collision:06d}" if collision else ""
        path = directory / f"rivian_finder_{stamp}{suffix}_{label}.db"
        try:
            path.touch(exist_ok=False)
            break
        except FileExistsError:
            collision += 1
    try:
        dest = sqlite3.connect(path)
        try:
            conn.backup(dest)
        finally:
            dest.close()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    prune(directory, preserve=(path,) + ((preserve,) if preserve is not None else ()))
    return path


def daily_backup(conn: sqlite3.Connection, directory: Path | None = None) -> Path | None:
    """Back up once per day before the first run of the day."""
    directory = directory or config.BACKUP_DIR
    today = datetime.now().strftime("%Y%m%d")
    if directory.exists() and any(directory.glob(f"rivian_finder_{today}_*_auto.db")):
        return None
    return backup_db(conn, directory, "auto")


def prune(directory: Path, keep: int = KEEP_BACKUPS, *, preserve: tuple[Path, ...] = ()) -> None:
    files = sorted(directory.glob("rivian_finder_*.db"))
    protected = {path.resolve() for path in preserve}
    candidates = [path for path in files if path.resolve() not in protected]
    for old in candidates[:max(0, len(files) - keep)]:
        old.unlink(missing_ok=True)


def list_backups(directory: Path | None = None) -> list[Path]:
    directory = directory or config.BACKUP_DIR
    return sorted(directory.glob("rivian_finder_*.db"), reverse=True) if directory.exists() else []


def restore_db(backup_path: Path, db_path: Path | None = None) -> Path:
    """Restore with other database connections closed; save the current database first."""
    db_path = db_path or config.DB_PATH
    check = sqlite3.connect(backup_path)
    try:
        if check.execute("SELECT name FROM sqlite_master WHERE name='vehicles'").fetchone() is None:
            raise ValueError("that file is not a MotorSift database")
    finally:
        check.close()
    with NamedTemporaryFile(dir=db_path.parent, prefix=".restore-", suffix=".db", delete=False) as temporary:
        staged = Path(temporary.name)
    try:
        shutil.copyfile(backup_path, staged)
        if db_path.exists():
            live = sqlite3.connect(db_path)
            try:
                backup_db(live, db_path.parent / "backups", label="before_restore", preserve=backup_path)
            finally:
                live.close()
        for suffix in ("-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        staged.replace(db_path)
    finally:
        staged.unlink(missing_ok=True)
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
        raise ValueError("not a MotorSift JSON export")
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
