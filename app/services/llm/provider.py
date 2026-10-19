import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings
from app.services.llm.usage import BATCH_DISCOUNT, compute_call_cost_usd, max_output_tokens

LLM_TIMEOUT_SECONDS = 900
# Batch requests are not streamed, so the ceiling only has to cover notes plus the thinking
# that adaptive models add at low effort; a truncated answer fails (and is billed) instead.
BATCH_MAX_OUTPUT_TOKENS = 32_000
# These jobs always run in the background (never blocking the HTTP request), so
# there's no UX cost to retrying harder on transient errors (429/5xx, including
# Anthropic's "overloaded_error") than the SDK's default of 2 retries.
LLM_MAX_RETRIES = 6
logger = logging.getLogger("raton.llm")
# Tool results can be long lists; the log keeps enough to follow the exchange.
LOG_EXCERPT_CHARS = 1500


def _log_excerpt(text: str) -> str:
    if len(text) <= LOG_EXCERPT_CHARS:
        return text
    return f"{text[:LOG_EXCERPT_CHARS]}… [{len(text) - LOG_EXCERPT_CHARS} caractères de plus]"


def _log_single_call(model: str, prompt: str, response) -> None:
    # Unlike the tool loop, these prompts carry whole transcripts: sizes only.
    logger.info(
        "appel unique modèle=%s prompt=%d caractères → stop_reason=%s tokens entrée=%d sortie=%d",
        model,
        len(prompt),
        response.stop_reason,
        response.usage.input_tokens,
        response.usage.output_tokens,
        extra={
            "fields": {
                "event": "ext.call",
                "service": "anthropic",
                "op": "single_call",
                "model": model,
                "stop_reason": response.stop_reason,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        },
    )


@dataclass
class CompletionResult:
    """A completion plus the real usage the API reported for it.

    `input_tokens`/`output_tokens` are exact counts from the provider itself
    (not the char/4 heuristic used for pre-run estimates) — this is what lets
    `app/services/background_jobs.py:run_llm_job` record real per-job cost instead of guessing.
    """

    text: str
    model: str
    input_tokens: int | None  # everything sent: uncached + cache reads + cache writes
    output_tokens: int | None  # includes thinking tokens, which are billed as output
    # Summed per API call (the Haiku 5.5 price tier depends on each call's prompt size);
    # None makes run_llm_job fall back on pricing the totals as one call.
    cost_usd: float | None = None


class CompletionFailed(RuntimeError):
    """A response that came back but is unusable (truncated, empty) — its tokens were billed anyway."""

    def __init__(self, message: str, usage: UsageTally) -> None:
        super().__init__(message)
        self.usage = usage


@dataclass
class UsageTally:
    """Running usage of a job over all its API calls."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0

    def add(self, usage) -> None:
        # Cache fields are absent from older SDK/usage objects and None when unused.
        cache_write = getattr(usage, "cache_creation_input_tokens", None) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", None) or 0
        self.input_tokens += usage.input_tokens + cache_write + cache_read
        self.output_tokens += usage.output_tokens
        call_cost = compute_call_cost_usd(
            self.model, usage.input_tokens, usage.output_tokens, cache_write, cache_read
        )
        # One call on an unpriced model makes the whole job unpriceable.
        self.cost_usd = (
            None if call_cost is None or self.cost_usd is None else self.cost_usd + call_cost
        )

    def result(self, text: str) -> CompletionResult:
        return CompletionResult(
            text=text,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_usd=self.cost_usd,
        )


@dataclass
class BatchEntry:
    """One request's outcome in an ended Message Batch.

    `text` is None when the request did not succeed (`error` says why). The
    token counts are reported even for a response that came back truncated or
    empty, since those tokens are billed anyway.
    """

    custom_id: str
    text: str | None
    error: str | None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class LLMProvider(Protocol):
    def complete(
        self, prompt: str, on_text: Callable[[str], None] | None = None
    ) -> CompletionResult: ...

    def complete_with_tools(
        self,
        prompt: str,
        tools: list[dict],
        run_tool: Callable[[str, dict], str],
        max_tool_turns: int,
    ) -> CompletionResult: ...


def _response_text(response, tally: UsageTally) -> str:
    if response.stop_reason == "max_tokens":
        raise CompletionFailed(
            "La réponse a été tronquée (limite de tokens de sortie atteinte) : "
            "le transcript est trop long pour être traité en une seule fois.",
            tally,
        )
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise CompletionFailed("Anthropic n'a retourné aucune réponse.", tally)
    return text


def _forward_text(stream, on_text: Callable[[str], None] | None) -> None:
    """Feed each text delta of an open stream to `on_text`, if one was given."""
    if on_text is None:
        return
    for delta in stream.text_stream:
        on_text(delta)


class AnthropicProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def complete(
        self, prompt: str, on_text: Callable[[str], None] | None = None
    ) -> CompletionResult:
        import anthropic

        client = anthropic.Anthropic(
            api_key=self.api_key, timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES
        )
        # Stream + get_final_message(): the SDK refuses a non-streaming call whose
        # max_tokens implies a long enough response to risk a dropped connection.
        with client.messages.stream(
            model=self.model,
            max_tokens=max_output_tokens(self.model),
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            _forward_text(stream, on_text)
            response = stream.get_final_message()
        _log_single_call(self.model, prompt, response)
        tally = UsageTally(self.model)
        tally.add(response.usage)
        return tally.result(_response_text(response, tally))

    def complete_with_tools(
        self,
        prompt: str,
        tools: list[dict],
        run_tool: Callable[[str, dict], str],
        max_tool_turns: int,
    ) -> CompletionResult:
        """Let the model call `run_tool(name, arguments)` until it answers.

        Tokens and cost are summed over every API call of the loop, so the job's
        recorded cost covers the whole exchange.
        """
        import anthropic

        client = anthropic.Anthropic(
            api_key=self.api_key, timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES
        )
        messages: list[dict] = [{"role": "user", "content": prompt}]
        tally = UsageTally(self.model)
        logger.info(
            "boucle d'outils modèle=%s outils=%s\n--- prompt ---\n%s",
            self.model,
            ", ".join(tool["name"] for tool in tools),
            prompt,
        )
        for turn in range(max_tool_turns + 1):
            # Once the budget is spent the model must answer from what it already
            # has. The tools stay declared: the API rejects a conversation that
            # holds tool calls without them.
            tool_choice = {"type": "auto"} if turn < max_tool_turns else {"type": "none"}
            with client.messages.stream(
                model=self.model,
                max_tokens=max_output_tokens(self.model),
                tools=tools,
                tool_choice=tool_choice,
                messages=messages,
            ) as stream:
                response = stream.get_final_message()
            tally.add(response.usage)
            logger.info(
                "appel %d : %d message(s) envoyés, tool_choice=%s → stop_reason=%s tokens entrée=%d sortie=%d",
                turn + 1,
                len(messages),
                tool_choice["type"],
                response.stop_reason,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    logger.info("  texte du modèle : %s", block.text.strip())
            if response.stop_reason != "tool_use":
                break
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                logger.info(
                    "  outil demandé : %s(%s)",
                    block.name,
                    json.dumps(block.input, ensure_ascii=False),
                )
                output = run_tool(block.name, block.input)
                logger.info(
                    "  résultat renvoyé au modèle (%d caractères) :\n%s",
                    len(output),
                    _log_excerpt(output),
                )
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": output}
                )
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        logger.info(
            "boucle terminée : %d appel(s), tokens entrée=%d sortie=%d",
            turn + 1,
            tally.input_tokens,
            tally.output_tokens,
        )
        return tally.result(_response_text(response, tally))

    def submit_batch(self, prompts: dict[str, str], effort: str = "low") -> str:
        """Send `{custom_id: prompt}` as one Message Batch (half price, asynchronous) and return its id.

        Plain text completions with the effort lowered: extraction needs little reasoning, and the
        thinking tokens are billed as output.
        """
        import anthropic

        client = anthropic.Anthropic(
            api_key=self.api_key, timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES
        )
        batch = client.messages.batches.create(
            requests=[
                {
                    "custom_id": custom_id,
                    "params": {
                        "model": self.model,
                        "max_tokens": BATCH_MAX_OUTPUT_TOKENS,
                        "output_config": {"effort": effort},
                        "messages": [{"role": "user", "content": prompt}],
                    },
                }
                for custom_id, prompt in prompts.items()
            ]
        )
        return batch.id

    def batch_results(self, batch_id: str) -> list[BatchEntry] | None:
        """The outcome of every request of a batch, or None while it is still being processed."""
        import anthropic

        client = anthropic.Anthropic(
            api_key=self.api_key, timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES
        )
        if client.messages.batches.retrieve(batch_id).processing_status != "ended":
            return None
        entries: list[BatchEntry] = []
        # Results come back in any order: the caller matches them by custom_id.
        for item in client.messages.batches.results(batch_id):
            result = item.result
            if result.type != "succeeded":
                detail = getattr(getattr(result, "error", None), "error", None)
                message = getattr(detail, "message", None) or result.type
                entries.append(BatchEntry(item.custom_id, None, f"{result.type} : {message}"))
                continue
            message = result.message
            tally = UsageTally(self.model)
            tally.add(message.usage)
            cost = None if tally.cost_usd is None else tally.cost_usd * BATCH_DISCOUNT
            try:
                entries.append(
                    BatchEntry(
                        item.custom_id,
                        _response_text(message, tally),
                        None,
                        message.model,
                        tally.input_tokens,
                        tally.output_tokens,
                        cost,
                    )
                )
            except CompletionFailed as exc:
                entries.append(
                    BatchEntry(
                        item.custom_id,
                        None,
                        str(exc),
                        message.model,
                        tally.input_tokens,
                        tally.output_tokens,
                        cost,
                    )
                )
        return entries

    def complete_with_image(
        self,
        prompt: str,
        image_bytes: bytes,
        media_type: str,
        on_text: Callable[[str], None] | None = None,
    ) -> CompletionResult:
        import base64

        import anthropic

        client = anthropic.Anthropic(
            api_key=self.api_key, timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES
        )
        image_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(image_bytes).decode("ascii"),
            },
        }
        with client.messages.stream(
            model=self.model,
            max_tokens=max_output_tokens(self.model),
            messages=[{"role": "user", "content": [image_block, {"type": "text", "text": prompt}]}],
        ) as stream:
            _forward_text(stream, on_text)
            response = stream.get_final_message()
        _log_single_call(self.model, prompt, response)
        tally = UsageTally(self.model)
        tally.add(response.usage)
        return tally.result(_response_text(response, tally))


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    provider = settings.llm_provider.strip().lower()

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY n'est pas configurée.")
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)

    raise RuntimeError(f"LLM_PROVIDER inconnu : {provider!r} (attendu 'anthropic').")


NOTES_SECTION_NAMES = ["Faits", "Dates", "Lieux", "Acteurs", "Concepts", "Relations causales"]
NOTES_EMPTY_SECTION_MARKER = "Aucun élément identifié."

_NOTES_SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _notes_instructions() -> str:
    section_headers = "\n".join(f"## {name}" for name in NOTES_SECTION_NAMES)
    return f"""Tu es un expert en sciences de l'apprentissage et en prise de notes efficace.
Produis des notes structurées et exhaustives à partir de ce transcript, avec
exactement ces sections Markdown, dans cet ordre, chacune précédée de son
titre exact et rien d'autre avant le premier titre :

{section_headers}

Sous chaque titre, liste les éléments correspondants sous forme de puces (une
puce par élément). Si une section n'a aucun élément pertinent, écris
"{NOTES_EMPTY_SECTION_MARKER}" sous le titre plutôt que d'omettre la section.

N'invente rien : si une information ne figure pas dans le transcript, ne
l'ajoute pas. Base-toi uniquement sur le texte ci-dessous."""


def build_notes_prompt(transcript: str) -> str:
    return f"""{_notes_instructions()}

TRANSCRIPT:
{transcript}
"""


def split_notes_sections(text: str) -> list[tuple[str, str]]:
    """Split a build_notes_prompt completion into (section_name, content) chunks.

    One chunk per Markdown section, used both to render the notes tab and to
    index each section as a separate embedding for cross-video RAG search
    (app/services/rag/indexing.py). Sections that are empty or just the
    "no items" placeholder are skipped — they carry no retrievable content.
    Falls back to a single ("Notes", text) chunk if the model didn't follow
    the section-header format at all.
    """
    matches = list(_NOTES_SECTION_HEADER_RE.finditer(text))
    if not matches:
        stripped = text.strip()
        return [("Notes", stripped)] if stripped else []
    sections = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        name = match.group(1).strip()
        content = text[start:end].strip()
        if not content or content == NOTES_EMPTY_SECTION_MARKER:
            continue
        sections.append((name, content))
    return sections


SUMMARY_SHORT_HEADER = "## Résumé court"
SUMMARY_FULL_HEADER = "## Résumé complet"
SUMMARY_QUESTIONS_HEADER = "## Questions suggérées"

_BULLET_LINE_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$", re.MULTILINE)


def _summary_instructions() -> str:
    return f"""Tu es un rédacteur qui résume des vidéos parlées à partir de leur transcript.

Produis trois éléments fidèles et autonomes à propos de cette vidéo, dans cet
ordre exact, avec ces trois titres Markdown exacts et rien d'autre avant le
premier titre :

{SUMMARY_SHORT_HEADER}
Exactement 3 lignes qui donnent le sujet et la conclusion principale de la
vidéo — de quoi se faire une idée sans l'avoir vue.

{SUMMARY_FULL_HEADER}
Un texte suivi en paragraphes qui restitue le sujet, l'argumentation et les
conclusions dans un ordre logique (pas nécessairement chronologique si le
propos digresse), termine par 2 à 4 points clés (puces).

{SUMMARY_QUESTIONS_HEADER}
3 à 5 questions, une par ligne en puces, auxquelles un spectateur pourrait
avoir envie que cette vidéo réponde — des questions concrètes sur le contenu
réellement traité, pas des questions génériques qui iraient pour n'importe
quelle vidéo.

Règles communes :
- N'invente rien : base-toi uniquement sur le transcript ci-dessous.
- Le résumé complet est un texte suivi en paragraphes, pas une liste de faits
  en vrac.
- Longueur proportionnée au contenu : reste un résumé, ne cherche pas à tout
  restituer."""


def build_summary_prompt(transcript: str) -> str:
    return f"""{_summary_instructions()}

TRANSCRIPT:
{transcript}
"""


def split_summary_result(text: str) -> tuple[str, str, list[str]]:
    """Split a build_summary_prompt completion into (short, full, questions).

    Falls back to (empty, whole text as the full summary, []) if the model
    didn't follow the header format — degrades gracefully instead of guessing.
    """
    full_marker = re.search(
        rf"^{re.escape(SUMMARY_FULL_HEADER)}\s*$", text, re.IGNORECASE | re.MULTILINE
    )
    if full_marker is None:
        return "", text.strip(), []
    short = re.sub(
        rf"^{re.escape(SUMMARY_SHORT_HEADER)}\s*$",
        "",
        text[: full_marker.start()],
        flags=re.IGNORECASE | re.MULTILINE,
    )

    questions_marker = re.search(
        rf"^{re.escape(SUMMARY_QUESTIONS_HEADER)}\s*$", text, re.IGNORECASE | re.MULTILINE
    )
    if questions_marker is None:
        return short.strip(), text[full_marker.end() :].strip(), []
    full = text[full_marker.end() : questions_marker.start()].strip()
    questions = [
        match.group(1) for match in _BULLET_LINE_RE.finditer(text[questions_marker.end() :])
    ]
    return short.strip(), full, questions


THUMBNAIL_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

ANALYSIS_CLICKBAIT_HEADER = "## Score clickbait"
ANALYSIS_RELEVANCE_HEADER = "## Pertinence du contenu"
ANALYSIS_SUGGESTIONS_HEADER = "## Suggestions"

_ANALYSIS_SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_ANALYSIS_SCORE_RE = re.compile(r"Score\s*:\s*(\d{1,2})\s*/\s*10")
_ANALYSIS_PERCENT_RE = re.compile(r"Contenu utile\s*:\s*(\d{1,3})\s*%")
_ANALYSIS_JUSTIFICATION_RE = re.compile(r"Justification\s*:\s*(.+)", re.DOTALL)
_ANALYSIS_TITLE_RE = re.compile(r"^Titre\s*\d\s*:\s*(.+)$", re.MULTILINE)
_ANALYSIS_CATEGORIES_RE = re.compile(r"^Catégories\s*:\s*(.+)$", re.MULTILINE)


def _video_analysis_instructions(title: str, has_image: bool) -> str:
    clickbait_section = ""
    if has_image:
        clickbait_section = f"""{ANALYSIS_CLICKBAIT_HEADER}
Compare la miniature jointe et le titre ci-dessus au contenu réel du
transcript. Réponds sur exactement deux lignes, sans rien ajouter :
Score : <un nombre entier de 1 à 10, où 10 signifie parfaitement fidèle et 1 signifie clickbait extrême>/10
Justification : <une phrase expliquant l'écart ou l'absence d'écart>

"""
    image_mention = " et la miniature jointe" if has_image else ""
    return f"""Tu es un analyste qui évalue une vidéo à partir de son transcript{image_mention}.

Titre actuel de la vidéo : {title}

Produis les sections suivantes, dans cet ordre exact, avec ces titres
Markdown exacts et rien d'autre avant le premier titre :

{clickbait_section}{ANALYSIS_RELEVANCE_HEADER}
Évalue la part du contenu qui traite réellement le sujet annoncé, par
opposition au remplissage (introduction longue, sponsors, redites,
digressions hors sujet). Réponds sur exactement deux lignes, sans rien
ajouter :
Contenu utile : <un nombre entier de 0 à 100>%
Justification : <une phrase expliquant l'estimation>

{ANALYSIS_SUGGESTIONS_HEADER}
Propose 3 titres alternatifs plus fidèles au contenu réel (du plus au moins
convaincant), et 1 à 3 catégories qui décrivent ce sujet réel. Réponds sur
exactement quatre lignes, sans rien ajouter :
Titre 1 : <premier titre suggéré>
Titre 2 : <deuxième titre suggéré>
Titre 3 : <troisième titre suggéré>
Catégories : <catégorie 1>, <catégorie 2>, <catégorie 3>

Règles communes :
- N'invente rien : base-toi uniquement sur le transcript ci-dessous{image_mention}.
- Respecte strictement le format de ligne demandé pour chaque champ, sans
  texte supplémentaire ni ligne vide au milieu d'une section."""


def build_video_analysis_prompt(transcript: str, title: str, has_image: bool) -> str:
    return f"""{_video_analysis_instructions(title, has_image)}

TRANSCRIPT:
{transcript}
"""


def split_video_analysis_result(text: str, has_image: bool) -> dict:
    """Split a build_video_analysis_prompt completion into an analysis dict.

    Keys are present only when their section exists and matches the expected
    line format — missing/malformed sections are silently omitted rather than
    guessed, mirroring split_summary_result's fallback. has_image=False means
    the clickbait section was never requested, so it's never looked for even
    if the model produced one anyway.
    """
    matches = list(_ANALYSIS_SECTION_HEADER_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).strip()] = text[start:end].strip()

    result: dict = {}

    if has_image:
        clickbait_text = sections.get(ANALYSIS_CLICKBAIT_HEADER.removeprefix("## "))
        if clickbait_text:
            score_match = _ANALYSIS_SCORE_RE.search(clickbait_text)
            justification_match = _ANALYSIS_JUSTIFICATION_RE.search(clickbait_text)
            if score_match:
                result["clickbait_score"] = int(score_match.group(1))
            if justification_match:
                result["clickbait_rationale"] = justification_match.group(1).strip()

    relevance_text = sections.get(ANALYSIS_RELEVANCE_HEADER.removeprefix("## "))
    if relevance_text:
        percent_match = _ANALYSIS_PERCENT_RE.search(relevance_text)
        justification_match = _ANALYSIS_JUSTIFICATION_RE.search(relevance_text)
        if percent_match:
            result["relevance_percent"] = int(percent_match.group(1))
        if justification_match:
            result["relevance_rationale"] = justification_match.group(1).strip()

    suggestions_text = sections.get(ANALYSIS_SUGGESTIONS_HEADER.removeprefix("## "))
    if suggestions_text:
        title_matches = _ANALYSIS_TITLE_RE.findall(suggestions_text)
        categories_match = _ANALYSIS_CATEGORIES_RE.search(suggestions_text)
        if title_matches:
            result["suggested_titles"] = [t.strip() for t in title_matches][:3]
        if categories_match:
            result["suggested_categories"] = [
                c.strip() for c in categories_match.group(1).split(",") if c.strip()
            ]

    return result


