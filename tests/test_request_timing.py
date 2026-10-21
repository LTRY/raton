"""Request timing: the log line and `Server-Timing` header that tell where a slow page spends its time."""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from back.core import request_timing
from back.core.request_timing import RequestTimingMiddleware, install_sql_timing

engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
install_sql_timing(engine)

app = FastAPI()
app.add_middleware(RequestTimingMiddleware)


@app.get("/two-queries")
def two_queries():
    with engine.connect() as conn:
        conn.execute(text("select 1"))
        conn.execute(text("select 2"))
    return {"ok": True}


def test_server_timing_header_counts_sql_statements():
    response = TestClient(app).get("/two-queries")

    assert response.status_code == 200
    assert '"2 requetes"' in response.headers["server-timing"]


def test_slow_request_is_logged_as_warning_with_sql_split(monkeypatch, caplog):
    monkeypatch.setattr(request_timing, "SLOW_REQUEST_SECONDS", 0.0)

    with caplog.at_level(logging.INFO, logger="raton.timing"):
        TestClient(app).get("/two-queries")

    assert any(
        r.levelno == logging.WARNING
        and "SLOW GET /two-queries" in r.getMessage()
        and "2 stmts" in r.getMessage()
        for r in caplog.records
    )
