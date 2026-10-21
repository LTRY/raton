import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings
from app.services.llm.prompts import Prompt
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


def _log_single_call(model: str, prompt_chars: int, response) -> None:
    # Unlike the tool loop, these prompts carry whole transcripts: sizes only.
    logger.info(
        "appel unique modèle=%s prompt=%d caractères → stop_reason=%s tokens entrée=%d sortie=%d",
        model,
        prompt_chars,
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
    `app/services/jobs/llm_jobs.py:run_llm_job` record real per-job cost instead of guessing.
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
        self,
        messages: str | list[dict],
        on_text: Callable[[str], None] | None = None,
        system: str | None = None,
    ) -> CompletionResult: ...

    def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        run_tool: Callable[[str, dict], str],
        max_tool_turns: int,
        system: str | None = None,
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
        self,
        messages: str | list[dict],
        on_text: Callable[[str], None] | None = None,
        system: str | None = None,
    ) -> CompletionResult:
        """One completion of `messages` (a bare string is a single user message) under `system`."""
        import anthropic

        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        client = anthropic.Anthropic(
            api_key=self.api_key, timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES
        )
        # Stream + get_final_message(): the SDK refuses a non-streaming call whose
        # max_tokens implies a long enough response to risk a dropped connection.
        with client.messages.stream(
            model=self.model,
            max_tokens=max_output_tokens(self.model),
            messages=messages,
            **({"system": system} if system else {}),
        ) as stream:
            _forward_text(stream, on_text)
            response = stream.get_final_message()
        prompt_chars = len(system or "") + sum(len(message["content"]) for message in messages)
        _log_single_call(self.model, prompt_chars, response)
        tally = UsageTally(self.model)
        tally.add(response.usage)
        return tally.result(_response_text(response, tally))

    def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        run_tool: Callable[[str, dict], str],
        max_tool_turns: int,
        system: str | None = None,
    ) -> CompletionResult:
        """Let the model call `run_tool(name, arguments)` until it answers.

        `messages` is the conversation so far (alternating turns, ending with the user's), `system`
        the instructions. The caller's list is left as it is: the loop works on a copy.

        Tokens and cost are summed over every API call of the loop, so the job's
        recorded cost covers the whole exchange.
        """
        import anthropic

        client = anthropic.Anthropic(
            api_key=self.api_key, timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES
        )
        messages = list(messages)
        system_argument = {"system": system} if system else {}
        tally = UsageTally(self.model)
        logger.info(
            "boucle d'outils modèle=%s outils=%s\n--- system ---\n%s\n--- messages ---\n%s",
            self.model,
            ", ".join(tool["name"] for tool in tools),
            system or "(aucun)",
            "\n\n".join(f"{message['role']}: {message['content']}" for message in messages),
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
                **system_argument,
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

    def submit_batch(self, prompts: dict[str, Prompt], effort: str = "low") -> str:
        """Send `{custom_id: Prompt}` as one Message Batch (half price, asynchronous) and return its id.

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
                        "system": prompt.system,
                        "messages": prompt.messages,
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


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    provider = settings.llm_provider.strip().lower()

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY n'est pas configurée.")
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)

    raise RuntimeError(f"LLM_PROVIDER inconnu : {provider!r} (attendu 'anthropic').")
