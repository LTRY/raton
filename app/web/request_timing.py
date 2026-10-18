"""Where a request's time goes: one log line per request, a `Server-Timing` header, an event-loop lag probe.

A slow page has several possible causes (SQL, template rendering, a worker thread waiting for a free
slot, a starved CPU, a VM short of memory) and a page-level profile cannot tell them apart. Each
request therefore reports its total time next to the time spent inside SQL: a large gap means the
time went elsewhere (Python, threads, host), not in the queries.
"""

import asyncio
import logging
import os
import time
import uuid
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import log_event, request_id_var

logger = logging.getLogger("raton.timing")

SLOW_REQUEST_SECONDS = 1.0
LOOP_LAG_WARNING_SECONDS = 0.5
LOOP_PROBE_INTERVAL_SECONDS = 1.0

# Shared with the worker threads that run sync routes: anyio copies the context into them.
_current_sql: ContextVar[SqlTotals | None] = ContextVar("request_sql_totals", default=None)


class SqlTotals:
    __slots__ = ("count", "seconds")

    def __init__(self) -> None:
        self.count = 0
        self.seconds = 0.0


def install_sql_timing(engine: Engine) -> None:
    """Count the statements of the current request and the time the database took to answer them."""

    @event.listens_for(engine, "before_cursor_execute")
    def _start(conn, cursor, statement, parameters, context, executemany):
        conn.info["pt_query_start"] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _stop(conn, cursor, statement, parameters, context, executemany):
        totals = _current_sql.get()
        started = conn.info.pop("pt_query_start", None)
        if totals is not None and started is not None:
            totals.count += 1
            totals.seconds += time.perf_counter() - started


def process_snapshot() -> str:
    """Memory and load of the process and its host (the VM, in Docker), for the slow-request lines."""
    parts = []
    try:
        with open("/proc/self/status", encoding="utf-8") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    parts.append(f"rss={int(line.split()[1]) // 1024}MB")
                elif line.startswith("Threads:"):
                    parts.append(f"threads={line.split()[1]}")
    except OSError:
        pass
    try:
        parts.append("load=" + "/".join(f"{value:.1f}" for value in os.getloadavg()))
    except OSError:
        pass
    return " ".join(parts)


class RequestTimingMiddleware:
    """Pure ASGI (not `BaseHTTPMiddleware`): it must not change how streamed media responses are sent."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        totals = SqlTotals()
        token = _current_sql.set(totals)
        request_id = uuid.uuid4().hex[:12]
        id_token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 0

        async def send_with_timing(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                elapsed_ms = (time.perf_counter() - started) * 1000
                headers = list(message.get("headers", []))
                value = f'app;dur={elapsed_ms:.0f}, sql;dur={totals.seconds * 1000:.0f};desc="{totals.count} requetes"'
                headers.append((b"server-timing", value.encode()))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        except Exception as exc:
            # Starlette turns this into a bare 500 and uvicorn prints the trace on stderr only:
            # log it here so the durable journal has the failing request and its traceback.
            status = 500
            log_event(
                logger,
                "request.error",
                level=logging.ERROR,
                exc_info=True,
                method=scope.get("method"),
                path=scope.get("path", ""),
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        finally:
            _current_sql.reset(token)
            elapsed = time.perf_counter() - started
            path = scope.get("path", "")
            # Thumbnails come by the hundred per page and are served from disk: only worth a line when slow.
            quiet = path.startswith(("/static/", "/videos/")) and path.endswith(
                ("/thumbnail", ".css", ".js", ".woff2")
            )
            request_fields = {
                "event": "request",
                "method": scope.get("method"),
                "path": path,
                "status": status,
                "duration_ms": round(elapsed * 1000),
                "sql_count": totals.count,
                "sql_ms": round(totals.seconds * 1000),
            }
            if elapsed >= SLOW_REQUEST_SECONDS:
                logger.warning(
                    "SLOW %s %s -> %s %.0f ms (sql %d stmts, %.0f ms) %s",
                    scope.get("method"),
                    path,
                    status,
                    elapsed * 1000,
                    totals.count,
                    totals.seconds * 1000,
                    process_snapshot(),
                    extra={"fields": request_fields},
                )
            elif not quiet or status >= 400:
                logger.info(
                    "%s %s -> %s %.0f ms (sql %d stmts, %.0f ms)",
                    scope.get("method"),
                    path,
                    status,
                    elapsed * 1000,
                    totals.count,
                    totals.seconds * 1000,
                    extra={"fields": request_fields},
                )
            request_id_var.reset(id_token)


async def event_loop_lag_probe() -> None:
    """Warn when the event loop wakes up late: something blocked it, or the CPU was not ours."""
    while True:
        expected = time.perf_counter() + LOOP_PROBE_INTERVAL_SECONDS
        await asyncio.sleep(LOOP_PROBE_INTERVAL_SECONDS)
        lag = time.perf_counter() - expected
        if lag >= LOOP_LAG_WARNING_SECONDS:
            logger.warning("LOOP-LAG %.0f ms %s", lag * 1000, process_snapshot())
