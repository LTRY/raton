import anthropic
import pytest

from app.services.llm import provider as llm
from app.services.llm.prompts import (
    NOTES_SECTION_NAMES,
    NOTES_SECTIONS,
    build_auto_notes_prompt,
    build_generation_prompt,
    build_notes_prompt,
    build_summary_prompt,
    partial_generation_summary,
    split_generation_result,
    split_notes_sections,
    split_summary_result,
)
from app.services.llm.provider import AnthropicProvider, CompletionFailed, get_llm_provider
from app.services.videos.documents import load_chat, save_chat


def test_save_and_load_chat_roundtrip(tmp_path):
    path = tmp_path / "chat.json"
    messages = [
        {"role": "user", "content": "Question ?"},
        {"role": "assistant", "content": "Réponse."},
    ]

    save_chat(path, messages)

    assert load_chat(path) == messages


def test_load_chat_ignores_invalid_messages(tmp_path):
    path = tmp_path / "chat.json"
    path.write_text(
        '[{"role":"system","content":"x"},{"role":"user","content":"ok"},{"role":"assistant","content":42}]',
        encoding="utf-8",
    )

    assert load_chat(path) == [{"role": "user", "content": "ok"}]


class _FakeSettings:
    def __init__(self, **overrides):
        self.llm_provider = "anthropic"
        self.anthropic_api_key = ""
        self.anthropic_model = "claude-sonnet-5"
        for key, value in overrides.items():
            setattr(self, key, value)


def test_get_llm_provider_returns_anthropic_by_default(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: _FakeSettings(anthropic_api_key="sk-ant-test"))

    provider = get_llm_provider()

    assert isinstance(provider, AnthropicProvider)
    assert provider.api_key == "sk-ant-test"
    assert provider.model == "claude-sonnet-5"


def test_get_llm_provider_requires_anthropic_api_key(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: _FakeSettings())

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        get_llm_provider()


def test_get_llm_provider_rejects_unknown_provider(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: _FakeSettings(llm_provider="mistral"))

    with pytest.raises(RuntimeError, match="LLM_PROVIDER inconnu"):
        get_llm_provider()


def test_build_notes_prompt_includes_all_section_headers():
    prompt = build_notes_prompt("Transcript ici.")

    for name in NOTES_SECTION_NAMES:
        assert f"## {name}" in prompt
    assert "Transcript ici." in prompt


def test_split_notes_sections_parses_all_headers_and_skips_empty_ones():
    text = (
        "## Faits\n- Fait 1\n- Fait 2\n\n"
        "## Dates\nAucun élément identifié.\n\n"
        "## Lieux\n- Paris\n\n"
        "## Acteurs\nAucun élément identifié.\n\n"
        "## Concepts\n- Concept X\n\n"
        "## Relations causales\n- A cause B"
    )

    assert split_notes_sections(text) == [
        ("Faits", "- Fait 1\n- Fait 2"),
        ("Lieux", "- Paris"),
        ("Concepts", "- Concept X"),
        ("Relations causales", "- A cause B"),
    ]


def test_split_notes_sections_falls_back_to_single_chunk_without_headers():
    assert split_notes_sections("Juste du texte libre, sans titres Markdown.") == [
        ("Notes", "Juste du texte libre, sans titres Markdown.")
    ]


def test_split_notes_sections_returns_nothing_for_blank_text():
    assert split_notes_sections("   ") == []


def test_build_summary_prompt_includes_both_headers_and_no_full_summary():
    prompt = build_summary_prompt("Transcript ici.")

    assert "## Résumé court" in prompt
    assert "Résumé complet" not in prompt
    assert "## Questions suggérées" in prompt
    assert "Transcript ici." in prompt


def test_split_summary_result_parses_short_and_questions():
    text = (
        "## Résumé court\nLigne 1.\nLigne 2.\nLigne 3.\n\n"
        "## Questions suggérées\n- Question A ?\n- Question B ?\n* Question C ?"
    )

    short, questions = split_summary_result(text)

    assert short == "Ligne 1.\nLigne 2.\nLigne 3."
    assert questions == ["Question A ?", "Question B ?", "Question C ?"]


def test_split_summary_result_falls_back_without_questions_header():
    short, questions = split_summary_result("## Résumé court\nLigne 1.")

    assert short == "Ligne 1."
    assert questions == []


def test_split_summary_result_falls_back_without_any_header():
    short, questions = split_summary_result("Juste du texte libre.")

    assert short == "Juste du texte libre."
    assert questions == []


