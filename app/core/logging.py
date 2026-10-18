"""Application logging: a readable stderr stream plus a durable JSON-lines file.

The container is recreated on every deploy, so `docker compose logs` cannot answer "what happened
in the last 24 hours". The file lives on a mounted volume (spec: 13-jobs-logs-planification.md,
section "Journal applicatif"). One line = one JSON event, so a reviewer (human or LLM) can filter it.
"""

import contextlib
import functools
import inspect
import json
import logging
import re
import sys
import time
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

APP_LOGGER_NAME = "raton"
# Most modules log through `logging.getLogger(__name__)`, i.e. under "app.": both trees are the app's.
APP_LOGGER_TREES = (APP_LOGGER_NAME, "app")
# Third-party loggers whose warnings and errors explain failures (a crashed scheduler job, a worker error).
FILE_ONLY_LOGGERS = ("uvicorn.error", "apscheduler")

LOG_FILE_NAME = "app.jsonl"
LOG_BACKUP_DAYS = 7
MAX_FIELD_CHARS = 500

# Correlates every line written while one HTTP request is handled; set by RequestTimingMiddleware.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
    re.compile(r"pa-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)[\"']?\s*[:=]\s*[\"']?)[^\s\"',&]+"),
)

_installed: list[tuple[logging.Logger, logging.Handler]] = []
_saved_state: dict[str, tuple[int, bool]] = {}


def redact(text: str) -> str:
    """Mask API keys and credentials: a log line must be safe to paste into a review."""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: f"{m.group(1)}***", text)
        else:
            text = pattern.sub("***", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


def _event_fields(record: logging.LogRecord) -> dict[str, Any]:
    fields = getattr(record, "fields", None)
    return fields if isinstance(fields, dict) else {}


def _field_value(value: Any) -> Any:
    if isinstance(value, bool | int | float) or value is None:
        return value
    return redact(str(value))[:MAX_FIELD_CHARS]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created)
            .astimezone()
            .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in _event_fields(record).items():
            payload.setdefault(key, _field_value(value))
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields = _event_fields(record)
        if fields:
            line += " " + " ".join(f"{key}={_field_value(value)}" for key, value in fields.items())
        return redact(line) if record.exc_info else line


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """Log a named event with structured fields (`job.end`, `ext.call`...); fields land as JSON keys."""
    logger.log(level, event, exc_info=exc_info, extra={"fields": {"event": event, **fields}})


def _attach(logger: logging.Logger, handler: logging.Handler) -> None:
    logger.addHandler(handler)
    _installed.append((logger, handler))


def configure_app_logging(log_dir: Path | None = None) -> None:
    """Send the app's INFO logs to stderr and, when `log_dir` is set, to a daily-rotated JSON file.

    uvicorn only configures its own loggers: without this, anything the app logs below WARNING is dropped.
    """
    if _installed:
        return
    redacting = RedactingFilter()
    console = logging.StreamHandler()
    console.setFormatter(ConsoleFormatter())
    console.addFilter(redacting)

    file_handler: logging.Handler | None = None
    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = TimedRotatingFileHandler(
                log_dir / LOG_FILE_NAME,
                when="midnight",
                backupCount=LOG_BACKUP_DAYS,
                encoding="utf-8",
                delay=True,
            )
            file_handler.setFormatter(JsonFormatter())
            file_handler.addFilter(redacting)
        except OSError as exc:
            # Logging must never keep the app from starting: fall back on stderr alone.
            print(f"raton: log file disabled ({log_dir}): {exc}", file=sys.stderr)

    for name in APP_LOGGER_TREES:
        logger = logging.getLogger(name)
        _attach(logger, console)
        if file_handler is not None:
            _attach(logger, file_handler)
        _saved_state[name] = (logger.level, logger.propagate)
        logger.setLevel(logging.INFO)
        # uvicorn may or may not have set up the root logger; don't print twice.
        logger.propagate = False
    if file_handler is not None:
        for name in FILE_ONLY_LOGGERS:
            _attach(logging.getLogger(name), file_handler)


def shutdown_app_logging() -> None:
    """Detach and close the handlers installed by `configure_app_logging` (tests, clean shutdown)."""
    for logger, handler in _installed:
        logger.removeHandler(handler)
        handler.close()
    _installed.clear()
    for name, (level, propagate) in _saved_state.items():
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = propagate
    _saved_state.clear()


@contextlib.contextmanager
def log_external(
    logger: logging.Logger,
    service: str,
    op: str,
    *,
    expected_failure: Callable[[BaseException], bool] | None = None,
    **fields: Any,
) -> Iterator[None]:
    """Time a call to an outside service (yt-dlp, Anthropic, Voyage, ffmpeg) and log how it ended.

    Success is an INFO `ext.call`; a failure is an ERROR `ext.error` with the exception class,
    re-raised untouched. `expected_failure` downgrades the ones the app handles on purpose
    (a YouTube 429, a video not yet available) to WARNING.
    """
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        log_event(
            logger,
            "ext.error",
            level=logging.WARNING if expected_failure and expected_failure(exc) else logging.ERROR,
            service=service,
            op=op,
            duration_ms=round((time.perf_counter() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}",
            **fields,
        )
        raise
    log_event(
        logger,
        "ext.call",
        service=service,
        op=op,
        duration_ms=round((time.perf_counter() - started) * 1000),
        **fields,
    )


_JOB_ID_ARGS = ("job_id", "channel_id", "video_id", "playlist_id")


def logged_job(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a background or scheduled job: log its start, end (with duration) or crash.

    A job that never logs `job.start` on its day is how a review notices a scheduler that did not fire.
    """

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(fn)
        job_logger = logging.getLogger(f"{APP_LOGGER_NAME}.jobs")

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind_partial(*args, **kwargs).arguments
            ids = {key: bound[key] for key in _JOB_ID_ARGS if key in bound}
            started = time.perf_counter()
            log_event(job_logger, "job.start", job=name, **ids)
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                log_event(
                    job_logger,
                    "job.error",
                    level=logging.ERROR,
                    exc_info=True,
                    job=name,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    error=f"{type(exc).__name__}: {exc}",
                    **ids,
                )
                raise
            extra = {"result": json.dumps(result, default=str)} if isinstance(result, dict) else {}
            log_event(
                job_logger,
                "job.end",
                job=name,
                duration_ms=round((time.perf_counter() - started) * 1000),
                **ids,
                **extra,
            )
            return result

        return wrapper

    return decorate
