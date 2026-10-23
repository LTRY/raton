"""The quiz of a fiche: reading the model's answer into questions."""

import json
import random

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.llm_job import LlmJob
from back.services.jobs import llm_jobs
from back.services.llm.provider import CompletionResult
from back.services.llm.quiz import QUIZ_QUESTION_COUNT, QUIZ_SCHEMA, parse_quiz_result


def quiz_text(*questions):
    return json.dumps({"questions": list(questions)}, ensure_ascii=False)


def question(text="Pourquoi ?", right="Parce que.", wrong=("Non.", "Jamais.", "Peut-être.")):
    return {
        "question": text,
        "bonne_reponse": right,
        "mauvaises_reponses": list(wrong),
        "explication": "La vidéo le dit.",
    }


def test_the_right_answer_is_shuffled_among_the_choices_and_pointed_at():
    positions = set()
    for seed in range(20):
        [parsed] = parse_quiz_result(quiz_text(question()), random.Random(seed))
        assert sorted(parsed["choices"]) == sorted(["Parce que.", "Non.", "Jamais.", "Peut-être."])
        assert parsed["choices"][parsed["answer"]] == "Parce que."
        assert parsed["explanation"] == "La vidéo le dit."
        positions.add(parsed["answer"])
    # Not always where the model wrote it.
    assert len(positions) > 1


def test_unusable_questions_are_dropped_and_extra_ones_cut():
    text = quiz_text(
        question(text=" "),
        question(wrong=("Non.",)),  # too few wrong answers
        question(wrong=("Parce que.", "Non.", "Jamais.")),  # the right one listed as wrong
        *[question(text=f"Q{index} ?") for index in range(QUIZ_QUESTION_COUNT + 2)],
    )

    parsed = parse_quiz_result(text)

    assert [item["question"] for item in parsed] == [
        f"Q{index} ?" for index in range(QUIZ_QUESTION_COUNT)
    ]


@pytest.mark.parametrize("text", ["pas du json", '{"questions": []}', "[]"])
def test_an_answer_that_is_not_a_quiz_is_refused(text):
    with pytest.raises(ValueError):
        parse_quiz_result(text)


def test_the_job_asks_the_model_for_json_that_matches_the_quiz_schema(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    job = llm_jobs.enqueue_llm_job(db, kind="quiz", provider="anthropic", video_id=None, prompt="p")
    calls = []

    class FakeProvider:
        def complete(self, messages, on_text=None, system=None, json_schema=None):
            calls.append(json_schema)
            return CompletionResult(quiz_text(question()), "claude-sonnet-5", 10, 20, 0.0)

    monkeypatch.setattr(llm_jobs, "get_llm_provider", lambda: FakeProvider())
    monkeypatch.setattr(llm_jobs, "SessionLocal", lambda: db)

    llm_jobs.run_llm_job(job.id)

    assert calls == [QUIZ_SCHEMA]
    assert db.get(LlmJob, job.id).status == "done"