def test_build_generation_prompt_includes_both_top_level_sections_once():
    prompt = build_generation_prompt("Transcript ici.")

    assert prompt.count("Transcript ici.") == 1  # sent once, not once per document
    assert "# Notes" in prompt
    assert "# Résumé" in prompt
    for name in NOTES_SECTION_NAMES:
        assert f"## {name}" in prompt
    assert "## Questions suggérées" in prompt
    assert "Résumé complet" not in prompt
    assert "# Analyse" not in prompt
    assert "## Pertinence du contenu" not in prompt
    assert "## Score clickbait" not in prompt


def test_build_generation_prompt_asks_for_the_summary_first():
    # The résumé is what the page shows while the completion streams.
    prompt = build_generation_prompt("Transcript ici.")

    assert prompt.index("\n# Résumé\n") < prompt.index("\n# Notes\n")


def test_combined_prompts_state_the_nothing_before_the_first_title_rule_once():
    # Nested copies of the rule contradicted the level-1 titles (a "## Notes" came back once).
    for prompt in (build_generation_prompt("T."), build_auto_notes_prompt("T.")):
        assert prompt.count("rien d'autre avant le premier titre") == 1


def test_notes_prompt_defines_every_section_and_keeps_bullets_self_contained():
    prompt = build_notes_prompt("T.")

    assert set(NOTES_SECTIONS) == set(NOTES_SECTION_NAMES)
    for name, definition in NOTES_SECTIONS.items():
        assert f"- {name} : {definition}" in prompt
    assert "se comprend seule" in prompt


def test_partial_generation_summary_is_empty_before_the_summary_starts():
    assert partial_generation_summary("") == ""
    assert partial_generation_summary("# Résu") == ""
    assert partial_generation_summary("# Résumé\n## Résumé court") == ""


def test_partial_generation_summary_follows_the_text_as_it_streams():
    text = (
        "# Résumé\n## Résumé court\nLigne 1.\nLigne 2.\n\n"
        "## Questions suggérées\n- Question ?\n\n"
        "# Notes\n## Faits\n- Fait 1"
    )

    assert partial_generation_summary(text[: text.index("Ligne 2.")]) == "Ligne 1."
    assert partial_generation_summary(text[: text.index("Ligne 2.") + 5]) == "Ligne 1.\nLigne"
    assert partial_generation_summary(text) == "Ligne 1.\nLigne 2."


def test_partial_generation_summary_only_ever_grows():
    # A header still being written must never show up as résumé text.
    text = (
        "# Résumé\n## Résumé court\nLigne 1.\nLigne 2.\n\n"
        "## Questions suggérées\n- Question ?\n\n# Notes\n## Faits\n- Fait"
    )
    previous = ""
    for end in range(len(text) + 1):
        current = partial_generation_summary(text[:end])
        assert current.startswith(previous)
        previous = current
    assert previous == "Ligne 1.\nLigne 2."


def test_split_generation_result_delegates_to_each_single_purpose_splitter():
    text = (
        "# Notes\n"
        "## Faits\n- Fait 1\n\n"
        "## Dates\nAucun élément identifié.\n\n"
        "## Lieux\nAucun élément identifié.\n\n"
        "## Acteurs\nAucun élément identifié.\n\n"
        "## Concepts\nAucun élément identifié.\n\n"
        "## Relations causales\nAucun élément identifié.\n\n"
        "# Résumé\n"
        "## Résumé court\nLigne 1.\nLigne 2.\nLigne 3.\n\n"
        "## Questions suggérées\n- Question A ?\n"
    )

    result = split_generation_result(text)

    assert "## Faits\n- Fait 1" in result["notes_text"]
    assert result["summary_short"] == "Ligne 1.\nLigne 2.\nLigne 3."
    assert result["summary_questions"] == ["Question A ?"]


def test_split_generation_result_degrades_gracefully_without_any_top_level_header():
    result = split_generation_result("Juste du texte libre.")

    assert result == {
        "notes_text": "",
        "summary_short": "",
        "summary_questions": [],
    }


class _FakeContentBlock:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class _FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeAnthropicResponse:
    def __init__(self, text, stop_reason="end_turn", input_tokens=10, output_tokens=20):
        self.stop_reason = stop_reason
        self.content = [_FakeContentBlock("text", text)]
        self.usage = _FakeUsage(input_tokens, output_tokens)


class _FakeStream:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_final_message(self):
        return self._response

    @property
    def text_stream(self):
        text = self._response.content[0].text
        return iter([text[:3], text[3:]])


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.stream_kwargs = None

    def stream(self, **kwargs):
        self.stream_kwargs = kwargs
        return _FakeStream(self._response)


class _FakeAnthropicClient:
    def __init__(self, response, **_kwargs):
        self.messages = _FakeMessages(response)


