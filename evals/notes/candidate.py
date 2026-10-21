"""The prompt under test. Starts as the current one: edit `build` to try a change.

`build(transcript)` returns a `Prompt(system, messages)`. To change the wording, copy the text of
`app/services/llm/prompts.py` here (or wrap the current prompt and edit its `system`), then:

    uv run --python 3.14 python -m scripts.eval_prompts --a evals/notes/current.py \
        --b evals/notes/candidate.py
"""

from app.services.llm.prompts import build_auto_notes_prompt

NAME = "candidate"


def build(transcript: str):
    prompt = build_auto_notes_prompt(transcript)
    return prompt  # e.g. prompt._replace(system=prompt.system + "\nRègle de test : ...")
