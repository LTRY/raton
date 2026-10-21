"""Compare two prompt variants side by side on real transcripts.

    uv run --python 3.14 python -m scripts.eval_prompts \\
        --a evals/notes/current.py --b evals/notes/candidate.py [--n 8] [--dry-run]

A variant is a Python file with `build(transcript) -> Prompt` (see evals/notes/). The same random
sample of transcripts goes through both, and the answers are written as a side-by-side HTML report
to judge by eye. The task is the nightly "notes + résumé court" one, so each answer is also
parsed with the app's own splitters and the report flags what does not parse.

Reports hold the user's transcripts: they go under `.local/evals/`, which git ignores. An answer is
cached by a hash of what was sent, so running again after editing one variant only pays for it.
"""

import argparse
import hashlib
import html
import importlib.util
import json
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from app.core.config import Settings
from app.services.llm.prompts import Prompt, split_auto_notes_result, split_notes_sections
from app.services.llm.provider import AnthropicProvider
from app.services.rag.auto_notes import MIN_TRANSCRIPT_CHARS

DEFAULT_MODEL = "claude-haiku-5-5"  # what the nightly batch runs on
DEFAULT_MEDIA_ROOT = Path(".local/media/YouTube")
EVALS_DIR = Path(".local/evals")


@dataclass
class Variant:
    name: str
    build: object  # Callable[[str], Prompt | str]

    def prompt(self, transcript: str) -> Prompt:
        built = self.build(transcript)
        if isinstance(built, str):
            return Prompt("", [{"role": "user", "content": built}])
        return built


@dataclass
class Answer:
    text: str = ""
    error: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    seconds: float = 0.0
    cached: bool = False


