"""Restore and demo cleanup preserve the shopper's data when release workflows fail."""
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from conftest import listing, vin
from rivian_finder import attributes, backup, checklist, db, pipeline, services
from rivian_finder.sources.demo import demo_listings


def _database(path, marker):
    conn = db.connect(path)
    try:
        db.set_pref(conn, "restore_test", marker)
    finally:
        conn.close()


def _marker(path):
    conn = db.connect(path)
    try:
        return db.get_pref(conn, "restore_test")
    finally:
        conn.close()


@pytest.fixture
def frozen_backup_time(monkeypatch):
    class FrozenTime:
        @staticmethod
        def now():
            return datetime(2026, 10, 28, 12, 0, 0)
    monkeypatch.setattr(backup, "datetime", FrozenTime)


@pytest.mark.parametrize("label", ["manual", "auto", "before_restore"])
def test_same_second_backups_never_overwrite_and_keep_sort_and_daily_globs(conn, tmp_path, frozen_backup_time, label):
    paths = []
    for marker in range(3):
        db.set_pref(conn, "restore_test", marker)
        paths.append(backup.backup_db(conn, tmp_path, label))
    assert len(set(paths)) == 3
    assert [_marker(path) for path in paths] == [0, 1, 2]
    assert backup.list_backups(tmp_path) == paths[::-1]
    assert len(list(tmp_path.glob(f"rivian_finder_20261028_*_{label}.db"))) == 3
    if label == "auto":
        assert backup.daily_backup(conn, tmp_path) is None


def test_restore_same_second_safety_backup_preserves_selected_source(tmp_path, frozen_backup_time):
    live = tmp_path / "live.db"
    _database(live, "current workspace")
    directory = tmp_path / "backups"
    selected_conn = db.connect(":memory:")
    try:
        db.set_pref(selected_conn, "restore_test", "selected backup")
        source = backup.backup_db(selected_conn, directory, "before_restore")
    finally:
        selected_conn.close()
    original_source = source.read_bytes()
    backup.restore_db(source, live)
    assert source.read_bytes() == original_source
    assert _marker(live) == "selected backup"
    safety = [path for path in directory.glob("*_before_restore.db") if path != source]
    assert len(safety) == 1 and _marker(safety[0]) == "current workspace"
    assert backup.list_backups(directory) == [safety[0], source]


def test_failed_backup_removes_only_its_incomplete_copy(conn, tmp_path, frozen_backup_time):
    source = backup.backup_db(conn, tmp_path)
    original_source = source.read_bytes()

    class FailedConnection:
        def backup(self, destination):
            destination.execute("CREATE TABLE partial_copy(id INTEGER)")
            destination.commit()
            raise OSError("backup failed")

    with pytest.raises(OSError, match="backup failed"):
        backup.backup_db(FailedConnection(), tmp_path)
    assert source.read_bytes() == original_source
    assert backup.list_backups(tmp_path) == [source]


def test_restore_oldest_of_thirty_backups_preserves_source_and_safety_copy(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    source = directory / "rivian_finder_20000101_000000_manual.db"
    _database(source, "selected backup")
    original_source = source.read_bytes()
    for index in range(1, backup.KEEP_BACKUPS):
        shutil.copyfile(source, directory / f"rivian_finder_20000101_0000{index:02d}_manual.db")
    live = tmp_path / "live.db"
    _database(live, "current workspace")

    assert backup.restore_db(source, live) == live
    assert source.read_bytes() == original_source
    assert _marker(live) == "selected backup"
    safety = list(directory.glob("*_before_restore.db"))
    assert len(safety) == 1 and _marker(safety[0]) == "current workspace"
    assert len(list(directory.glob("*.db"))) == backup.KEEP_BACKUPS
    assert not list(tmp_path.glob(".restore-*.db"))


@pytest.mark.parametrize("failure_step", ["copy", "safety_backup", "replace"])
def test_restore_failure_leaves_live_database_and_selected_source_intact(tmp_path, monkeypatch, failure_step):
    source, live = tmp_path / "selected.db", tmp_path / "live.db"
    _database(source, "selected backup")
    _database(live, "current workspace")
    original_source, original_live = source.read_bytes(), live.read_bytes()

    def fail_copy(src, dest):
        Path(dest).write_bytes(b"partial copy")
        raise OSError("copy failed")

    def fail_backup(*args, **kwargs):
        raise OSError("safety backup failed")

    replace = Path.replace

    def fail_replace(path, target):
        if path.name.startswith(".restore-"):
            raise OSError("replace failed")
        return replace(path, target)

    if failure_step == "copy":
        monkeypatch.setattr(backup.shutil, "copyfile", fail_copy)
    elif failure_step == "safety_backup":
        monkeypatch.setattr(backup, "backup_db", fail_backup)
    else:
        monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError):
        backup.restore_db(source, live)
    assert source.read_bytes() == original_source
    assert live.read_bytes() == original_live
    assert _marker(live) == "current workspace"
    assert not list(tmp_path.glob(".restore-*.db"))
    if failure_step == "replace":
        safety = list((tmp_path / "backups").glob("*_before_restore.db"))
        assert len(safety) == 1 and _marker(safety[0]) == "current workspace"


def test_purge_demo_removes_shopping_records_and_preserves_real_inventory_history(conn):
    demo = pipeline.import_listings(conn, demo_listings(1, include_general=True), "demo_import")
    real = pipeline.import_listings(conn, [listing(vin=vin(990), make="Toyota", model="Camry")], "manual_entry")
    demo_id, real_id = demo["vehicle_ids"][0], real["vehicle_ids"][0]
    for vehicle_id in (demo_id, real_id):
        checklist.save(conn, vehicle_id, {"tires": ("problem", "Inspection notes")})
        checklist.add_contact(conn, vehicle_id, "email", "Example seller", "Requested an itemized quote")
        services.toggle_favorite(conn, vehicle_id, True)
        attributes.set_override(conn, vehicle_id, "tonneau", "no", "Checked")
    tables = ("vehicles", "listings", "vehicle_attributes", "user_overrides", "watchlist", "checklist",
              "contacts", "change_events")

    def real_records():
        return {table: [dict(row) for row in conn.execute(
            f"SELECT * FROM {table} WHERE {'id' if table == 'vehicles' else 'vehicle_id'}=? ORDER BY rowid", (real_id,))]
                for table in tables}

    before = real_records()
    listing_id = real["listing_ids"][0]
    observations = [dict(row) for row in conn.execute("SELECT * FROM observations WHERE listing_id=?", (listing_id,))]
    expected_count = conn.execute("SELECT COUNT(*) FROM vehicles WHERE is_demo=1").fetchone()[0]
    assert services.purge_demo(conn) == expected_count
    assert conn.execute("SELECT COUNT(*) FROM vehicles WHERE is_demo=1").fetchone()[0] == 0
    assert real_records() == before
    assert observations == [dict(row) for row in conn.execute("SELECT * FROM observations WHERE listing_id=?", (listing_id,))]
    assert conn.execute("SELECT COUNT(*) FROM checklist").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 1
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    assert services.purge_demo(conn) == 0
