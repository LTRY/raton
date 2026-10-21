from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from back.core.config import Settings
from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.services.jobs import scheduler as scheduler_module
from back.services.jobs.scheduler import (
    get_last_auto_scan_info,
    get_last_media_purge_at,
    record_media_purge,
    record_scan_result,
    scan_is_overdue,
)


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_scan_is_overdue_when_never_scanned():
    assert scan_is_overdue(None) is True


def test_scan_is_overdue_false_for_recent_scan():
    now = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    last_scan_at = now - timedelta(hours=2)

    assert scan_is_overdue(last_scan_at, now=now) is False


def test_scan_is_overdue_true_after_stale_threshold():
    now = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    last_scan_at = now - timedelta(hours=25)

    assert scan_is_overdue(last_scan_at, now=now) is True


def test_scan_is_overdue_respects_custom_stale_after():
    now = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    last_scan_at = now - timedelta(hours=2)

    assert scan_is_overdue(last_scan_at, now=now, stale_after=timedelta(hours=1)) is True


def test_get_last_auto_scan_info_defaults_when_never_recorded():
    db = make_session()

    info = get_last_auto_scan_info(db)

    assert info == {"at": None, "status": None, "imported": 0}


def test_record_scan_result_roundtrips_completed_status():
    db = make_session()

    record_scan_result(db, {"status": "completed", "downloaded": 7, "deleted": 0})
    info = get_last_auto_scan_info(db)

    assert info["status"] == "completed"
    assert info["imported"] == 7
    assert info["at"] is not None
    assert info["at"].tzinfo is not None


def test_record_scan_result_roundtrips_storage_low_status():
    db = make_session()

    record_scan_result(db, {"status": "storage_low", "downloaded": 0, "deleted": 0})
    info = get_last_auto_scan_info(db)

    assert info["status"] == "storage_low"
    assert info["imported"] == 0


def test_record_scan_result_overwrites_previous_recording():
    db = make_session()

    record_scan_result(db, {"status": "already_running", "downloaded": 0, "deleted": 0})
    record_scan_result(db, {"status": "completed", "downloaded": 3, "deleted": 0})
    info = get_last_auto_scan_info(db)

    assert info["status"] == "completed"
    assert info["imported"] == 3


def test_media_purge_record_round_trip():
    db = make_session()
    assert get_last_media_purge_at(db) is None

    now = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
    record_media_purge(db, now)

    assert get_last_media_purge_at(db) == now


def test_start_scheduler_does_nothing_when_disabled(monkeypatch):
    monkeypatch.setattr(
        scheduler_module, "get_settings", lambda: Settings(APP_SCHEDULER_ENABLED=False)
    )
    monkeypatch.setattr(
        scheduler_module.scheduler, "add_job", lambda *a, **k: pytest.fail("job registered")
    )

    scheduler_module.start_scheduler()

    assert scheduler_module.scheduler.running is False
