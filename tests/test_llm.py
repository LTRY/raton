import anthropic
import pytest

from app.services.llm import provider as llm
from app.services.llm.prompts import (
    NOTES_SECTION_NAMES,
    build_generation_prompt,
    build_notes_prompt,
    build_summary_prompt,
    build_video_analysis_prompt,
    partial_generation_summary,
    split_generation_result,
    split_notes_sections,
    split_summary_result,
    split_video_analysis_result,
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


def test_build_summary_prompt_includes_all_three_headers():
    prompt = build_summary_prompt("Transcript ici.")

    assert "## Résumé court" in prompt
    assert "## Résumé complet" in prompt
    assert "## Questions suggérées" in prompt
    assert "Transcript ici." in prompt


def test_split_summary_result_parses_short_full_and_questions():
    text = (
        "## Résumé court\nLigne 1.\nLigne 2.\nLigne 3.\n\n"
        "## Résumé complet\nRésumé du contenu.\n\n- Point clé 1\n\n"
        "## Questions suggérées\n- Question A ?\n- Question B ?\n* Question C ?"
    )

    short, full, questions = split_summary_result(text)

    assert short == "Ligne 1.\nLigne 2.\nLigne 3."
    assert full == "Résumé du contenu.\n\n- Point clé 1"
    assert questions == ["Question A ?", "Question B ?", "Question C ?"]


def test_split_summary_result_falls_back_without_questions_header():
    text = "## Résumé court\nLigne 1.\n\n## Résumé complet\nRésumé complet."

    short, full, questions = split_summary_result(text)

    assert short == "Ligne 1."
    assert full == "Résumé complet."
    assert questions == []


def test_split_summary_result_falls_back_without_any_header():
    short, full, questions = split_summary_result("Juste du texte libre.")

    assert short == ""
    assert full == "Juste du texte libre."
    assert questions == []


def test_build_video_analysis_prompt_includes_clickbait_section_when_has_image():
    prompt = build_video_analysis_prompt("Transcript ici.", "Titre vidéo", has_image=True)

    assert "## Score clickbait" in prompt
    assert "## Pertinence du contenu" in prompt
    assert "## Suggestions" in prompt
    assert "Titre vidéo" in prompt
    assert "Transcript ici." in prompt


def test_build_video_analysis_prompt_omits_clickbait_section_without_image():
    prompt = build_video_analysis_prompt("Transcript ici.", "Titre vidéo", has_image=False)

    assert "## Score clickbait" not in prompt
    assert "## Pertinence du contenu" in prompt
    assert "## Suggestions" in prompt


def test_split_video_analysis_result_parses_all_sections_with_image():
    text = (
        "## Score clickbait\nScore : 7/10\nJustification : Le titre exagère un peu.\n\n"
        "## Pertinence du contenu\nContenu utile : 65%\nJustification : Beaucoup d'intro.\n\n"
        "## Suggestions\nTitre 1 : Un titre plus fidèle\nTitre 2 : Un autre angle\n"
        "Titre 3 : Encore un titre\nCatégories : Tech, Actualité"
    )

    result = split_video_analysis_result(text, has_image=True)

    assert result == {
        "clickbait_score": 7,
        "clickbait_rationale": "Le titre exagère un peu.",
        "relevance_percent": 65,
        "relevance_rationale": "Beaucoup d'intro.",
        "suggested_titles": ["Un titre plus fidèle", "Un autre angle", "Encore un titre"],
        "suggested_categories": ["Tech", "Actualité"],
    }


def test_split_video_analysis_result_ignores_clickbait_section_without_image():
    text = (
        "## Score clickbait\nScore : 7/10\nJustification : Ignoré.\n\n"
        "## Pertinence du contenu\nContenu utile : 65%\nJustification : Beaucoup d'intro.\n\n"
        "## Suggestions\nTitre 1 : Un titre plus fidèle\nCatégories : Tech"
    )

    result = split_video_analysis_result(text, has_image=False)

    assert "clickbait_score" not in result
    assert "clickbait_rationale" not in result
    assert result["relevance_percent"] == 65
    assert result["suggested_titles"] == ["Un titre plus fidèle"]
    assert result["suggested_categories"] == ["Tech"]


def test_split_video_analysis_result_returns_empty_dict_without_any_header():
    assert split_video_analysis_result("Juste du texte libre.", has_image=True) == {}


def test_split_video_analysis_result_omits_malformed_relevance_section():
    text = "## Pertinence du contenu\nPas le bon format ici.\n\n## Suggestions\nTitre 1 : X\nCatégories : Y"

    result = split_video_analysis_result(text, has_image=False)

    assert "relevance_percent" not in result
    assert "relevance_rationale" not in result
    assert result["suggested_titles"] == ["X"]


def test_split_video_analysis_result_handles_partial_suggested_titles():
    text = "## Suggestions\nTitre 1 : Seul titre proposé\nCatégories : Tech"

    result = split_video_analysis_result(text, has_image=False)

    assert result["suggested_titles"] == ["Seul titre proposé"]


def test_split_video_analysis_result_omits_suggested_titles_when_absent():
    text = "## Suggestions\nCatégories : Tech"

    result = split_video_analysis_result(text, has_image=False)

    assert "suggested_titles" not in result


def test_split_video_analysis_result_caps_suggested_titles_at_three():
    text = (
        "## Suggestions\nTitre 1 : Un\nTitre 2 : Deux\nTitre 3 : Trois\n"
        "Titre 4 : Quatre\nCatégories : Tech"
    )

    result = split_video_analysis_result(text, has_image=False)

    assert result["suggested_titles"] == ["Un", "Deux", "Trois"]


def test_build_generation_prompt_includes_all_three_top_level_sections_once():
    prompt = build_generation_prompt("Transcript ici.", "Titre vidéo", has_image=False)

    assert prompt.count("Transcript ici.") == 1  # sent once, not once per document
    assert "# Notes" in prompt
    assert "# Résumé" in prompt
    assert "# Analyse" in prompt
    for name in NOTES_SECTION_NAMES:
        assert f"## {name}" in prompt
    assert "## Résumé complet" in prompt
    assert "## Pertinence du contenu" in prompt
    assert "Titre vidéo" in prompt
    assert "## Score clickbait" not in prompt


def test_build_generation_prompt_asks_for_the_summary_first():
    # The résumé is what the page shows while the completion streams.
    prompt = build_generation_prompt("Transcript ici.", "Titre vidéo", has_image=False)

    assert (
        prompt.index("\n# Résumé\n") < prompt.index("\n# Notes\n") < prompt.index("\n# Analyse\n")
    )


def test_partial_generation_summary_is_empty_before_the_summary_starts():
    assert partial_generation_summary("") == ("", "")
    assert partial_generation_summary("# Résu") == ("", "")
    assert partial_generation_summary("# Résumé\n## Résumé court") == ("", "")


def test_partial_generation_summary_follows_the_text_as_it_streams():
    text = (
        "# Résumé\n## Résumé court\nLigne 1.\nLigne 2.\n\n"
        "## Résumé complet\nPremier paragraphe.\n\n- Point clé\n\n"
        "## Questions suggérées\n- Question ?\n\n"
        "# Notes\n## Faits\n- Fait 1"
    )

    assert partial_generation_summary(text[: text.index("Ligne 2.")]) == ("Ligne 1.", "")
    assert partial_generation_summary(text[: text.index("paragraphe")]) == (
        "Ligne 1.\nLigne 2.",
        "Premier",
    )
    assert partial_generation_summary(text) == (
        "Ligne 1.\nLigne 2.",
        "Premier paragraphe.\n\n- Point clé",
    )


def test_partial_generation_summary_only_ever_grows():
    # A header still being written must never show up as résumé text.
    text = (
        "# Résumé\n## Résumé court\nLigne 1.\n\n## Résumé complet\nParagraphe.\n\n"
        "## Questions suggérées\n- Question ?\n\n# Notes\n## Faits\n- Fait"
    )
    previous = ("", "")
    for end in range(len(text) + 1):
        current = partial_generation_summary(text[:end])
        assert current[0].startswith(previous[0])
        assert current[1].startswith(previous[1])
        previous = current
    assert previous == ("Ligne 1.", "Paragraphe.")


def test_build_generation_prompt_includes_clickbait_section_when_has_image():
    prompt = build_generation_prompt("Transcript ici.", "Titre vidéo", has_image=True)

    assert "## Score clickbait" in prompt


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
        "## Résumé complet\nRésumé du contenu.\n\n"
        "## Questions suggérées\n- Question A ?\n\n"
        "# Analyse\n"
        "## Score clickbait\nScore : 7/10\nJustification : Un peu exagéré.\n\n"
        "## Pertinence du contenu\nContenu utile : 65%\nJustification : Beaucoup d'intro.\n\n"
        "## Suggestions\nTitre 1 : Un titre plus fidèle\nCatégories : Tech"
    )

    result = split_generation_result(text, has_image=True)

    assert "## Faits\n- Fait 1" in result["notes_text"]
    assert result["summary_short"] == "Ligne 1.\nLigne 2.\nLigne 3."
    assert result["summary_full"] == "Résumé du contenu."
    assert result["summary_questions"] == ["Question A ?"]
    assert result["analysis"]["clickbait_score"] == 7
    assert result["analysis"]["relevance_percent"] == 65
    assert result["analysis"]["suggested_titles"] == ["Un titre plus fidèle"]


