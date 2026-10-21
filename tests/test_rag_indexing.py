from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.channel import Channel
from back.models.video import TranscriptStatus, Video
from back.models.video_note_chunk import VideoNoteChunk
from back.services.rag import indexing as rag_indexing
from back.services.rag.retrieval import count_indexed_videos


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def add_video(db, yt_video_id="abc123"):
    channel = Channel(url=f"https://example.test/{yt_video_id}", name="Chaîne test")
    video = Video(
        channel=channel,
        yt_video_id=yt_video_id,
        title="Vidéo test",
        url=f"https://youtube.com/watch?v={yt_video_id}",
        media_type="video",
        folder_path="/media/video",
        transcript_status=TranscriptStatus.downloaded,
    )
    db.add(video)
    db.commit()
    return video


def chunks_for(db, video_id):
    return (
        db.query(VideoNoteChunk)
        .filter(VideoNoteChunk.video_id == video_id)
        .order_by(VideoNoteChunk.id)
        .all()
    )


def test_index_video_notes_creates_one_chunk_per_non_empty_section(monkeypatch):
    db = make_session()
    monkeypatch.setattr(rag_indexing, "embed_texts", lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    video = add_video(db)

    rag_indexing.index_video_notes(
        db, video.id, "## Faits\n- Fait 1\n\n## Dates\nAucun élément identifié."
    )

    chunks = chunks_for(db, video.id)
    assert [chunk.section for chunk in chunks] == ["Faits"]
    assert chunks[0].content == "- Fait 1"
    assert chunks[0].embedding == [0.1, 0.2, 0.3]


def test_index_video_notes_replaces_existing_chunks_on_regeneration(monkeypatch):
    db = make_session()
    monkeypatch.setattr(rag_indexing, "embed_texts", lambda texts: [[0.0, 0.0, 0.0] for _ in texts])
    video = add_video(db)

    rag_indexing.index_video_notes(db, video.id, "## Faits\n- Ancien fait")
    rag_indexing.index_video_notes(db, video.id, "## Faits\n- Nouveau fait")

    chunks = chunks_for(db, video.id)
    assert len(chunks) == 1
    assert chunks[0].content == "- Nouveau fait"


def test_index_video_notes_with_only_empty_sections_creates_no_chunks_and_skips_embedding(
    monkeypatch,
):
    db = make_session()
    calls = []
    monkeypatch.setattr(rag_indexing, "embed_texts", lambda texts: calls.append(texts) or [])
    video = add_video(db)

    rag_indexing.index_video_notes(db, video.id, "## Faits\nAucun élément identifié.")

    assert chunks_for(db, video.id) == []
    assert calls == []  # no point calling the embedding model for zero chunks


def test_count_indexed_videos_counts_distinct_videos_with_chunks(monkeypatch):
    db = make_session()
    monkeypatch.setattr(rag_indexing, "embed_texts", lambda texts: [[0.0, 0.0, 0.0] for _ in texts])
    indexed_video = add_video(db, "abc123")
    add_video(db, "other")

    assert count_indexed_videos(db) == 0

    rag_indexing.index_video_notes(db, indexed_video.id, "## Faits\n- Un fait\n\n## Dates\n- 2026")

    # Two chunks from the same video still count as one indexed video.
    assert count_indexed_videos(db) == 1


def test_failed_embedding_keeps_the_previous_chunks(monkeypatch):
    db = make_session()
    monkeypatch.setattr(rag_indexing, "embed_texts", lambda texts: [[0.0, 0.0, 0.0] for _ in texts])
    video = add_video(db)
    rag_indexing.index_video_notes(db, video.id, "## Faits\n- Ancien fait")

    def failing(texts):
        raise rag_indexing.EmbeddingError("API down")

    monkeypatch.setattr(rag_indexing, "embed_texts", failing)
    try:
        rag_indexing.index_video_notes(db, video.id, "## Faits\n- Nouveau fait")
    except rag_indexing.EmbeddingError:
        pass

    assert [chunk.content for chunk in chunks_for(db, video.id)] == ["- Ancien fait"]


def test_backfill_indexes_videos_with_notes_and_no_chunks(monkeypatch, tmp_path):
    db = make_session()
    monkeypatch.setattr(rag_indexing, "embed_texts", lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    monkeypatch.setattr(
        rag_indexing, "get_settings", lambda: type("S", (), {"voyage_api_key": "pa-test"})()
    )
    monkeypatch.setattr(rag_indexing, "local_media_path", lambda stored: type(tmp_path)(stored))
    with_notes = add_video(db, "withnotes")
    without_notes = add_video(db, "nonotes")
    already = add_video(db, "already")
    for video, notes in ((with_notes, "## Faits\n- Fait"), (already, "## Faits\n- Autre")):
        folder = tmp_path / video.yt_video_id
        folder.mkdir()
        video.transcript_path = str(folder / "transcript.txt")
        (folder / "transcript.notes.txt").write_text(notes, encoding="utf-8")
    without_notes.transcript_path = str(tmp_path / "nonotes" / "transcript.txt")
    db.add(
        VideoNoteChunk(
            video_id=already.id, section="Faits", content="- Autre", embedding=[0.0, 0.0, 0.0]
        )
    )
    db.commit()

    assert rag_indexing.backfill_note_chunks(db) == 1

    assert [chunk.content for chunk in chunks_for(db, with_notes.id)] == ["- Fait"]
    assert chunks_for(db, without_notes.id) == []


def test_backfill_does_nothing_without_an_api_key(monkeypatch):
    db = make_session()
    monkeypatch.setattr(
        rag_indexing, "get_settings", lambda: type("S", (), {"voyage_api_key": ""})()
    )

    assert rag_indexing.backfill_note_chunks(db) == 0


def test_index_video_notes_embeds_the_section_with_its_video_and_channel(monkeypatch):
    db = make_session()
    embedded = []
    monkeypatch.setattr(
        rag_indexing,
        "embed_texts",
        lambda texts: embedded.extend(texts) or [[0.0, 0.0, 0.0] for _ in texts],
    )
    video = add_video(db)

    rag_indexing.index_video_notes(db, video.id, "## Faits\n- Fait 1")

    assert embedded == ["Vidéo test — Chaîne test — Faits\n- Fait 1"]
    # The stored content stays the bare text shown to the model.
    assert chunks_for(db, video.id)[0].content == "- Fait 1"


def test_index_video_notes_adds_a_chunk_for_the_short_summary(monkeypatch):
    db = make_session()
    embedded = []
    monkeypatch.setattr(
        rag_indexing,
        "embed_texts",
        lambda texts: embedded.extend(texts) or [[0.0, 0.0, 0.0] for _ in texts],
    )
    video = add_video(db)

    rag_indexing.index_video_notes(
        db, video.id, "## Faits\n- Fait 1", "  Le sujet en trois lignes.  "
    )

    assert [chunk.section for chunk in chunks_for(db, video.id)] == ["Faits", "Résumé"]
    assert chunks_for(db, video.id)[1].content == "Le sujet en trois lignes."
    assert embedded[1] == "Vidéo test — Chaîne test — Résumé\nLe sujet en trois lignes."


def test_backfill_notes_indexes_the_summary_file_next_to_the_notes(monkeypatch, tmp_path):
    db = make_session()
    monkeypatch.setattr(rag_indexing, "embed_texts", lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    monkeypatch.setattr(
        rag_indexing, "get_settings", lambda: type("S", (), {"voyage_api_key": "pa-test"})()
    )
    monkeypatch.setattr(rag_indexing, "local_media_path", lambda stored: type(tmp_path)(stored))
    video = add_video(db, "withsummary")
    (tmp_path / "withsummary").mkdir()
    video.transcript_path = str(tmp_path / "withsummary" / "transcript.txt")
    (tmp_path / "withsummary" / "transcript.notes.txt").write_text(
        "## Faits\n- Fait", encoding="utf-8"
    )
    (tmp_path / "withsummary" / "transcript.summary_short.txt").write_text(
        "Résumé court.", encoding="utf-8"
    )
    db.commit()

    assert rag_indexing.backfill_note_chunks(db) == 1

    assert [chunk.section for chunk in chunks_for(db, video.id)] == ["Faits", "Résumé"]


def test_backfill_summary_chunks_only_touches_indexed_videos_lacking_one(monkeypatch, tmp_path):
    db = make_session()
    monkeypatch.setattr(rag_indexing, "embed_texts", lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    monkeypatch.setattr(
        rag_indexing, "get_settings", lambda: type("S", (), {"voyage_api_key": "pa-test"})()
    )
    monkeypatch.setattr(rag_indexing, "local_media_path", lambda stored: type(tmp_path)(stored))
    needs = add_video(db, "needs")
    has_one = add_video(db, "hasone")
    no_file = add_video(db, "nofile")
    not_indexed = add_video(db, "notindexed")
    for video in (needs, has_one, no_file, not_indexed):
        folder = tmp_path / video.yt_video_id
        folder.mkdir()
        video.transcript_path = str(folder / "transcript.txt")
        (folder / "transcript.notes.txt").write_text("## Faits\n- Fait", encoding="utf-8")
        if video is not no_file:
            (folder / "transcript.summary_short.txt").write_text("Résumé court.", encoding="utf-8")
    for video in (needs, has_one, no_file):
        db.add(
            VideoNoteChunk(
                video_id=video.id, section="Faits", content="- Fait", embedding=[0.0, 0.0, 0.0]
            )
        )
    db.add(
        VideoNoteChunk(
            video_id=has_one.id, section="Résumé", content="Déjà là.", embedding=[0.0, 0.0, 0.0]
        )
    )
    db.commit()

    assert rag_indexing.backfill_summary_chunks(db) == 1

    assert [chunk.section for chunk in chunks_for(db, needs.id)] == ["Faits", "Résumé"]
    assert [chunk.content for chunk in chunks_for(db, has_one.id)] == ["- Fait", "Déjà là."]
    assert [chunk.section for chunk in chunks_for(db, no_file.id)] == ["Faits"]
    assert chunks_for(db, not_indexed.id) == []
