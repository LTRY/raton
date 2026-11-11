"""Startup marks the jobs a restart cut short as failed, so no page polls them forever."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.job import DownloadJob
from back.models.llm_job import LlmJob
from back.services.jobs.interrupted import INTERRUPTED_MESSAGE, fail_interrupted_jobs
from back.services.rag.auto_notes import AUTO_NOTES_KIND


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def llm_job(kind: str, status: str) -> LlmJob:
    return LlmJob(kind=kind, provider="anthropic", prompt="{}", status=status)


def test_unfinished_jobs_fail_and_finished_ones_are_left_alone():
    db = make_session()
    downloads = {
        status: DownloadJob(status=status, message=f"message {status}")
        for status in ("queued", "running", "downloaded", "failed", "played")
    }
    llm = {status: llm_job("generate", status) for status in ("queued", "running", "done")}
    db.add_all([*downloads.values(), *llm.values()])
    db.commit()

    assert fail_interrupted_jobs(db) == (2, 2)

    db.expire_all()
    for status in ("queued", "running"):
        assert downloads[status].status == "failed"
        assert downloads[status].message == INTERRUPTED_MESSAGE
        assert llm[status].status == "failed"
        assert llm[status].error == INTERRUPTED_MESSAGE
        assert llm[status].completed_at is not None
    assert downloads["downloaded"].message == "message downloaded"
    assert downloads["failed"].message == "message failed"
    assert downloads["played"].status == "played"
    assert llm["done"].status == "done"


def test_a_running_auto_notes_batch_survives_the_restart():
    db = make_session()
    batch = llm_job(AUTO_NOTES_KIND, "running")
    db.add(batch)
    db.commit()

    assert fail_interrupted_jobs(db) == (0, 0)

    db.expire_all()
    assert batch.status == "running"
    assert batch.error is None
