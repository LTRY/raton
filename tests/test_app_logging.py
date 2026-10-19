"""Application journal: JSON-lines file, secret masking, request ids, job and external-call events."""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import (
    LOG_FILE_NAME,
    configure_app_logging,
    log_event,
    log_external,
    logged_job,
    redact,
    shutdown_app_logging,
)
from app.web.request_timing import RequestTimingMiddleware


@pytest.fixture
def log_dir(tmp_path):
    shutdown_app_logging()
    configure_app_logging(tmp_path)
    yield tmp_path
    shutdown_app_logging()


def read_lines(log_dir):
    for handler in logging.getLogger("raton").handlers:
        handler.flush()
    return [json.loads(line) for line in (log_dir / LOG_FILE_NAME).read_text().splitlines()]


def test_module_loggers_reach_the_json_file(log_dir):
    # Most modules use getLogger(__name__), i.e. the "app." tree, not "raton".
    logging.getLogger("app.services.channels.scanner").info("scan started")
    log_event(logging.getLogger("raton.llm"), "llm.call", model="m", tokens=12)

    first, second = read_lines(log_dir)
    assert first["msg"] == "scan started"
    assert first["level"] == "INFO"
    assert first["logger"] == "app.services.channels.scanner"
    assert first["ts"][:4].isdigit()
    assert second["event"] == "llm.call"
    assert second["tokens"] == 12


def test_exception_is_logged_with_its_traceback(log_dir):
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("app.x").exception("failed")

    (line,) = read_lines(log_dir)
    assert line["level"] == "ERROR"
    assert "ValueError: boom" in line["exc"]


def test_secrets_are_masked_in_message_fields_and_traceback(log_dir):
    logger = logging.getLogger("app.x")
    logger.info("calling with key sk-ant-api03-SECRET123")
    log_event(logger, "ext.call", header="Authorization: Bearer abc.def-ghi")
    try:
        raise RuntimeError("api_key=hunter2")
    except RuntimeError:
        logger.exception("failed")

    text = (log_dir / LOG_FILE_NAME).read_text()
    for secret in ("SECRET123", "abc.def-ghi", "hunter2"):
        assert secret not in text


def test_redact_keeps_ordinary_text():
    assert redact("GET /videos/3 -> 200") == "GET /videos/3 -> 200"


def test_unwritable_log_dir_does_not_stop_the_app(tmp_path):
    shutdown_app_logging()
    blocker = tmp_path / "file"
    blocker.write_text("x")
    try:
        configure_app_logging(blocker / "logs")  # a path under a regular file cannot be created
        logging.getLogger("app.x").info("still works")
    finally:
        shutdown_app_logging()


def test_logged_job_records_start_end_and_ids(log_dir):
    @logged_job("demo")
    def run(job_id: int, channel_id: int | None = None):
        return {"downloaded": 2}

    run(7, channel_id=3)

    start, end = read_lines(log_dir)
    assert (start["event"], start["job"], start["job_id"], start["channel_id"]) == (
        "job.start",
        "demo",
        7,
        3,
    )
    assert end["event"] == "job.end"
    assert end["duration_ms"] >= 0
    assert json.loads(end["result"]) == {"downloaded": 2}


def test_logged_job_records_a_crash_and_reraises(log_dir):
    @logged_job("demo")
    def run():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        run()

    _, error = read_lines(log_dir)
    assert error["event"] == "job.error"
    assert error["level"] == "ERROR"
    assert "RuntimeError: nope" in error["error"]
    assert "Traceback" in error["exc"]


def test_log_external_records_success_and_failure(log_dir):
    logger = logging.getLogger("app.services.youtube.yt")
    with log_external(logger, "yt-dlp", "extract", url="u"):
        pass
    with pytest.raises(OSError), log_external(logger, "yt-dlp", "extract", url="u"):
        raise OSError("HTTP Error 429")

    ok, failed = read_lines(log_dir)
    assert (ok["event"], ok["service"], ok["op"]) == ("ext.call", "yt-dlp", "extract")
    assert failed["event"] == "ext.error"
    assert "429" in failed["error"]


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestTimingMiddleware)

    @app.get("/ok")
    def ok():
        logging.getLogger("app.x").info("inside handler")
        return {"ok": True}

    @app.get("/crash")
    def crash():
        raise RuntimeError("handler exploded")

    return app


def test_request_gets_an_id_shared_by_its_lines(log_dir):
    response = TestClient(build_app()).get("/ok")

    request_id = response.headers["x-request-id"]
    inside, summary = read_lines(log_dir)
    assert inside["request_id"] == summary["request_id"] == request_id
    assert (summary["method"], summary["path"], summary["status"]) == ("GET", "/ok", 200)
    assert "sql_count" in summary


def test_unhandled_exception_is_logged_with_its_request(log_dir):
    client = TestClient(build_app(), raise_server_exceptions=False)

    assert client.get("/crash").status_code == 500

    error = next(line for line in read_lines(log_dir) if line.get("event") == "request.error")
    assert error["level"] == "ERROR"
    assert error["path"] == "/crash"
    assert "handler exploded" in error["exc"]
