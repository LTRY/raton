import json
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.library_chat_message import LibraryChatMessage
from app.models.llm_job import LlmJob
from app.models.video import TranscriptStatus, Video
from app.services.jobs import backfills, llm_jobs
from app.services.llm.provider import CompletionResult
from app.services.rag import retrieval as rag_retrieval
from app.services.rag.library_chat_tools import LibraryChatToolbox
from app.services.rag.retrieval import RetrievedChunk
from app.services.youtube import channel_info
from app.web.routes import library_chat as library_chat_routes


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def add_video(db, title="Vidéo test", channel=None):
    channel = channel or Channel(url=f"https://example.test/{title}", name="Chaîne test")
    video = Video(
        channel=channel,
        yt_video_id=f"vid-{title}",
        title=title,
        url="https://youtube.com/watch?v=abc123",
        media_type="video",
        folder_path="/media/video",
        transcript_status=TranscriptStatus.downloaded,
    )
    db.add(video)
    db.commit()
    return video


def fake_provider(answer, tool_calls=()):
    """A provider whose model calls `tool_calls` in order, then says `answer`."""

    class FakeProvider:
        tool_outputs = []

        def complete_with_tools(self, prompt, tools, run_tool, max_tool_turns):
            self.tool_outputs.extend(run_tool(name, arguments) for name, arguments in tool_calls)
            return CompletionResult(
                text=answer, model="claude-haiku-4-5", input_tokens=40, output_tokens=12
            )

    return FakeProvider()


def ask(db, monkeypatch, provider, question="Une question ?"):
    # The post-chat profile backfill would reach YouTube and the real media root.
    monkeypatch.setattr(backfills, "run_channel_profile_backfill_job", lambda: None)
    monkeypatch.setattr(llm_jobs, "get_llm_provider", lambda: provider)
    monkeypatch.setattr(llm_jobs, "SessionLocal", lambda: db)
    response = library_chat_routes.chat_about_library(
        fetch_request("/chat"), BackgroundTasks(), question, db
    )
    job_id = json.loads(response.body)["job_id"]
    llm_jobs.run_llm_job(job_id)
    return json.loads(library_chat_routes.library_chat_job_status(job_id, db).body)


def fetch_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"x-requested-with", b"fetch")],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