def test_split_generation_result_degrades_gracefully_without_any_top_level_header():
    result = split_generation_result("Juste du texte libre.", has_image=False)

    assert result == {
        "notes_text": "",
        "summary_short": "",
        "summary_full": "",
        "summary_questions": [],
        "analysis": {},
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
    image_deltas = []
    provider.complete_with_image(
        "Décris.", b"fake-bytes", "image/jpeg", on_text=image_deltas.append
    )

    assert result.text == "Réponse générée."
    assert deltas == image_deltas == ["Rép", "onse générée."]


def test_complete_with_image_returns_completion_result(monkeypatch):
    response = _FakeAnthropicResponse("Réponse générée.", input_tokens=10, output_tokens=20)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: _FakeAnthropicClient(response))

    provider = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-5")
    result = provider.complete_with_image("Décris cette image.", b"fake-bytes", "image/jpeg")

    assert result.text == "Réponse générée."
    assert result.model == "claude-sonnet-5"
    assert result.input_tokens == 10
    assert result.output_tokens == 20


def test_complete_with_image_sends_image_block_before_text(monkeypatch):
    response = _FakeAnthropicResponse("ok")
    fake_client_holder = {}

    def make_client(**kwargs):
        client = _FakeAnthropicClient(response)
        fake_client_holder["client"] = client
        return client

    monkeypatch.setattr(anthropic, "Anthropic", make_client)

    provider = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-5")
    provider.complete_with_image("Un prompt.", b"\x89PNG", "image/png")

    messages = fake_client_holder["client"].messages.stream_kwargs["messages"]
    content = messages[0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["type"] == "base64"
    assert content[0]["source"]["media_type"] == "image/png"
    assert content[1] == {"type": "text", "text": "Un prompt."}


def test_complete_with_image_raises_on_max_tokens(monkeypatch):
    response = _FakeAnthropicResponse("tronqué", stop_reason="max_tokens")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: _FakeAnthropicClient(response))

    provider = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-5")
    with pytest.raises(RuntimeError, match="tronquée"):
        provider.complete_with_image("prompt", b"bytes", "image/jpeg")


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


def test_complete_with_image_raises_on_empty_response(monkeypatch):
    response = _FakeAnthropicResponse("")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: _FakeAnthropicClient(response))

    provider = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-5")
    with pytest.raises(RuntimeError, match="aucune réponse"):
        provider.complete_with_image("prompt", b"bytes", "image/jpeg")


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
