"""Word-based, accent-insensitive matching shared by the library/channel search
fields and the library chat tools."""

import unicodedata

from back.models.channel import Channel
from back.models.video import Video


def normalized_search_query(value: str | None) -> str:
    """The query as typed, whitespace collapsed — also what the search field echoes back."""
    return " ".join((value or "").split())


def fold_search_text(value: str) -> str:
    """Case- and accent-insensitive form, so "ecole" finds "École"."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def search_rank(search_query: str, field_groups: list[list[str | None]]) -> int | None:
    """Relevance tier of a record for a query, or None when it does not match.

    Every word of the query must appear somewhere in the record. The tier is the
    index of the first group that, together with the groups before it, holds all
    the words — so groups go from most to least significant field.
    """
    tokens = fold_search_text(search_query).split()
    haystack = ""
    for rank, group in enumerate(field_groups):
        haystack += " " + fold_search_text(" ".join(item for item in group if item))
        if all(token in haystack for token in tokens):
            return rank
    return None


def video_search_rank(video: Video, search_query: str, comment: str | None = None) -> int | None:
    """`comment` is the searching user's own comment on the fiche."""
    channel = video.channel
    return search_rank(
        search_query,
        [
            [video.title],
            [channel.name if channel else None, video.category_labels],
            [
                comment,
                video.url,
                video.yt_video_id,
                channel.url if channel else None,
            ],
        ],
    )


def channel_search_rank(channel: Channel, search_query: str) -> int | None:
    return search_rank(
        search_query,
        [[channel.name], [channel.category_labels], [channel.url, channel.yt_channel_id]],
    )