def test_chat_about_library_queues_job_and_resolves_after_background_task(monkeypatch):
    db = make_session()
    video = add_video(db, "Stoïcisme et action")
    channel = video.channel

    retrieved = [
        RetrievedChunk(
            video_id=video.id,
            video_title=video.title,
            section="Concepts",
            content="- La dichotomie du contrôle",
            channel_id=channel.id,
            channel_name=channel.name,
        )
    ]
    monkeypatch.setattr(
        rag_retrieval, "retrieve_relevant_chunks", lambda db_arg, question: retrieved
    )

    provider = fake_provider(
        f"Chaîne test [chaine:{channel.id}] en parle dans Stoïcisme et action [video:{video.id}].",
        tool_calls=[("chercher_dans_les_notes", {"requete": "stoïcisme"})],
    )
    monkeypatch.setattr(llm_jobs, "get_llm_provider", lambda: provider)
    monkeypatch.setattr(llm_jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(backfills, "SessionLocal", lambda: db)

    scheduled = []
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        background_tasks,
        "add_task",
        lambda fn, *args, **kwargs: scheduled.append((fn, args, kwargs)),
    )

    response = library_chat_routes.chat_about_library(
        fetch_request("/chat"), background_tasks, "Qu'est-ce que le stoïcisme ?", db
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "queued"
    job_id = payload["job_id"]
    job = db.get(LlmJob, job_id)
    assert job.kind == "library_chat"
    assert job.video_id is None
    assert "Qu'est-ce que le stoïcisme ?" in job.prompt
    assert scheduled == [(llm_jobs.run_llm_job, (job_id,), {})]

    llm_jobs.run_llm_job(job_id)

    assert "dichotomie du contrôle" in provider.tool_outputs[0]

    resolved = library_chat_routes.library_chat_job_status(job_id, db)
    resolved_payload = json.loads(resolved.body)

    assert resolved_payload["status"] == "ok"
    assert resolved_payload["messages"] == [
        {
            "role": "user",
            "content": "Qu'est-ce que le stoïcisme ?",
            "channels": [],
            "citations": [],
        },
        {
            "role": "assistant",
            "content": "Chaîne test en parle dans Stoïcisme et action.",
            "channels": [{"channel_id": channel.id, "name": "Chaîne test"}],
            "citations": [{"video_id": video.id, "title": "Stoïcisme et action"}],
        },
    ]
    assert (
        resolved_payload["indexed_video_count"] == 0
    )  # no VideoNoteChunk rows actually created in this test
    assert resolved_payload["total_video_count"] == 1

    # Idempotent replay ("applied") must not duplicate messages.
    second = library_chat_routes.library_chat_job_status(job_id, db)
    assert json.loads(second.body)["messages"] == resolved_payload["messages"]


def test_chat_about_library_lists_channels_found_by_the_channel_tool(monkeypatch):
    db = make_session()
    cooking = Channel(
        url="https://example.test/cuisine",
        name="Les Pâtes de Léa",
        category_labels="Cuisine",
    )
    tech = Channel(
        url="https://example.test/tech",
        name="Atelier Python",
        category_labels="Tech",
    )
    db.add_all([cooking, tech])
    db.commit()

    provider = fake_provider(
        f"Tu suis Les Pâtes de Léa [chaine:{cooking.id}].",
        tool_calls=[("chercher_chaines", {"requete": "pates"}), ("chercher_chaines", {})],
    )
    payload = ask(db, monkeypatch, provider, "Quelle est ma chaîne de pâtes ?")

    accent_insensitive, everything = provider.tool_outputs
    assert f"[chaine:{cooking.id}] Les Pâtes de Léa" in accent_insensitive
    assert "Atelier Python" not in accent_insensitive
    assert "Atelier Python" in everything
    assert payload["messages"][1]["content"] == "Tu suis Les Pâtes de Léa."
    assert payload["messages"][1]["channels"] == [
        {"channel_id": cooking.id, "name": "Les Pâtes de Léa"}
    ]
    assert payload["messages"][1]["citations"] == []


def test_answer_cannot_cite_a_channel_or_video_no_tool_returned(monkeypatch):
    db = make_session()
    video = add_video(db, "Vidéo jamais cherchée")

    provider = fake_provider(
        f"Voir Chaîne test [chaine:{video.channel.id}] et [video:{video.id}] [video:9999]."
    )
    payload = ask(db, monkeypatch, provider)

    assert payload["messages"][1] == {
        "role": "assistant",
        "content": "Voir Chaîne test et.",
        "channels": [],
        "citations": [],
    }


def test_inline_references_stay_in_the_text_only_when_a_tool_returned_them():
    toolbox = LibraryChatToolbox(make_session())
    toolbox.channel_ids.update({3})
    toolbox.video_ids.update({7})

    text, sources = toolbox.extract_sources(
        "Regardez [[chaine:3|Léa Martin]], puis [[video:7|Pourquoi 7 ± 2 est faux]] "
        "et [[video:99|Titre inventé]] [video:7] [youtube:UCabc]."
    )

    assert (
        text
        == "Regardez [[chaine:3|Léa Martin]], puis [[video:7|Pourquoi 7 ± 2 est faux]] et Titre inventé."
    )
    assert sources == {"channel_ids": [3], "video_ids": [7]}


def test_inline_reference_label_may_contain_square_brackets():
    toolbox = LibraryChatToolbox(make_session())
    toolbox.video_ids.update({7, 8})

    text, sources = toolbox.extract_sources(
        "Voir [[video:7|[FR] Python [2024]]]. Puis [[video:8|Autre [FR] titre]] et [[video:99|[FR] Inventé]]."
    )

    assert (
        text
        == "Voir [[video:7|[FR] Python [2024]]]. Puis [[video:8|Autre [FR] titre]] et [FR] Inventé."
    )
    assert sources == {"channel_ids": [], "video_ids": [7, 8]}


def test_inline_reference_without_label_is_kept_when_backed_and_dropped_otherwise():
    toolbox = LibraryChatToolbox(make_session())
    toolbox.video_ids.update({7})

    text, sources = toolbox.extract_sources("Voir [[video:7]] et [[video:99]].")

    assert text == "Voir [[video:7]] et ."
    assert sources == {"channel_ids": [], "video_ids": [7]}


def test_reference_already_cited_in_the_history_stays_a_link():
    db = make_session()
    video = add_video(db, "Vidéo déjà citée")
    db.add(
        LibraryChatMessage(
            role="assistant",
            content="Voir.",
            sources=str(video.id),
            channel_sources=str(video.channel.id),
        )
    )
    db.commit()
    toolbox = LibraryChatToolbox(db)

    text, sources = toolbox.extract_sources(
        f"Reprenons [[video:{video.id}|Vidéo déjà citée]] de [[chaine:{video.channel.id}|Chaîne test]]."
    )

    assert (
        text
        == f"Reprenons [[video:{video.id}|Vidéo déjà citée]] de [[chaine:{video.channel.id}|Chaîne test]]."
    )
    assert sources == {"channel_ids": [video.channel.id], "video_ids": [video.id]}


def test_video_tool_searches_titles_and_restricts_to_a_channel():
    db = make_session()
    first = add_video(db, "Apprendre Python vite")
    other_channel = Channel(url="https://example.test/autre", name="Autre chaîne")
    second = add_video(db, "Python pour la data", channel=other_channel)
    add_video(db, "Recette de cuisine", channel=other_channel)
    toolbox = LibraryChatToolbox(db)

    everywhere = toolbox.run("chercher_videos", {"requete": "python"})
    assert f"[video:{first.id}]" in everywhere and f"[video:{second.id}]" in everywhere
    assert "Recette de cuisine" not in everywhere

    in_channel = toolbox.run(
        "chercher_videos", {"requete": "python", "chaine_id": other_channel.id}
    )
    assert f"[video:{second.id}]" in in_channel
    assert f"[video:{first.id}]" not in in_channel

    # No video holds both words: the search falls back to either word.
    partial = toolbox.run("chercher_videos", {"requete": "python recette"})
    assert "correspondances partielles" in partial
    assert "Recette de cuisine" in partial

    assert toolbox.run("chercher_videos", {}) == "Précise une requête ou un chaine_id."


def test_tool_failure_is_reported_to_the_model_instead_of_failing_the_job(monkeypatch):
    db = make_session()

    def broken(db_arg, question):
        raise RuntimeError("index indisponible")

    monkeypatch.setattr(rag_retrieval, "retrieve_relevant_chunks", broken)

    output = LibraryChatToolbox(db).run("chercher_dans_les_notes", {"requete": "sujet"})

    assert output == "Erreur de l'outil chercher_dans_les_notes : index indisponible"


def test_chat_about_library_rejects_empty_question(monkeypatch):
    db = make_session()
    response = library_chat_routes.chat_about_library(
        fetch_request("/chat"), BackgroundTasks(), "   ", db
    )
    payload = json.loads(response.body)

    assert response.status_code == 400
    assert payload["status"] == "failed"


def test_library_chat_payload_drops_chips_for_deleted_videos_and_channels(monkeypatch):
    db = make_session()
    video = add_video(db, "Vidéo temporaire")
    channel = video.channel
    provider = fake_provider(
        f"Chaîne test [chaine:{channel.id}], Vidéo temporaire [video:{video.id}].",
        tool_calls=[("chercher_videos", {"requete": "temporaire"})],
    )
    answered = ask(db, monkeypatch, provider)
    assert answered["messages"][1]["channels"] and answered["messages"][1]["citations"]

    db.delete(channel)  # cascades to its videos
    db.commit()

    message = library_chat_routes.library_chat_payload(db)["messages"][1]
    assert message["channels"] == []
    assert message["citations"] == []


def test_clear_library_chat_deletes_all_messages(monkeypatch):
    db = make_session()
    ask(db, monkeypatch, fake_provider("Réponse."))
    assert len(library_chat_routes.library_chat_payload(db)["messages"]) == 2

    cleared = library_chat_routes.clear_library_chat(db)
    assert json.loads(cleared.body)["messages"] == []
    assert library_chat_routes.library_chat_payload(db)["messages"] == []


def test_notes_search_keeps_at_most_two_chunks_per_video():
    def chunk(video_id, section):
        return RetrievedChunk(
            video_id=video_id, video_title=f"Vidéo {video_id}", section=section, content="-"
        )

    # Closest first: video 1 would otherwise take the first six places.
    nearest = [chunk(1, f"S{index}") for index in range(6)] + [
        chunk(video_id, "Faits") for video_id in range(2, 12)
    ]

    kept = rag_retrieval.diversify_chunks(nearest)

    assert [(item.video_id, item.section) for item in kept[:3]] == [
        (1, "S0"),
        (1, "S1"),
        (2, "Faits"),
    ]
    assert len(kept) == rag_retrieval.TOP_K_CHUNKS
    assert len({item.video_id for item in kept}) == 7


def youtube_candidates(*candidates):
    return [
        {
            "yt_channel_id": yt_channel_id,
            "name": name,
            "handle": handle,
            "url": f"https://www.youtube.com/{handle}",
            "subscriber_count": subscriber_count,
            "description": None,
            "thumbnail_url": None,
        }
        for yt_channel_id, name, handle, subscriber_count in candidates
    ]


def test_library_chat_adds_a_channel_found_on_youtube(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channel_info,
        "search_channels",
        lambda query: youtube_candidates(
            ("UCleo", "Léo Duff", "@LeoDuff", 822000), ("UCother", "Leo Duff", "@LeFohShow", 341)
        ),
    )
    provider = fake_provider(
        "J'ai ajouté Léo Duff [chaine:1] [youtube:UCleo] à votre bibliothèque.",
        tool_calls=[
            ("chercher_sur_youtube", {"requete": "Léo Duff"}),
            ("ajouter_chaine", {"youtube_id": "UCleo"}),
        ],
    )

    payload = ask(db, monkeypatch, provider, "Ajoute la chaîne de Léo Duff")

    assert "[youtube:UCleo] Léo Duff — @LeoDuff — 822000 abonné(s)" in provider.tool_outputs[0]
    assert (
        provider.tool_outputs[1]
        == "Chaîne ajoutée : [chaine:1] Léo Duff — @LeoDuff — 822000 abonné(s)"
    )
    channel = db.query(Channel).one()
    assert (channel.url, channel.name, channel.yt_channel_id, channel.rating) == (
        "https://www.youtube.com/@LeoDuff",
        "Léo Duff",
        "UCleo",
        1,
    )
    assert payload["messages"][-1] == {
        "role": "assistant",
        "content": "J'ai ajouté Léo Duff à votre bibliothèque.",
        "channels": [{"channel_id": channel.id, "name": "Léo Duff"}],
        "citations": [],
    }


def test_library_chat_cannot_add_a_channel_youtube_did_not_return(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channel_info,
        "search_channels",
        lambda query: youtube_candidates(("UCleo", "Léo Duff", "@LeoDuff", 822000)),
    )
    toolbox = LibraryChatToolbox(db)

    assert "Identifiant inconnu" in toolbox.run("ajouter_chaine", {"youtube_id": "UCleo"})
    toolbox.run("chercher_sur_youtube", {"requete": "Léo Duff"})
    assert "Identifiant inconnu" in toolbox.run("ajouter_chaine", {"youtube_id": "UCinvented"})
    assert db.query(Channel).count() == 0


def test_library_chat_does_not_duplicate_a_channel_already_in_the_library(monkeypatch):
    db = make_session()
    # Same YouTube channel, stored under its other URL form.
    known = Channel(
        url="https://www.youtube.com/channel/UCleo", name="Léo Duff", yt_channel_id="UCleo"
    )
    db.add(known)
    db.commit()
    monkeypatch.setattr(
        channel_info,
        "search_channels",
        lambda query: youtube_candidates(("UCleo", "Léo Duff", "@LeoDuff", 822000)),
    )
    toolbox = LibraryChatToolbox(db)

    assert f"déjà dans la bibliothèque [chaine:{known.id}]" in toolbox.run(
        "chercher_sur_youtube", {"requete": "Léo Duff"}
    )
    assert toolbox.run("ajouter_chaine", {"youtube_id": "[youtube:UCleo]"}) == (
        f"Déjà dans la bibliothèque : [chaine:{known.id}] Léo Duff"
    )
    assert db.query(Channel).count() == 1


def test_library_chat_backfills_profiles_once_after_the_job_is_done(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channel_info,
        "search_channels",
        lambda query: youtube_candidates(("UCleo", "Léo Duff", "@LeoDuff", 822000)),
    )
    provider = fake_provider(
        "Ajoutée.",
        tool_calls=[
            ("chercher_sur_youtube", {"requete": "Léo"}),
            ("ajouter_chaine", {"youtube_id": "UCleo"}),
        ],
    )
    statuses = []

    def record():
        db.rollback()  # only what was committed counts
        statuses.append(db.query(LlmJob).one().status)

    ask(db, monkeypatch, provider)  # builds the job and installs the no-op hook
    monkeypatch.setattr(llm_jobs, "run_channel_profile_backfill_job", record)
    job = db.query(LlmJob).one()
    job.status = "queued"
    db.query(Channel).delete()
    db.commit()
    provider.tool_outputs.clear()
    monkeypatch.setattr(
        channel_info,
        "search_channels",
        lambda query: youtube_candidates(("UCleo", "Léo Duff", "@LeoDuff", 822000)),
    )

    llm_jobs.run_llm_job(job.id)

    assert statuses == ["done"]


def test_library_chat_does_not_backfill_when_no_channel_was_added(monkeypatch):
    db = make_session()
    calls = []
    ask(db, monkeypatch, fake_provider("Rien à ajouter."))
    monkeypatch.setattr(backfills, "run_channel_profile_backfill_job", lambda: calls.append(1))
    job = db.query(LlmJob).one()
    job.status = "queued"
    db.commit()

    llm_jobs.run_llm_job(job.id)

    assert calls == []


def test_a_failing_post_chat_backfill_does_not_propagate(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        channel_info,
        "search_channels",
        lambda query: youtube_candidates(("UCleo", "Léo Duff", "@LeoDuff", 822000)),
    )
    provider = fake_provider(
        "Ajoutée.",
        tool_calls=[
            ("chercher_sur_youtube", {"requete": "Léo"}),
            ("ajouter_chaine", {"youtube_id": "UCleo"}),
        ],
    )
    ask(db, monkeypatch, provider)
    job = db.query(LlmJob).one()
    job.status = "queued"
    db.query(Channel).delete()
    db.commit()

    def boom():
        raise RuntimeError("youtube down")

    monkeypatch.setattr(backfills, "run_channel_profile_backfill_job", boom)

    llm_jobs.run_llm_job(job.id)  # must not raise

    assert db.query(LlmJob).one().status == "done"


def test_toolbox_records_a_label_then_a_result_for_each_tool_call(monkeypatch):
    db = make_session()
    db.add(Channel(url="https://example.test/underscore", name="Underscore_"))
    db.commit()
    seen = []
    toolbox = LibraryChatToolbox(
        db, on_progress=lambda steps: seen.append([dict(step) for step in steps])
    )

    toolbox.run("chercher_chaines", {"requete": "underscore"})
    toolbox.run("chercher_videos", {"requete": "reverse engineering"})

    assert seen[0] == [{"label": "Recherche de la chaîne « underscore »…", "result": None}]
    assert seen[1] == [
        {"label": "Recherche de la chaîne « underscore »…", "result": "Chaîne Underscore_ trouvée."}
    ]
    assert toolbox.steps[1] == {
        "label": "Recherche de vidéos « reverse engineering »…",
        "result": "Aucune vidéo trouvée.",
    }


def test_toolbox_step_result_says_the_nearest_channel_when_only_a_loose_match_exists():
    db = make_session()
    db.add(Channel(url="https://example.test/underscore", name="Underscore_"))
    db.commit()
    toolbox = LibraryChatToolbox(db)

    toolbox.run("chercher_chaines", {"requete": "underscore reverse"})

    assert toolbox.steps[0]["result"] == "Chaîne la plus proche : Underscore_."


def test_pending_job_status_exposes_the_tool_calls_made_so_far():
    db = make_session()
    job = LlmJob(
        kind="library_chat", provider="anthropic", prompt="p", question="q", status="running"
    )
    job.tool_calls = json.dumps([{"label": "Recherche dans les notes générées…", "result": None}])
    db.add(job)
    db.commit()

    payload = json.loads(library_chat_routes.library_chat_job_status(job.id, db).body)

    assert payload == {
        "status": "pending",
        "tool_calls": [{"label": "Recherche dans les notes générées…", "result": None}],
    }


def test_run_llm_job_stores_the_tool_calls_of_a_library_chat(monkeypatch):
    db = make_session()
    monkeypatch.setattr(rag_retrieval, "retrieve_relevant_chunks", lambda db_arg, question: [])
    provider = fake_provider(
        "Rien.", tool_calls=[("chercher_dans_les_notes", {"requete": "reverse"})]
    )

    ask(db, monkeypatch, provider)

    assert json.loads(db.query(LlmJob).one().tool_calls) == [
        {"label": "Recherche dans les notes générées…", "result": "Aucun extrait pertinent."}
    ]


def test_notes_search_failing_to_embed_tells_the_model_and_does_not_fail_the_job(monkeypatch):
    from app.services.rag.embeddings import EmbeddingError

    db = make_session()

    def failing(db_arg, question):
        raise EmbeddingError("VOYAGE_API_KEY n'est pas configurée")

    monkeypatch.setattr(rag_retrieval, "retrieve_relevant_chunks", failing)
    provider = fake_provider(
        "Je ne peux pas chercher.", tool_calls=[("chercher_dans_les_notes", {"requete": "x"})]
    )

    ask(db, monkeypatch, provider)

    assert "VOYAGE_API_KEY" in provider.tool_outputs[0]
    assert db.query(LlmJob).one().status == "applied"


def add_playback(db, video, position, duration=600, created_at=None, title=None):
    job = DownloadJob(
        channel_id=video.channel_id if video else None,
        video_id=video.id if video else None,
        status="played",
        message=json.dumps(
            {
                "type": "playback",
                "action": "Lecture",
                "media_label": "vidéo",
                "position_seconds": position,
                "duration_seconds": duration,
                "watched_seconds": position,
                "title": title or (video.title if video else ""),
            }
        ),
    )
    if created_at:
        job.created_at = created_at
    db.add(job)
    db.commit()
    return job


def test_history_tool_lists_latest_playback_once_per_video_and_cites_it():
    db = make_session()
    seen = add_video(db, "Vidéo vue deux fois")
    unseen = add_video(db, "Jamais lue")
    old = add_video(db, "Très ancienne")
    add_playback(db, seen, 100, created_at=datetime.now(UTC) - timedelta(hours=2))
    add_playback(db, seen, 600, created_at=datetime.now(UTC) - timedelta(hours=1))
    add_playback(db, old, 50, created_at=datetime.now(UTC) - timedelta(days=90))
    toolbox = LibraryChatToolbox(db)

    output = toolbox.run("consulter_historique", {})

    assert output.count(f"[video:{seen.id}]") == 1
    assert "terminée" in output
    assert f"[video:{unseen.id}]" not in output
    assert f"[video:{old.id}]" not in output
    assert seen.id in toolbox.video_ids

    wide = toolbox.run("consulter_historique", {"jours": 365})
    assert f"[video:{old.id}]" in wide
    filtered = toolbox.run("consulter_historique", {"jours": 365, "requete": "ancienne"})
    assert f"[video:{old.id}]" in filtered and f"[video:{seen.id}]" not in filtered


def test_history_tool_reports_an_empty_history():
    toolbox = LibraryChatToolbox(make_session())

    assert "Aucune lecture" in toolbox.run("consulter_historique", {})