def load_variant(path: Path) -> Variant:
    spec = importlib.util.spec_from_file_location(f"eval_variant_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return Variant(getattr(module, "NAME", path.stem), module.build)


def sample_transcripts(media_root: Path, count: int, seed: int) -> list[Path]:
    """`count` transcripts the nightly batch would take (long enough), the same ones for a seed."""
    eligible = sorted(
        path
        for path in media_root.rglob("transcript.txt")
        if path.stat().st_size >= MIN_TRANSCRIPT_CHARS
    )
    return random.Random(seed).sample(eligible, min(count, len(eligible)))


def cache_key(model: str, prompt: Prompt) -> str:
    payload = json.dumps([model, prompt.system, prompt.messages], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def answer_for(provider, prompt: Prompt, cache_dir: Path, *, call_api: bool = True) -> Answer:
    """The model's answer to `prompt`, from the cache when this exact prompt was already paid for."""
    cache_file = cache_dir / f"{cache_key(provider.model, prompt)}.json"
    if cache_file.is_file():
        return Answer(**{**json.loads(cache_file.read_text(encoding="utf-8")), "cached": True})
    if not call_api:
        return Answer(error="(pas d'appel : --dry-run)")
    started = time.monotonic()
    try:
        completion = provider.complete(prompt.messages, system=prompt.system)
    except Exception as exc:
        return Answer(error=str(exc), seconds=time.monotonic() - started)
    answer = Answer(
        text=completion.text,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
        cost_usd=completion.cost_usd,
        seconds=round(time.monotonic() - started, 1),
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(asdict(answer), ensure_ascii=False), encoding="utf-8")
    return answer


_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ«\"'])")


def count_sentences(text: str) -> int:
    """Sentences of `text`, told apart by a full stop followed by a capital: close enough to flag a
    résumé that is one run-on sentence or five."""
    return len([part for part in _SENTENCE_END.split(text.strip()) if part.strip()])


def check_answer(text: str) -> tuple[str, str, list[str]]:
    """(notes, résumé court, problems) of a notes + résumé court answer, parsed like the app does."""
    notes, summary = split_auto_notes_result(text)
    problems = []
    sections = split_notes_sections(notes)
    if not sections:
        problems.append("aucune note exploitable")
    if not summary:
        problems.append("pas de résumé court")
    elif (count := count_sentences(summary)) != 3:
        problems.append(f"résumé court de {count} phrases (3 attendues)")
    return notes, summary, problems


_CSS = """
:root { --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --card:#f5f5f7; --line:#d2d2d7; --bad:#b3261e; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#1c1c1e; --fg:#f2f2f7; --muted:#a1a1a6; --card:#2c2c2e; --line:#48484a; --bad:#ff8a80; }
}
body { background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, sans-serif; margin:0 auto;
  max-width:1200px; padding:16px; }
h1 { font-size:1.3rem } h2 { font-size:1rem; margin:0 0 8px; overflow-wrap:anywhere }
.summary, .video { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:12px 16px; margin-bottom:16px }
.pair { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px }
@media (max-width:760px) { .pair { grid-template-columns:minmax(0, 1fr) } }
.col { border:1px solid var(--line); border-radius:8px; padding:8px 12px; min-width:0 }
.meta { color:var(--muted); font-size:.85rem } .bad { color:var(--bad); font-weight:600 }
pre { white-space:pre-wrap; overflow-wrap:anywhere; margin:6px 0; font:inherit }
.vote label { margin-right:14px } .tally { font-weight:600 }
"""

_JS = """
const votes = JSON.parse(localStorage.getItem(KEY) || '{}');
function tally() {
  const counts = {a:0, b:0, tie:0};
  Object.values(votes).forEach(v => counts[v]++);
  document.getElementById('tally').textContent =
    `A : ${counts.a} · B : ${counts.b} · égal : ${counts.tie}`;
}
document.querySelectorAll('input[type=radio]').forEach(input => {
  if (votes[input.name] === input.value) input.checked = true;
  input.addEventListener('change', () => {
    votes[input.name] = input.value;
    localStorage.setItem(KEY, JSON.stringify(votes));
    tally();
  });
});
tally();
"""


def _column(variant: str, answer: Answer) -> str:
    if answer.error:
        return (
            f'<div class="col"><h3>{html.escape(variant)}</h3>'
            f'<p class="bad">{html.escape(answer.error)}</p></div>'
        )
    notes, summary, problems = check_answer(answer.text)
    meta = (
        f"{answer.input_tokens} → {answer.output_tokens} tokens · "
        f"{answer.cost_usd:.4f} $ · {answer.seconds} s" + (" · cache" if answer.cached else "")
        if answer.cost_usd is not None
        else "coût inconnu"
    )
    raw = (
        f"<details><summary>Réponse brute</summary><pre>{html.escape(answer.text)}</pre></details>"
        if problems
        else ""
    )
    flags = "".join(f'<p class="bad">⚠ {html.escape(problem)}</p>' for problem in problems)
    return (
        f'<div class="col"><h3>{html.escape(variant)}</h3><p class="meta">{meta}</p>{flags}'
        f"<strong>Résumé court</strong><pre>{html.escape(summary)}</pre>"
        f"<strong>Notes</strong><pre>{html.escape(notes)}</pre>{raw}</div>"
    )


def render_report(
    names: tuple[str, str], model: str, rows: list[tuple[str, tuple[Answer, Answer]]]
) -> str:
    totals = [sum(pair[index].cost_usd or 0 for _, pair in rows) for index in (0, 1)]
    failures = [
        sum(1 for _, pair in rows if pair[index].error or check_answer(pair[index].text)[2])
        for index in (0, 1)
    ]
    cards = []
    for number, (label, (first, second)) in enumerate(rows):
        name = f"v{number}"
        cards.append(
            f'<section class="video"><h2>{html.escape(label)}</h2>'
            f'<div class="pair">{_column(f"A · {names[0]}", first)}'
            f"{_column(f'B · {names[1]}', second)}</div>"
            f'<p class="vote">Meilleur : '
            f'<label><input type="radio" name="{name}" value="a"> A</label>'
            f'<label><input type="radio" name="{name}" value="b"> B</label>'
            f'<label><input type="radio" name="{name}" value="tie"> égal</label></p></section>'
        )
    summary = (
        f'<div class="summary"><p class="tally" id="tally"></p>'
        f'<p class="meta">Modèle {html.escape(model)} · {len(rows)} vidéos · '
        f"A : {totals[0]:.4f} $, {failures[0]} sortie(s) à problème · "
        f"B : {totals[1]:.4f} $, {failures[1]} sortie(s) à problème</p></div>"
    )
    key = json.dumps(f"eval:{names[0]}:{names[1]}:{[label for label, _ in rows]}")
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Évaluation de prompts</title><style>{_CSS}</style></head><body>"
        f"<h1>A : {html.escape(names[0])} · B : {html.escape(names[1])}</h1>"
        f"{summary}{''.join(cards)}<script>const KEY = {key};{_JS}</script></body></html>"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--a", type=Path, required=True, help="variant file A")
    parser.add_argument("--b", type=Path, required=True, help="variant file B")
    parser.add_argument("--n", type=int, default=8, help="transcripts to sample")
    parser.add_argument("--seed", type=int, default=1, help="same seed = same transcripts")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--media-root", type=Path, default=DEFAULT_MEDIA_ROOT)
    parser.add_argument("--env-file", default=".env", help="file holding ANTHROPIC_API_KEY")
    parser.add_argument(
        "--dry-run", action="store_true", help="list what would be called, pay nothing"
    )
    args = parser.parse_args(argv)

    variants = (load_variant(args.a), load_variant(args.b))
    paths = sample_transcripts(args.media_root, args.n, args.seed)
    if not paths:
        print(
            f"Aucun transcript.txt d'au moins {MIN_TRANSCRIPT_CHARS} octets sous {args.media_root}"
        )
        return 1
    api_key = Settings(_env_file=args.env_file).anthropic_api_key
    if not api_key and not args.dry_run:
        print(f"ANTHROPIC_API_KEY introuvable (variable d'environnement ou {args.env_file}).")
        return 1
    provider = AnthropicProvider(api_key, args.model)
    cache_dir = EVALS_DIR / "cache"

    rows = []
    for path in paths:
        transcript = path.read_text(encoding="utf-8", errors="replace")
        pair = tuple(
            answer_for(provider, variant.prompt(transcript), cache_dir, call_api=not args.dry_run)
            for variant in variants
        )
        rows.append((str(path.parent.relative_to(args.media_root)), pair))
        print(
            f"{path.parent.name[:60]:60} "
            + " ".join("cache" if a.cached else "appel" for a in pair)
        )

    if args.dry_run:
        calls = sum(1 for _, pair in rows for a in pair if not a.cached)
        print(f"{calls} appel(s) API à payer ({len(rows) * 2 - calls} déjà en cache).")
        return 0
    report_dir = EVALS_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir.mkdir(parents=True)
    names = (variants[0].name, variants[1].name)
    (report_dir / "report.html").write_text(
        render_report(names, args.model, rows), encoding="utf-8"
    )
    (report_dir / "results.json").write_text(
        json.dumps(
            [{"video": label, "a": asdict(a), "b": asdict(b)} for label, (a, b) in rows],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Rapport : {report_dir / 'report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
