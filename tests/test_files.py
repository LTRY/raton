from app.models.channel import Channel
from app.models.video import TranscriptStatus
from app.services.common.files import sanitize_filename
from app.services.youtube import channel_info, downloads
from app.services.youtube.downloads import discover_downloaded_files, write_transcript


def test_sanitize_filename_removes_invalid_characters():
    assert sanitize_filename('A/B:C*D? "test"') == "A B C D test"


def test_sanitize_filename_fallback_for_empty_value():
    assert sanitize_filename("///") == "untitled"


def test_discover_downloaded_files_detects_audio(tmp_path):
    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"audio")

    files = discover_downloaded_files(tmp_path)

    assert files["audio_path"] == audio
    assert files["video_path"] is None


def test_write_transcript_converts_vtt_to_plain_text(tmp_path):
    subtitle = tmp_path / "subtitle.vtt"
    subtitle.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nBonjour\n\n"
        "00:00:01.000 --> 00:00:02.000\nle monde\n",
        encoding="utf-8",
    )

    transcript_path, status = write_transcript(tmp_path, subtitle)

    assert status == TranscriptStatus.downloaded
    assert transcript_path is not None
    assert transcript_path.read_text(encoding="utf-8") == "Bonjour\nle monde"


def test_write_transcript_dedupes_repeated_auto_caption_lines(tmp_path):
    subtitle = tmp_path / "subtitle.vtt"
    subtitle.write_text(
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.000\némission merci\n\n"
        "00:00:01.000 --> 00:00:02.000\némission merci\n\n"
        "00:00:02.000 --> 00:00:03.000\némission merci\n\n",
        encoding="utf-8",
    )

    transcript_path, status = write_transcript(tmp_path, subtitle)

    assert status == TranscriptStatus.downloaded
    assert transcript_path is not None
    assert transcript_path.read_text(encoding="utf-8") == "émission merci"


def test_download_media_configures_m4a_without_subtitles(monkeypatch, tmp_path):
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            return {"id": "test"}

    monkeypatch.setattr(downloads, "YoutubeDL", FakeYoutubeDL)

    downloads.download_media("https://example.com/video", tmp_path, "audio")

    assert captured["format"] == "bestaudio[ext=m4a]/bestaudio/best"
    assert "writesubtitles" not in captured
    assert "writeautomaticsub" not in captured
    assert captured["postprocessors"][0]["preferredcodec"] == "m4a"


def test_download_media_configures_ios_compatible_mp4(monkeypatch, tmp_path):
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            return {"id": "test"}

    monkeypatch.setattr(downloads, "YoutubeDL", FakeYoutubeDL)

    downloads.download_media("https://example.com/video", tmp_path, "video")

    assert "[ext=mp4]" in captured["format"]
    assert "[vcodec^=avc1]" in captured["format"]
    assert "bestaudio[ext=m4a]" in captured["format"]
    assert captured["merge_output_format"] == "mp4"


def test_download_subtitles_requests_the_original_track_not_a_translation(monkeypatch, tmp_path):
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            return {"id": "test"}

        def process_ie_result(self, info, download):
            return info

    monkeypatch.setattr(downloads, "YoutubeDL", FakeYoutubeDL)

    info = {"automatic_captions": {"fr": [], "fr-orig": [], "en": []}, "subtitles": {}}
    downloads.download_subtitles("https://example.com/video", tmp_path, info=info)

    assert captured["skip_download"] is True
    # The original track, never the auto-translated `en` (YouTube answers 429 to those).
    assert captured["subtitleslangs"] == ["fr-orig"]
    assert captured["writeautomaticsub"] is True and captured["writesubtitles"] is False


def test_download_thumbnail_skips_media_download(monkeypatch, tmp_path):
    captured = {}
    calls = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            calls["download"] = download
            return {"id": "test"}

    monkeypatch.setattr(downloads, "YoutubeDL", FakeYoutubeDL)

    downloads.download_thumbnail("https://example.com/video", tmp_path)

    assert captured["skip_download"] is True
    assert captured["writethumbnail"] is True
    assert calls["download"] is True


def test_list_channel_entries_uses_page_window(monkeypatch):
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            captured["url"] = url
            return {"entries": [{"id": "test"}]}

    monkeypatch.setattr(channel_info, "YoutubeDL", FakeYoutubeDL)

    entries = channel_info.list_channel_entries(
        Channel(url="https://example.test/channel", name="Test"),
        page=3,
        page_size=25,
    )

    assert entries == [{"id": "test"}]
    assert captured["url"] == "https://example.test/channel/videos"
    assert captured["playliststart"] == 51
    assert captured["playlistend"] == 75


def test_list_channel_entries_can_target_shorts_tab(monkeypatch):
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            captured["url"] = url
            return {"entries": [{"id": "short"}]}

    monkeypatch.setattr(channel_info, "YoutubeDL", FakeYoutubeDL)

    entries = channel_info.list_channel_entries(
        Channel(url="https://www.youtube.com/@test/videos", name="Test"),
        section="short",
    )

    assert entries == [{"id": "short"}]
    assert captured["url"] == "https://www.youtube.com/@test/shorts"


def test_choose_subtitle_track_never_picks_a_translation():
    choose = downloads.choose_subtitle_track

    # French video: the original auto caption, not the machine-translated "en".
    assert choose({"automatic_captions": {"fr-orig": [], "fr": [], "en": []}}) == ("fr-orig", False)
    # English video seen with a French translation next to it.
    assert choose({"automatic_captions": {"en-orig": [], "en": [], "fr": []}}) == ("en-orig", False)
    # Another language: its original track, even if neither fr nor en.
    assert choose({"automatic_captions": {"ar-orig": [], "ar": [], "fr": [], "en": []}}) == (
        "ar-orig",
        False,
    )
    # Creator subtitles in fr/en win over the auto caption.
    assert choose({"subtitles": {"en": []}, "automatic_captions": {"fr-orig": []}}) == ("en", True)
    # Only translations available: nothing to request.
    assert choose({"automatic_captions": {"fr": [], "en": []}}) is None
    assert choose({}) is None


def test_choose_subtitle_track_honours_the_manual_and_auto_switches():
    info = {"subtitles": {"fr": []}, "automatic_captions": {"fr-orig": []}}

    assert downloads.choose_subtitle_track(info, include_manual=False) == ("fr-orig", False)
    assert downloads.choose_subtitle_track(info, include_auto=False) == ("fr", True)


def test_download_subtitles_requests_nothing_when_the_video_has_no_original_track(
    monkeypatch, tmp_path
):
    class FakeYoutubeDL:
        def __init__(self, opts):
            raise AssertionError("no request expected")

    monkeypatch.setattr(downloads, "YoutubeDL", FakeYoutubeDL)

    downloads.download_subtitles(
        "https://example.com/video",
        tmp_path,
        info={"automatic_captions": {"fr": [], "en": []}, "subtitles": {}},
    )
