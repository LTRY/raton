import socket
import urllib.request

import pytest

from back.services.channels import profile as channel_profile
from back.services.youtube import channel_info
from back.services.youtube.url_guard import UnsafeUrlError, ensure_public_http_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/",
        "http://localhost/admin",
        "http://192.168.1.1/",
        "http://10.0.0.5/x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "file:///etc/passwd",
        "ftp://example.org/x",
        "http:///nohost",
    ],
)
def test_private_or_non_http_urls_are_refused(url):
    with pytest.raises(UnsafeUrlError):
        ensure_public_http_url(url)


def test_public_address_is_accepted():
    url = "https://www.youtube.com/@Fireship"
    assert ensure_public_http_url(url) == url
    assert ensure_public_http_url("https://93.184.216.34/x")


def test_name_resolving_to_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 0, 0, "", ("10.1.2.3", 0))]
    )
    with pytest.raises(UnsafeUrlError):
        ensure_public_http_url("http://internal.example/")


def test_unresolvable_host_is_left_to_the_fetcher(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert ensure_public_http_url("https://nowhere.invalid/x")


def test_channel_url_to_a_private_host_is_not_resolved():
    with pytest.raises(channel_info.ChannelNotFoundError):
        channel_info.resolve_channel_url("http://192.168.1.1/@x")


def test_image_fetch_refuses_a_private_url():
    with pytest.raises(UnsafeUrlError):
        channel_profile.fetch_image_bytes("http://127.0.0.1/avatar.png")


def test_image_redirect_to_a_private_address_is_refused():
    handler = channel_profile._PublicRedirectHandler()
    request = urllib.request.Request("https://93.184.216.34/a.png")
    with pytest.raises(UnsafeUrlError):
        handler.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1/secret")