GENERATION_NOTES_HEADER = "# Notes"
GENERATION_SUMMARY_HEADER = "# Résumé"
GENERATION_ANALYSIS_HEADER = "# Analyse"

_GENERATION_SECTION_HEADER_RE = re.compile(r"^#\s+(Notes|Résumé|Analyse)\s*$", re.MULTILINE)


def build_generation_prompt(transcript: str, title: str, has_image: bool) -> str:
    """Notes + résumé + analyse in a single completion, transcript sent once.

    Wraps the three existing single-purpose instruction blocks under distinct
    level-1 Markdown headers (their own `##` sub-headers stay level-2, so the
    two never collide) so split_generation_result can slice the response back
    into the same three pieces each single-purpose split_* function expects.

    The résumé comes first because it is the part shown to the user while the
    completion streams (see partial_generation_summary).
    """
    return f"""Tu produis trois analyses d'une même vidéo à partir de son
transcript en un seul appel, pour éviter d'envoyer ce transcript plusieurs
fois. Produis exactement ces trois sections, dans cet ordre, chacune
introduite par son titre Markdown de niveau 1 exact et rien d'autre avant le
premier titre :

{GENERATION_SUMMARY_HEADER}
{_summary_instructions()}

{GENERATION_NOTES_HEADER}
{_notes_instructions()}

{GENERATION_ANALYSIS_HEADER}
{_video_analysis_instructions(title, has_image)}

TRANSCRIPT:
{transcript}
"""


