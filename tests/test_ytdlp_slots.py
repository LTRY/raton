"""Only a few yt-dlp calls run at once, whatever started them: YouTube answers 429 to a burst."""

import threading
import time

from back.services.youtube import yt


def run_calls(count: int, **call_options) -> int:
    """Run `count` calls at once, each holding its slot a moment; returns the most that overlapped."""
    inside = 0
    peak = 0
    lock = threading.Lock()

    def call():
        nonlocal inside, peak
        with yt.ytdlp_call("test", **call_options):
            with lock:
                inside += 1
                peak = max(peak, inside)
            time.sleep(0.05)
            with lock:
                inside -= 1

    threads = [threading.Thread(target=call) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return peak


def test_requests_share_a_few_slots():
    assert run_calls(yt.MAX_CONCURRENT_REQUESTS * 3) == yt.MAX_CONCURRENT_REQUESTS


def test_media_downloads_have_fewer_slots_of_their_own():
    assert run_calls(yt.MAX_CONCURRENT_DOWNLOADS * 3, media=True) == yt.MAX_CONCURRENT_DOWNLOADS


def test_a_download_does_not_keep_a_request_waiting(monkeypatch):
    monkeypatch.setattr(yt, "_download_slots", threading.BoundedSemaphore(1))
    release = threading.Event()
    started = threading.Event()

    def long_download():
        with yt.ytdlp_call("download", media=True):
            started.set()
            release.wait(5)

    thread = threading.Thread(target=long_download)
    thread.start()
    started.wait(5)
    try:
        assert (
            run_calls(1) == 1
        )  # a metadata request goes through while the download holds its slot
    finally:
        release.set()
        thread.join()


def test_a_slot_is_given_back_when_the_call_fails():
    for _ in range(yt.MAX_CONCURRENT_REQUESTS + 1):
        try:
            with yt.ytdlp_call("test"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass

    assert run_calls(1) == 1


def test_a_long_wait_is_written_to_the_journal(monkeypatch):
    events = []
    monkeypatch.setattr(yt, "SLOT_WAIT_LOGGED_AFTER_SECONDS", 0.0)
    monkeypatch.setattr(yt, "log_event", lambda logger, event, **fields: events.append(event))

    with yt.ytdlp_call("test"):
        pass

    assert events == ["ytdlp.waited"]