def test_complete_forwards_text_deltas_to_on_text(monkeypatch):
    response = _FakeAnthropicResponse("Réponse générée.")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: _FakeAnthropicClient(response))
    provider = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-5")

    deltas = []
    result = provider.complete("Résume.", on_text=deltas.append)

    assert result.text == "Réponse générée."
    assert deltas == ["Rép", "onse générée."]


def test_complete_reports_per_call_cost_and_total_prompt_tokens(monkeypatch):
    response = _FakeAnthropicResponse("ok", input_tokens=1_000_000, output_tokens=1_000_000)
    response.usage.cache_read_input_tokens = 500_000
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: _FakeAnthropicClient(response))

    result = AnthropicProvider(api_key="sk-ant-test", model="claude-haiku-4-5").complete("prompt")

    assert result.input_tokens == 1_500_000  # uncached + cache reads
    assert result.cost_usd == pytest.approx(1.0 + 5.0 + 0.5 * 0.10)


def test_complete_uses_the_model_output_ceiling(monkeypatch):
    holder = {}

    def make_client(**kwargs):
        holder["client"] = _FakeAnthropicClient(_FakeAnthropicResponse("ok"))
        return holder["client"]

    monkeypatch.setattr(anthropic, "Anthropic", make_client)

    AnthropicProvider(api_key="sk-ant-test", model="claude-haiku-4-5").complete("p")
    assert holder["client"].messages.stream_kwargs["max_tokens"] == 64_000
    AnthropicProvider(api_key="sk-ant-test", model="claude-haiku-5-5").complete("p")
    assert holder["client"].messages.stream_kwargs["max_tokens"] == 128_000


def test_truncated_response_keeps_its_billed_usage(monkeypatch):
    response = _FakeAnthropicResponse(
        "tronqué", stop_reason="max_tokens", input_tokens=1_000_000, output_tokens=200_000
    )
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: _FakeAnthropicClient(response))

    with pytest.raises(CompletionFailed) as excinfo:
        AnthropicProvider(api_key="sk-ant-test", model="claude-haiku-4-5").complete("p")

    assert excinfo.value.usage.output_tokens == 200_000
    assert excinfo.value.usage.cost_usd == pytest.approx(2.0)


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, block_id, name, tool_input):
        self.id = block_id
        self.name = name
        self.input = tool_input


class _ScriptedMessages:
    """Replays one response per API call, a tool call as long as it is allowed to."""

    def __init__(self, final_text):
        self.final_text = final_text
        self.tool_choices = []
        self.last_messages = None

    def stream(self, **kwargs):
        self.tool_choices.append(kwargs["tool_choice"]["type"])
        self.last_messages = kwargs["messages"]
        if kwargs["tool_choice"]["type"] == "none":
            return _FakeStream(
                _FakeAnthropicResponse(self.final_text, input_tokens=5, output_tokens=7)
            )
        response = _FakeAnthropicResponse(
            "", stop_reason="tool_use", input_tokens=5, output_tokens=7
        )
        call_number = len(self.tool_choices)
        response.content = [
            _FakeToolUseBlock(
                f"call-{call_number}", "chercher_chaines", {"requete": f"q{call_number}"}
            )
        ]
        return _FakeStream(response)


def test_complete_with_tools_feeds_tool_results_back_and_stops_at_the_turn_budget(
    monkeypatch, caplog
):
    caplog.set_level("INFO", logger="raton.llm")
    scripted = _ScriptedMessages("Réponse finale.")
    monkeypatch.setattr(
        anthropic, "Anthropic", lambda **kwargs: type("Client", (), {"messages": scripted})()
    )
    calls = []

    def run_tool(name, arguments):
        calls.append((name, arguments))
        return f"résultat {len(calls)}"

    provider = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-5")
    result = provider.complete_with_tools(
        "Une question.", [{"name": "chercher_chaines"}], run_tool, max_tool_turns=2
    )

    # The model would call tools forever: the third call forbids them.
    assert scripted.tool_choices == ["auto", "auto", "none"]
    assert calls == [
        ("chercher_chaines", {"requete": "q1"}),
        ("chercher_chaines", {"requete": "q2"}),
    ]
    assert scripted.last_messages[-1] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call-2", "content": "résultat 2"}],
    }
    assert result.text == "Réponse finale."
    assert (result.input_tokens, result.output_tokens) == (15, 21)
    # The exchange is traced so it can be followed in the container logs.
    assert 'outil demandé : chercher_chaines({"requete": "q1"})' in caplog.text
    assert "résultat 1" in caplog.text
    assert "boucle terminée : 3 appel(s), tokens entrée=15 sortie=21" in caplog.text
