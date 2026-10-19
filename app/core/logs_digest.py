"""Digest of the application journal (`app.jsonl`): what a reviewer reads before opening the raw file.

Standard library only, so it also runs on the host without the app's dependencies:
`python -m app.core.logs_digest --dir .local/logs --hours 24`. The journal's format and events
are described in docs/spec/13-jobs-logs-planification.md ("Journal applicatif").
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

LOG_FILE_NAME = "app.jsonl"
# Jobs that must start once a day; keep in step with app/services/jobs/scheduler.py.
EXPECTED_DAILY_JOBS = ("scheduled_scan", "scheduled_media_purge", "scheduled_auto_notes")
# A job still running this recently is not "never finished": it may just be long.
UNFINISHED_AFTER = timedelta(minutes=30)
SLOWEST_COUNT = 5
SAMPLE_CHARS = 300


@dataclass
class IssueGroup:
    signature: str
    level: str
    count: int = 0
    first_ts: str = ""
    last_ts: str = ""
    sample: str = ""
    request_id: str | None = None


@dataclass
class ExternalStats:
    service: str
    op: str
    calls: int = 0
    errors: int = 0
    total_ms: int = 0
    max_ms: int = 0

    @property
    def average_ms(self) -> int:
        return self.total_ms // self.calls if self.calls else 0


@dataclass
class Digest:
    hours: int
    now: datetime
    total: int = 0
    counts_by_level: Counter = field(default_factory=Counter)
    restarts: int = 0
    requests: int = 0
    server_errors: list[tuple[str, int]] = field(default_factory=list)
    slowest: list[tuple[str, int, int]] = field(default_factory=list)  # route, max ms, calls
    error_groups: list[IssueGroup] = field(default_factory=list)
    warning_groups: list[IssueGroup] = field(default_factory=list)
    external: list[ExternalStats] = field(default_factory=list)
    jobs: dict[str, tuple[int, int, int]] = field(
        default_factory=dict
    )  # name -> started, ended, failed
    failed_records: int = 0
    signals: list[str] = field(default_factory=list)


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except TypeError, ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def load_events(directory: Path, since: datetime) -> tuple[list[dict], int]:
    """Read the current and rotated journal files; keep the lines newer than `since`."""
    events: list[dict] = []
    malformed = 0
    for path in sorted(directory.glob(f"{LOG_FILE_NAME}*")):
        with path.open(encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                if not raw.strip():
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                stamp = _parse_ts(event.get("ts", "")) if isinstance(event, dict) else None
                if stamp is None:
                    malformed += 1
                elif stamp >= since:
                    events.append(event)
    events.sort(key=lambda e: e["ts"])
    return events, malformed


def _signature(event: dict) -> str:
    what = event.get("error") or event.get("msg") or ""
    where = " ".join(str(event[k]) for k in ("job", "service", "op", "path") if event.get(k))
    return f"{event.get('event') or event.get('logger', '')} {where}: {re.sub(r'\d+', 'N', str(what))}".strip()


def _group(events: list[dict]) -> list[IssueGroup]:
    groups: dict[str, IssueGroup] = {}
    for event in events:
        key = _signature(event)
        group = groups.setdefault(key, IssueGroup(signature=key, level=event.get("level", "")))
        group.count += 1
        group.first_ts = group.first_ts or event["ts"]
        group.last_ts = event["ts"]
        group.sample = str(event.get("exc") or event.get("error") or event.get("msg", ""))[
            -SAMPLE_CHARS:
        ]
        group.request_id = event.get("request_id") or group.request_id
    return sorted(groups.values(), key=lambda g: -g.count)


def build_digest(events: list[dict], *, now: datetime, hours: int) -> Digest:
    digest = Digest(hours=hours, now=now, total=len(events))
    digest.counts_by_level = Counter(e.get("level", "?") for e in events)
    digest.restarts = sum(e.get("event") == "app.started" for e in events)

    route_stats: dict[str, list[int]] = defaultdict(list)
    server_errors: Counter = Counter()
    for event in events:
        if event.get("event") != "request":
            continue
        digest.requests += 1
        route = f"{event.get('method')} {event.get('path')}"
        route_stats[route].append(int(event.get("duration_ms") or 0))
        if int(event.get("status") or 0) >= 500:
            server_errors[route] += 1
    digest.server_errors = server_errors.most_common()
    digest.slowest = sorted(
        ((route, max(times), len(times)) for route, times in route_stats.items()),
        key=lambda r: -r[1],
    )[:SLOWEST_COUNT]

    digest.error_groups = _group([e for e in events if e.get("level") in ("ERROR", "CRITICAL")])
    digest.warning_groups = _group([e for e in events if e.get("level") == "WARNING"])

    external: dict[tuple[str, str], ExternalStats] = {}
    for event in events:
        if event.get("event") not in ("ext.call", "ext.error"):
            continue
        key = (str(event.get("service")), str(event.get("op")))
        stats = external.setdefault(key, ExternalStats(*key))
        if event["event"] == "ext.error":
            stats.errors += 1
        else:
            duration = int(event.get("duration_ms") or 0)
            stats.calls += 1
            stats.total_ms += duration
            stats.max_ms = max(stats.max_ms, duration)
    digest.external = sorted(external.values(), key=lambda s: (s.service, s.op))

    started: Counter = Counter()
    ended: Counter = Counter()
    failed: Counter = Counter()
    last_start: dict[str, datetime] = {}
    scheduler_disabled = False
    for event in events:
        kind, job = event.get("event"), event.get("job")
        if kind == "scheduler.disabled":
            scheduler_disabled = True
        elif kind == "job.start":
            started[job] += 1
            last_start[job] = _parse_ts(event["ts"])
        elif kind == "job.end":
            ended[job] += 1
        elif kind == "job.error":
            failed[job] += 1
        elif kind == "job.record" and event.get("status") == "failed":
            digest.failed_records += 1
    digest.jobs = {name: (started[name], ended[name], failed[name]) for name in sorted(started)}

    _add_signals(digest, started, ended, failed, last_start, scheduler_disabled)
    return digest


def _add_signals(
    digest: Digest,
    started: Counter,
    ended: Counter,
    failed: Counter,
    last_start: dict[str, datetime],
    scheduler_disabled: bool,
) -> None:
    signals = digest.signals
    error_count = sum(g.count for g in digest.error_groups)
    if error_count:
        signals.append(
            f"{error_count} erreurs en {len(digest.error_groups)} groupe(s) (voir ci-dessous)"
        )
    server_error_count = sum(count for _, count in digest.server_errors)
    if server_error_count:
        signals.append(f"{server_error_count} réponse(s) 5xx")
    if digest.restarts > 1:
        signals.append(f"{digest.restarts} démarrages de l'application (redémarrages ou crashs)")
    if digest.failed_records:
        signals.append(
            f"{digest.failed_records} ligne(s) « Échec » dans la page Logs (download_jobs)"
        )
    if digest.hours >= 24 and not scheduler_disabled:
        for job in EXPECTED_DAILY_JOBS:
            if not started[job]:
                signals.append(f"Le job planifié {job} n'a pas tourné sur la période")
    for job, count in started.items():
        if count > ended[job] + failed[job] and digest.now - last_start[job] > UNFINISHED_AFTER:
            signals.append(
                f"Le job {job} a démarré mais n'est jamais terminé (ni job.end ni job.error)"
            )


def render_digest(digest: Digest) -> str:
    lines = [
        f"# Journal applicatif — {digest.hours} dernières heures (jusqu'à {digest.now.isoformat(timespec='seconds')})",
        "",
        f"{digest.total} lignes — "
        + ", ".join(f"{level} {count}" for level, count in sorted(digest.counts_by_level.items()))
        + f" — {digest.requests} requêtes — {digest.restarts} démarrage(s) de l'application",
        "",
        "## Signaux",
        "",
    ]
    lines += [f"- {s}" for s in digest.signals] or [
        "Aucun signal : la période ressemble à un fonctionnement nominal."
    ]

    for title, groups in (
        ("Erreurs", digest.error_groups),
        ("Avertissements", digest.warning_groups),
    ):
        if groups:
            lines += ["", f"## {title}", ""]
            for g in groups:
                rid = f" (request_id {g.request_id})" if g.request_id else ""
                lines += [
                    f"- ×{g.count} `{g.signature}` de {g.first_ts} à {g.last_ts}{rid}",
                    f"  > {g.sample}",
                ]

    if digest.server_errors:
        lines += ["", "## Réponses 5xx", ""] + [
            f"- {route} ×{count}" for route, count in digest.server_errors
        ]
    if digest.slowest:
        lines += ["", "## Requêtes les plus lentes (max)", ""]
        lines += [f"- {route}: {ms} ms ({calls} appel(s))" for route, ms, calls in digest.slowest]
    if digest.jobs:
        lines += ["", "## Jobs (démarrés / terminés / en erreur)", ""]
        lines += [f"- {name}: {s} / {e} / {f}" for name, (s, e, f) in digest.jobs.items()]
    if digest.external:
        lines += ["", "## Appels externes", ""]
        for stats in digest.external:
            lines.append(
                f"- {stats.service} {stats.op}: {stats.calls} ok (moy. {stats.average_ms} ms, max {stats.max_ms} ms),"
                f" {stats.errors} échec(s)"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir", type=Path, default=Path(".local/logs"), help="folder holding app.jsonl"
    )
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args(argv)
    if not args.dir.is_dir():
        print(f"Dossier de journal introuvable : {args.dir}", file=sys.stderr)
        return 2
    now = datetime.now(UTC)
    events, malformed = load_events(args.dir, since=now - timedelta(hours=args.hours))
    output = render_digest(build_digest(events, now=now, hours=args.hours))
    if malformed:
        output += f"\n{malformed} ligne(s) illisibles ignorée(s).\n"
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
