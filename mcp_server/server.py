"""The tools: read-only, one `/api` call each (`docs/spec/21-serveur-mcp.md`)."""

from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_server import api

mcp = MCPServer(
    "raton",
    instructions=(
        "Raton est une bibliothèque locale de vidéos YouTube. Les outils lisent la bibliothèque "
        "(fiches, chaînes, playlists, Nouveautés, statistiques) sans jamais la modifier."
    ),
)


@mcp.tool()
def search_library(
    q: str | None = None,
    channel_id: int | None = None,
    section: str | None = None,
    sort: str | None = None,
    page: int = 1,
) -> Any:
    """Search the library's fiches (title, notes) and list a page of them."""
    return api.get("/library", q=q, channel_id=channel_id, section=section, sort=sort, page=page)


@mcp.tool()
def get_video(video_id: int) -> Any:
    """One fiche: metadata, notes, transcript state, playlists. Read only: does not mark it Vu."""
    detail = api.get(f"/videos/{video_id}")
    # The raw WebVTT of the subtitles only bloats the answer.
    detail.pop("subtitles_vtt", None)
    return detail


@mcp.tool()
def list_channels(q: str | None = None, sort: str | None = None, page: int = 1) -> Any:
    """A page of the library's channels, optionally filtered by name."""
    return api.get("/channels", q=q, sort=sort, page=page)


@mcp.tool()
def get_channel(channel_id: int) -> Any:
    """One channel's page: description, profile, counts."""
    return api.get(f"/channels/{channel_id}")


@mcp.tool()
def list_playlists() -> Any:
    """Every playlist of the library."""
    return api.get("/playlists")


@mcp.tool()
def get_playlist(playlist_id: int) -> Any:
    """One playlist with its items."""
    return api.get(f"/playlists/{playlist_id}")


@mcp.tool()
def get_nouveautes(page: int = 1) -> Any:
    """The Nouveautés: unseen fiches, stacked by channel."""
    return api.get("/nouveautes", page=page)


@mcp.tool()
def get_library_stats() -> Any:
    """Counts (channels, fiches, Shorts, transcripts) and disk usage of the library."""
    return api.get("/stats")
