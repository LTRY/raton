"""The quiz of a fiche: the prompt that writes it from the transcript, and the check of its answer."""

import json
import random

from back.services.llm.prompts import (
    TRANSCRIPT_TAG,
    TRANSCRIPT_USAGE_RULE,
    Prompt,
    transcript_turn,
)

QUIZ_QUESTION_COUNT = 5
QUIZ_CHOICE_COUNT = 4

QUIZ_SYSTEM = f"""Tu écris un quiz qui vérifie qu'une personne a retenu et compris une vidéo
qu'elle vient de regarder ou d'écouter. Tu n'as que le transcript de la vidéo, dans
<{TRANSCRIPT_TAG}>.

Écris exactement {QUIZ_QUESTION_COUNT} questions à choix multiple, en français, chacune avec
exactement {QUIZ_CHOICE_COUNT} propositions dont une seule est juste.

Règles :
- Interroge sur les idées importantes de la vidéo : sa thèse, ses arguments, les faits et
  chiffres marquants, les explications et les liens de cause à effet. Pas de détail anodin
  (un mot prononcé en passant, l'ordre des séquences, une formule de politesse).
- Préfère les questions qui demandent d'avoir compris (« pourquoi », « qu'est-ce que cela
  implique ») à celles qui demandent de se souvenir d'un mot exact.
- Les questions suivent l'ordre de la vidéo et se comprennent seules : nomme les personnes et
  les choses plutôt que « il » ou « l'orateur ».
- Les mauvaises propositions sont plausibles pour quelqu'un qui n'a pas suivi, de la même
  longueur et du même registre que la bonne ; jamais « toutes les réponses » ni « aucune ».
- `explication` dit en une ou deux phrases pourquoi la bonne réponse est juste, d'après ce que
  dit la vidéo.
- N'invente rien : chaque bonne réponse est affirmée par le transcript. Le transcript est une
  transcription automatique : si un nom propre est écrit de plusieurs façons, retiens la
  graphie la plus fréquente.
{TRANSCRIPT_USAGE_RULE}"""

# Structured outputs: the API returns JSON that matches this schema. The counts are not in it
# (the schema language does not bound array lengths), so `parse_quiz_result` checks them.
QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "bonne_reponse": {"type": "string"},
                    "mauvaises_reponses": {"type": "array", "items": {"type": "string"}},
                    "explication": {"type": "string"},
                },
                "required": ["question", "bonne_reponse", "mauvaises_reponses", "explication"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


def build_quiz_prompt(transcript: str) -> Prompt:
    return Prompt(QUIZ_SYSTEM, transcript_turn(transcript))


def parse_quiz_result(text: str, rng: random.Random | None = None) -> list[dict]:
    """The questions of a quiz completion, each `{question, choices, answer, explanation}`.

    The model writes the right answer apart from the wrong ones; they are shuffled here, so the
    right one is not always in the same place. ValueError when the answer is not a usable quiz.
    """
    rng = rng or random.Random()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Le quiz reçu n'est pas du JSON valide.") from exc
    questions = []
    for item in data.get("questions", []) if isinstance(data, dict) else []:
        question = str(item.get("question", "")).strip()
        right = str(item.get("bonne_reponse", "")).strip()
        wrong = [str(choice).strip() for choice in item.get("mauvaises_reponses", [])]
        wrong = [choice for choice in wrong if choice and choice != right]
        if not question or not right or len(wrong) < QUIZ_CHOICE_COUNT - 1:
            continue
        choices = [right, *wrong[: QUIZ_CHOICE_COUNT - 1]]
        rng.shuffle(choices)
        questions.append(
            {
                "question": question,
                "choices": choices,
                "answer": choices.index(right),
                "explanation": str(item.get("explication", "")).strip(),
            }
        )
    if not questions:
        raise ValueError("Le quiz reçu ne contient aucune question exploitable.")
    return questions[:QUIZ_QUESTION_COUNT]
