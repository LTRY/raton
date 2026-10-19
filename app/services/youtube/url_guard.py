"""Refuse URLs that point at the local machine or a private network (SSRF guard).

The app fetches user-supplied URLs (yt-dlp, channel images). Without a check, a URL such as
`http://192.168.1.1/` or `http://localhost:5432/` makes the server query services that the person who
typed it could not reach. Only addresses that are globally routable are accepted.

A host that does not resolve is let through: the fetcher fails on its own. A name resolving to a public
address at check time and to a private one later (DNS rebinding) is not covered; the app is meant for a
trusted network, this guard closes the direct case.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    pass


def _addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    return [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]


def ensure_public_http_url(url: str) -> str:
    """Return `url` unchanged when it is http(s) and does not target a private address, else raise."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("L'URL doit commencer par http:// ou https://.")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL sans nom d'hôte.")
    for address in _addresses(host):
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if not address.is_global:
            raise UnsafeUrlError("L'URL pointe vers une adresse locale ou privée.")
    return url
