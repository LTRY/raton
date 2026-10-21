from pathlib import Path

from app.services.llm.prompts import Prompt
from app.services.llm.provider import CompletionResult
from scripts.eval_prompts import (
    Answer,
    answer_for,
    cache_key,
    check_answer,
    count_sentences,
    load_variant,
    render_report,
    sample_transcripts,
)

GOOD_ANSWER = (
    "# Résumé\n## Résumé court\nUne.\nDeux.\nTrois.\n\n"
    "# Notes\n## Faits\n- Un fait.\n\n## Dates\nAucun élément identifié.\n"
)


class FakeProvider:
    model = "claude-haiku-5-5"

    def __init__(self):
        self.calls = []

    def complete(self, messages, system=None):
        self.calls.append((messages, system))
        return CompletionResult(
            text=GOOD_ANSWER, model=self.model, input_tokens=100, output_tokens=40, cost_usd=0.001
        )


def make_library(root: Path, names: list[str], size: int = 600) -> None:
    for name in names:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "transcript.txt").write_text("x" * size, encoding="utf-8")


def test_sample_is_repeatable_and_skips_short_transcripts(tmp_path):
    make_library(tmp_path, [f"video{i}" for i in range(6)])
    make_library(tmp_path, ["tiny"], size=10)

    first = sample_transcripts(tmp_path, 3, seed=1)

    assert first == sample_transcripts(tmp_path, 3, seed=1)
    assert len(first) == 3 and all(path.parent.name != "tiny" for path in first)
    assert len(sample_transcripts(tmp_path, 50, seed=1)) == 6  # never more than there are


def test_cache_key_follows_what_is_sent():
    prompt = Prompt("S", [{"role": "user", "content": "T"}])

    assert cache_key("m", prompt) == cache_key("m", Prompt("S", [{"role": "user", "content": "T"}]))
    assert cache_key("m", prompt) != cache_key("other", prompt)
    assert cache_key("m", prompt) != cache_key("m", prompt._replace(system="S2"))


def test_an_answer_is_paid_once_per_prompt(tmp_path):
    provider = FakeProvider()
    prompt = Prompt("S", [{"role": "user", "content": "T"}])

    first = answer_for(provider, prompt, tmp_path)
    second = answer_for(provider, prompt, tmp_path)

    assert len(provider.calls) == 1
    assert (first.cached, second.cached) == (False, True)
    assert second.text == GOOD_ANSWER and second.cost_usd == 0.001


def test_dry_run_calls_nothing(tmp_path):
    provider = FakeProvider()

    answer = answer_for(provider, Prompt("S", []), tmp_path, call_api=False)

    assert provider.calls == [] and answer.error


def test_check_answer_flags_what_does_not_parse():
    notes, summary, problems = check_answer(GOOD_ANSWER)
    assert summary == "Une.\nDeux.\nTrois." and "Un fait." in notes and problems == []

    assert "aucune note exploitable" in check_answer("du texte libre")[2]
    two_sentences = GOOD_ANSWER.replace("Trois.", "")
    assert any("2 phrases" in problem for problem in check_answer(two_sentences)[2])


def test_count_sentences_handles_one_paragraph_and_accents():
    paragraph = "Une phrase d'IA. Une deuxième (Exploit Gym), avec 3,5 %. « Et la troisième ? »"

    assert count_sentences(paragraph) == 3
    assert count_sentences("Une seule phrase sans point final") == 1
    assert count_sentences("A.\nB.\nC.") == 3


def test_load_variant_reads_name_and_build(tmp_path):
    path = tmp_path / "mine.py"
    path.write_text('NAME = "ma variante"\ndef build(t):\n    return "prompt " + t\n')

    variant = load_variant(path)

    assert variant.name == "ma variante"
    assert variant.prompt("T") == Prompt("", [{"role": "user", "content": "prompt T"}])


def test_report_shows_both_columns_and_escapes_the_answers():
    good = Answer(text=GOOD_ANSWER, input_tokens=1, output_tokens=2, cost_usd=0.002, seconds=1.5)
    hostile = Answer(text="<script>alert(1)</script>", cost_usd=0.001)

    report = render_report(("current", "candidate"), "claude-haiku-5-5", [("v1", (good, hostile))])

    assert "A · current" in report and "B · candidate" in report
    assert "<script>alert(1)</script>" not in report
    assert "&lt;script&gt;" in report
    assert "aucune note exploitable" in report
    assert 'name="v0"' in report