def split_generation_result(text: str, has_image: bool) -> dict:
    """Split a build_generation_prompt completion into notes/summary/analysis.

    Slices the response on the three level-1 headers first, then delegates
    each slice to the matching single-purpose split_* function. A missing
    top-level section (model didn't follow the format) yields empty/absent
    results for that piece rather than a guess — same philosophy as the
    single-purpose split functions.
    """
    matches = list(_GENERATION_SECTION_HEADER_RE.finditer(text))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks[match.group(1)] = text[start:end].strip()

    summary_short, summary_full, summary_questions = split_summary_result(blocks.get("Résumé", ""))
    return {
        "notes_text": blocks.get("Notes", ""),
        "summary_short": summary_short,
        "summary_full": summary_full,
        "summary_questions": summary_questions,
        "analysis": split_video_analysis_result(blocks.get("Analyse", ""), has_image),
    }


def _short_summary_instructions() -> str:
    return f"""Tu es un rédacteur qui résume des vidéos parlées à partir de leur transcript.

Produis un seul élément, sous ce titre Markdown exact et rien d'autre avant :

{SUMMARY_SHORT_HEADER}
Exactement 3 lignes qui donnent le sujet et la conclusion principale de la
vidéo — de quoi se faire une idée sans l'avoir vue.

N'invente rien : base-toi uniquement sur le transcript ci-dessous."""


