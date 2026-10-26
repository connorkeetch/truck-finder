"""Cloud scheduling never fetches on startup or catches up missed searches."""
from datetime import datetime, timezone
import threading
from zoneinfo import ZoneInfo

import pytest

from rivian_finder import cloud, db, services


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def save_schedule(conn, enabled=True, times=None):
    settings = db.load_settings(conn)
    settings["alerts"] = {"enabled": enabled, "times": times or ["08:00"]}
    db.save_settings(conn, settings)


def test_next_run_is_future_in_saved_timezone_and_deduplicates_times():
    tz = ZoneInfo("America/Denver")
    assert cloud.next_run(utc("2026-10-25T13:59:00"), ["08:00", "08:00", "15:00"], tz) == utc("2026-10-25T14:00:00")
    assert cloud.next_run(utc("2026-10-25T14:00:00"), ["08:00"], tz) == utc("2026-10-26T14:00:00")


def test_dst_skips_nonexistent_time_and_does_not_repeat_fall_back_hour():
    tz = ZoneInfo("America/Denver")
    assert cloud.next_run(utc("2026-03-08T07:00:00"), ["02:30"], tz) == utc("2026-03-09T08:30:00")
    assert cloud.next_run(utc("2026-11-01T07:31:00"), ["01:30"], tz) == utc("2026-11-02T08:30:00")


@pytest.mark.parametrize("times", [[], ["24:00"], ["8:00"], [None], "08:00"])
def test_invalid_schedule_is_rejected(times):
    with pytest.raises(ValueError):
        cloud._times(times)


def test_scheduler_waits_for_future_time_runs_once_and_honors_disable(conn):
    save_schedule(conn)
    now, calls = [utc("2026-10-25T14:00:00")], []
    scheduler = cloud.Scheduler(conn, clock=lambda: now[0], run_search=lambda c: calls.append(c), tz=ZoneInfo("America/Denver"))
    scheduler.tick()
    assert not calls and scheduler.next_due == utc("2026-10-26T14:00:00")
    now[0] = utc("2026-10-26T14:00:10")
    scheduler.tick()
    scheduler.tick()
    assert calls == [conn]
    save_schedule(conn, enabled=False)
    scheduler.tick()
    now[0] = utc("2026-10-27T14:00:10")
    scheduler.tick()
    assert len(calls) == 1 and scheduler.next_due is None


def test_saved_changes_and_missed_minutes_never_catch_up(conn):
    save_schedule(conn)
    now, calls = [utc("2026-10-25T13:59:00")], []
    scheduler = cloud.Scheduler(conn, clock=lambda: now[0], run_search=lambda c: calls.append(c), tz=ZoneInfo("America/Denver"))
    scheduler.tick()
    now[0] = utc("2026-10-25T14:02:00")
    scheduler.tick()
    assert not calls and scheduler.next_due == utc("2026-10-26T14:00:00")
    save_schedule(conn, times=["07:00", "15:00"])
    scheduler.tick()
    assert not calls and scheduler.next_due == utc("2026-10-25T21:00:00")


def test_long_search_skips_times_that_passed_while_running(conn):
    save_schedule(conn, times=["08:00", "08:01"])
    now, calls = [utc("2026-10-25T13:59:00")], []

    def run(c):
        calls.append(c)
        now[0] = utc("2026-10-25T14:05:00")

    scheduler = cloud.Scheduler(conn, clock=lambda: now[0], run_search=run, tz=ZoneInfo("America/Denver"))
    scheduler.tick()
    now[0] = utc("2026-10-25T14:00:01")
    scheduler.tick()
    scheduler.tick()
    assert calls == [conn] and scheduler.next_due == utc("2026-10-26T14:00:00")


def test_scheduled_search_rechecks_enable_flag_and_budget_without_notifications(conn, monkeypatch):
    save_schedule(conn)
    calls = []
    monkeypatch.setattr(cloud.cli, "budget_ok_sources", lambda c, s: (["autodev"], ["marketcheck budget"]))
    monkeypatch.setattr(services, "run_sources", lambda c, keys, settings: calls.append(keys) or {"status": "success"})
    cloud._scheduled_search(conn)
    assert calls == [["autodev"]]
    monkeypatch.setattr(cloud.cli, "budget_ok_sources", lambda c, s: ([], ["budget"]))
    cloud._scheduled_search(conn)
    save_schedule(conn, enabled=False)
    monkeypatch.setattr(cloud.cli, "budget_ok_sources", lambda *args: pytest.fail("Disabled schedules cannot check/run connectors"))
    cloud._scheduled_search(conn)
    assert len(calls) == 1


def test_manual_refreshes_share_the_scheduler_lock(monkeypatch):
    first_entered, release_first, second_entered = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def run(conn, keys, settings, brands):
        calls.append(conn)
        if conn == "first":
            first_entered.set()
            assert release_first.wait(2)
        else:
            second_entered.set()
        return {"status": "success"}

    monkeypatch.setattr(services, "_run_sources", run)
    first = threading.Thread(target=services.run_sources, args=("first",))
    second = threading.Thread(target=services.run_sources, args=("second",))
    first.start()
    assert first_entered.wait(2)
    second.start()
    assert not second_entered.wait(.05)
    release_first.set()
    first.join(2)
    second.join(2)
    assert calls == ["first", "second"] and second_entered.is_set()


def test_local_runtime_never_starts_scheduler(monkeypatch):
    monkeypatch.delenv("RIVIAN_FINDER_CLOUD", raising=False)
    monkeypatch.setattr(cloud.db, "connect", lambda: pytest.fail("Local mode must not open the scheduler database"))
    assert cloud.start_scheduler() is None


def test_failed_search_advances_to_next_future_time(conn):
    save_schedule(conn)
    now = [utc("2026-10-25T13:59:00")]

    def fail(c):
        raise RuntimeError("provider unavailable")

    scheduler = cloud.Scheduler(conn, clock=lambda: now[0], run_search=fail, tz=ZoneInfo("America/Denver"))
    scheduler.tick()
    now[0] = utc("2026-10-25T14:00:01")
    with pytest.raises(RuntimeError):
        scheduler.tick()
    assert scheduler.next_due == utc("2026-10-26T14:00:00")
    scheduler.tick()


def test_streamlit_stays_in_process_and_binds_only_loopback(monkeypatch):
    from streamlit.web import cli as streamlit_cli

    arguments = []
    previous = cloud.sys.argv
    monkeypatch.setattr(streamlit_cli, "main", lambda: arguments.extend(cloud.sys.argv))
    cloud._run_streamlit()
    assert arguments[:2] == ["streamlit", "run"]
    assert "--server.address=127.0.0.1" in arguments and "--server.port=8501" in arguments
    assert "--server.headless=true" in arguments and cloud.sys.argv is previous


def test_main_stops_scheduler_even_when_streamlit_exits(conn, monkeypatch):
    monkeypatch.setenv("RIVIAN_FINDER_CLOUD", "1")
    closed = []
    monkeypatch.setattr(cloud.db, "connect", lambda: type("Connection", (), {"close": lambda self: closed.append(True)})())
    stops = []
    monkeypatch.setattr(cloud, "start_scheduler", lambda stop: stops.append(stop))
    monkeypatch.setattr(cloud, "_run_streamlit", lambda: (_ for _ in ()).throw(SystemExit(0)))
    with pytest.raises(SystemExit):
        cloud.main()
    assert closed == [True] and stops[0].is_set()