def build_auto_notes_prompt(transcript: str) -> str:
    """Notes + résumé court in one completion: what the nightly batch asks for each video.

    The same `# Résumé` / `# Notes` level-1 headers as build_generation_prompt, so the answer is
    sliced the same way; the long résumé, the questions and the analysis are left to the robot
    button (they are reading aids, not what the cross-video search indexes).
    """
    return f"""Tu produis deux analyses d'une même vidéo à partir de son transcript en un seul
appel. Produis exactement ces deux sections, dans cet ordre, chacune introduite
par son titre Markdown de niveau 1 exact et rien d'autre avant le premier titre :

{GENERATION_SUMMARY_HEADER}
{_short_summary_instructions()}

{GENERATION_NOTES_HEADER}
{_notes_instructions()}

TRANSCRIPT:
{transcript}
"""


# The two sections are asked as level-1 titles, but a model sometimes writes "## Notes" under its
# "# Résumé" (seen on 1 answer out of 844): accept both levels. Neither can be mistaken for a notes
# section ("## Faits"...) or the "## Résumé court" line, which the end-of-line anchor rules out.
_AUTO_NOTES_SECTION_HEADER_RE = re.compile(r"^#{1,2}\s+(Notes|Résumé)\s*$", re.MULTILINE)


def split_auto_notes_result(text: str) -> tuple[str, str]:
    """Split a build_auto_notes_prompt completion into (notes_text, summary_short).

    A missing section yields an empty string for that piece, never a guess.
    """
    matches = list(_AUTO_NOTES_SECTION_HEADER_RE.finditer(text))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks[match.group(1)] = text[match.end() : end].strip()
    summary_block = blocks.get("Résumé", "")
    summary = re.sub(
        rf"^{re.escape(SUMMARY_SHORT_HEADER)}\s*$",
        "",
        summary_block,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return blocks.get("Notes", ""), summary.strip()


def _between_headers(text: str, start_header: str, end_header: str) -> str | None:
    """Text after the `start_header` line, up to the `end_header` line if it is there yet."""
    start = re.search(rf"^{re.escape(start_header)}[ \t]*$", text, re.IGNORECASE | re.MULTILINE)
    if start is None:
        return None
    rest = text[start.end() :]
    end = re.search(rf"^{re.escape(end_header)}[ \t]*$", rest, re.IGNORECASE | re.MULTILINE)
    return rest[: end.start()] if end else rest


def partial_generation_summary(text: str) -> tuple[str, str]:
    """(short, full) résumé as far as a still-streaming generation has written them.

    Each value only ever grows from one call to the next on the same stream,
    so a client can append what is new. That is why a last line starting with
    `#` is dropped: it is a header still being written, which would otherwise
    show up as résumé text and then vanish.
    """
    matches = list(_GENERATION_SECTION_HEADER_RE.finditer(text))
    block = ""
    for index, match in enumerate(matches):
        if match.group(1) == "Résumé":
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[match.end() : end]
            break
    head, _, last_line = block.rpartition("\n")
    if last_line.lstrip().startswith("#"):
        block = head + "\n"
    short = _between_headers(block, SUMMARY_SHORT_HEADER, SUMMARY_FULL_HEADER) or ""
    full = _between_headers(block, SUMMARY_FULL_HEADER, SUMMARY_QUESTIONS_HEADER) or ""
    return short.strip(), full.strip()


def build_chat_prompt(transcript: str, messages: list[dict[str, str]], question: str) -> str:
    history = "\n\n".join(
        f"{'UTILISATEUR' if message['role'] == 'user' else 'ASSISTANT'}: {message['content']}"
        for message in messages[-10:]
    )
    return f"""Réponds à la question en utilisant uniquement le transcript fourni.
Si l'information n'est pas dans le transcript, dis-le clairement.
Réponds en français, de façon précise. Tu peux citer de courts passages utiles.

TRANSCRIPT:
{transcript}

HISTORIQUE:
{history or "(aucun échange précédent)"}

QUESTION:
{question}
"""


def build_library_chat_prompt(messages: list[dict[str, str]], question: str) -> str:
    """Build the cross-video ("whole library") chat prompt.

    It carries no library content: the model fetches what it needs through the
    tools of app/services/rag/library_chat_tools.py, whose reference format this
    prompt tells it to cite.
    """
    history = "\n\n".join(
        f"{'UTILISATEUR' if message['role'] == 'user' else 'ASSISTANT'}: {message['content']}"
        for message in messages[-10:]
    )
    return f"""Tu es l'assistant de recherche de la bibliothèque vidéo personnelle de
l'utilisateur : des chaînes YouTube suivies, leurs vidéos, et des notes
structurées tirées des transcripts.

Utilise les outils pour chercher dans cette bibliothèque avant de répondre, en
choisissant ceux qui conviennent à la question (une chaîne ou une vidéo précise,
un thème, une question sur le contenu). Tu peux en enchaîner plusieurs.
Appuie-toi uniquement sur leurs résultats : si rien ne correspond, dis-le
clairement plutôt que d'inventer.

L'outil d'historique donne ce que l'utilisateur a déjà regardé ou écouté
(récent d'abord, avec la progression) : utilise-le pour « qu'ai-je regardé »,
« ai-je déjà vu... » ou « qu'est-ce que je n'ai pas fini ».

Tu peux aussi chercher sur YouTube une chaîne absente de la bibliothèque, et
l'ajouter quand l'utilisateur le demande explicitement (« ajoute la chaîne de
X »). Cherche-la d'abord sur YouTube. Si une candidate correspond nettement à la
demande (même nom, et bien plus d'abonnés que ses homonymes), ajoute-la et
confirme-le en précisant son handle et son nombre d'abonnés, pour que
l'utilisateur puisse vérifier que c'est la bonne. Si plusieurs candidates sont
plausibles, n'ajoute rien : présente-les,
une par ligne avec leur handle et leur nombre d'abonnés, et demande laquelle
ajouter. Quand l'utilisateur en choisit une dans un message suivant, relance la
recherche avec son handle avant de l'ajouter. Les identifiants [youtube:...]
servent uniquement à l'outil d'ajout : ne les recopie jamais dans ta réponse.

Chaque chaîne ou vidéo renvoyée par un outil porte une référence, par exemple
[chaine:12] ou [video:34]. Quand tu cites une chaîne ou une vidéo dans ta
réponse, écris son nom ou son titre à l'endroit où tu en parles, entouré de sa
référence sous la forme [[chaine:12|Nom de la chaîne]] ou
[[video:34|Titre de la vidéo]] : le texte affiché est le nom, qui devient un lien
cliquable surligné, et la phrase doit se lire normalement sans la syntaxe.
Tu peux reprendre sous cette forme une référence déjà écrite plus haut dans la
conversation. Ne référence que ce qui répond vraiment à la question, n'invente
jamais de référence, et ne recopie jamais de référence en dehors de cette forme.

Les outils ne renvoient qu'un nombre limité de résultats, et la recherche dans
les notes ne couvre que les vidéos dont les notes ont été générées. Ne présente
donc jamais tes résultats comme la liste complète : dis ce que tu as trouvé
(« j'ai trouvé... », « au moins... »), pas ce que la bibliothèque contient en
tout.

Réponds en français, de façon précise et concise, en vouvoyant l'utilisateur.
Écris en texte brut : la réponse est affichée telle quelle, sans mise en forme,
donc pas de Markdown (ni astérisques, ni titres, ni liens). Pour une liste, un
élément par ligne commençant par un tiret.

HISTORIQUE:
{history or "(aucun échange précédent)"}

QUESTION:
{question}
"""


def load_chat(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return []
    return [
        message
        for message in data
        if isinstance(message, dict)
        and message.get("role") in {"user", "assistant"}
        and isinstance(message.get("content"), str)
    ]


def save_chat(path: Path, messages: list[dict[str, str]]) -> None:
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
