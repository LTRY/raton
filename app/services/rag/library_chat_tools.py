"""Tools the library chat model calls to look things up or add a channel, and the references it cites.

Every channel or video a tool returns carries a `[chaine:ID]` / `[video:ID]`
reference. The model writes the ones it keeps in its answer as
`[[kind:ID|name]]`, and `LibraryChatToolbox.extract_sources` keeps only those a
tool returned (or an earlier answer already cited) — so a highlighted link can
only ever point at something the tools found. The interface shows the name
stored in the database, never the model's label, which is only the fallback of
a reference that is not backed.
"""

import re
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.channel import Channel
from app.models.library_chat_message import LibraryChatMessage
from app.models.video import Video
from app.services.channels.lookup import find_channel
from app.services.common.search import channel_search_rank, fold_search_text, video_search_rank
from app.services.rag import retrieval as rag_retrieval
from app.services.videos.playback import (
    dashboard_media_activity_logs,
    local_datetime,
    playback_activity_view,
)
from app.services.youtube import channel_info

# Each tool turn is a full extra API call, so this bounds both the latency and
# the cost of one question.
MAX_TOOL_TURNS = 4
MAX_CHANNEL_RESULTS = 60
MAX_VIDEO_RESULTS = 20
MAX_HISTORY_RESULTS = 30
DEFAULT_HISTORY_DAYS = 30
# Playback rows read before they are folded to one per media; bounds the scan of
# the ever-growing download_jobs table.
HISTORY_SCAN_LIMIT = 500

LIBRARY_CHAT_TOOLS = [
    {
        "name": "chercher_chaines",
        "description": (
            "Cherche des chaînes de la bibliothèque par nom, label (catégorie), URL ou identifiant YouTube. "
            "La recherche est textuelle (insensible à la casse et aux accents), pas sémantique : utilise un ou deux "
            "mots-clés, pas une phrase. Sans requête, liste toutes les chaînes, ce qui permet de choisir toi-même "
            "celles qui correspondent à un thème."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requete": {"type": "string", "description": "Mots-clés ; vide pour tout lister."}
            },
        },
    },
    {
        "name": "chercher_videos",
        "description": (
            "Cherche des vidéos de la bibliothèque par titre, nom de chaîne, label ou commentaire, y compris "
            "celles sans notes structurées. Recherche textuelle par mots-clés, pas sémantique. `chaine_id` restreint "
            "à une chaîne ; avec `chaine_id` seul, renvoie ses vidéos les plus récentes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requete": {"type": "string", "description": "Mots-clés du titre ou du sujet."},
                "chaine_id": {
                    "type": "integer",
                    "description": "ID d'une chaîne renvoyée par chercher_chaines.",
                },
            },
        },
    },
    {
        "name": "chercher_dans_les_notes",
        "description": (
            "Recherche sémantique dans les notes structurées des vidéos (faits, concepts, acteurs...). À utiliser pour "
            "une question sur le contenu des vidéos, ou pour trouver quelles chaînes parlent d'un sujet. Ne couvre que "
            "les vidéos dont les notes ont été générées. Formule la requête comme une question ou une phrase complète."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requete": {
                    "type": "string",
                    "description": "Question ou sujet en langage naturel.",
                }
            },
            "required": ["requete"],
        },
    },
    {
        "name": "consulter_historique",
        "description": (
            "Renvoie l'historique de lecture : les vidéos ou audios que l'utilisateur a regardés ou écoutés, du plus "
            "récent au plus ancien, une ligne par vidéo, avec la date, la progression et le temps regardé. À utiliser "
            "pour « qu'ai-je regardé récemment », « ai-je déjà vu telle vidéo », « qu'est-ce que je n'ai pas fini »."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "jours": {
                    "type": "integer",
                    "description": f"Fenêtre en jours à partir d'aujourd'hui (défaut {DEFAULT_HISTORY_DAYS}).",
                },
                "requete": {
                    "type": "string",
                    "description": "Mots-clés du titre ou de la chaîne pour ne garder qu'une partie de l'historique.",
                },
            },
        },
    },
    {
        "name": "chercher_sur_youtube",
        "description": (
            "Cherche sur YouTube des chaînes par nom, pour trouver une chaîne qui n'est pas encore dans la "
            "bibliothèque. Renvoie les candidates dans l'ordre de pertinence de YouTube, avec leur identifiant "
            "[youtube:ID], leur handle et leur nombre d'abonnés, et signale celles déjà présentes dans la bibliothèque."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requete": {
                    "type": "string",
                    "description": "Nom de la chaîne ou du créateur, ou handle.",
                }
            },
            "required": ["requete"],
        },
    },
    {
        "name": "ajouter_chaine",
        "description": (
            "Ajoute à la bibliothèque une chaîne renvoyée par chercher_sur_youtube pendant cette même question. "
            "À n'appeler que si l'utilisateur demande explicitement d'ajouter une chaîne."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "youtube_id": {
                    "type": "string",
                    "description": "L'ID d'une référence [youtube:ID], sans les crochets.",
                }
            },
            "required": ["youtube_id"],
        },
    },
]

# The model writes `[[video:34|Title]]` around the name it retains, so the
# interface can highlight it in place; the bare `[video:34]` form is what tools
# return and what older prompts asked for. The label runs to the first `]]` not
# followed by another `]`, so a title such as `[FR] Python [2024]` survives.
# app/static/js/app.js (REFERENCE_PATTERN) must match the same syntax.
_REFERENCE_PATTERN = re.compile(
    r"\[\[(chaine|video)\s*:\s*(\d+)\s*(?:\|\s*([^\n]*?)\s*)?\]\](?!\])"
    r"|\s*\[(chaine|video)\s*:\s*(\d+)\]"
)
# YouTube candidates are not library items, so they never become chips: a
# reference the model repeats is only removed from the text.
_YOUTUBE_REFERENCE_PATTERN = re.compile(r"\s*\[youtube\s*:\s*[\w-]+\]")


def _ranked[T](
    items: list[T], rank: Callable[[T, str], int | None], query: str
) -> tuple[list[tuple[int, T]], bool]:
    """Items matching every word of the query, or failing that, any of its words.

    The model tends to send several near-synonyms where the search fields expect
    words that all appear, so an empty strict result falls back to a looser one.
    The flag tells whether that fallback was used.
    """
    strict = [(tier, item) for item in items if (tier := rank(item, query)) is not None]
    if strict:
        return strict, False
    words = fold_search_text(query).split()
    if len(words) < 2:
        return [], False
    loose = []
    for item in items:
        tiers = [tier for word in words if (tier := rank(item, word)) is not None]
        if tiers:
            # More matching words first, then the usual field tier.
            loose.append((min(tiers) - 10 * len(tiers), item))
    return loose, True


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _quoted(query: str) -> str:
    return f"« {query} »"


def parse_source_ids(sources: str | None) -> list[int]:
    """Ids of a `library_chat_messages.sources` / `channel_sources` column."""
    if not sources:
        return []
    return [int(value) for value in sources.split(",") if value.strip().isdigit()]


class LibraryChatToolbox:
    """Runs the tools for one question and remembers what they returned.

    `steps` is the user-facing trace of the calls (a label while the tool runs,
    then a one-line result). `on_progress` is called with it every time it
    changes, so the job runner can store it for the UI to poll.
    """

    def __init__(
        self, db: Session, on_progress: Callable[[list[dict]], None] | None = None
    ) -> None:
        self.db = db
        self.on_progress = on_progress
        self.steps: list[dict] = []
        self._summary: str | None = None
        self.channel_ids: set[int] = set()
        self.video_ids: set[int] = set()
        self.youtube_candidates: dict[str, dict] = {}
        self.added_channel_ids: list[int] = []

    def run(self, name: str, arguments: dict) -> str:
        handlers = {
            "chercher_chaines": self._search_channels,
            "chercher_videos": self._search_videos,
            "chercher_dans_les_notes": self._search_notes,
            "consulter_historique": self._playback_history,
            "chercher_sur_youtube": self._search_youtube,
            "ajouter_chaine": self._add_channel,
        }
        handler = handlers.get(name)
        if handler is None:
            return f"Outil inconnu : {name}"
        arguments = arguments or {}
        step = {"label": self._step_label(name, arguments), "result": None}
        self.steps.append(step)
        self._notify_progress()
        self._summary = None
        try:
            output = handler(arguments)
            step["result"] = self._summary or "Terminé."
        except Exception as exc:
            # A failed query leaves the session unusable until rolled back, and
            # the job runner still has to commit the answer on this session.
            self.db.rollback()
            output = f"Erreur de l'outil {name} : {exc}"
            step["result"] = "La recherche a échoué."
        self._notify_progress()
        return output

    def _notify_progress(self) -> None:
        if self.on_progress is not None:
            self.on_progress(self.steps)

    @staticmethod
    def _step_label(name: str, arguments: dict) -> str:
        query = str(arguments.get("requete") or "").strip()
        if name == "chercher_chaines":
            return (
                f"Recherche de la chaîne {_quoted(query)}…"
                if query
                else "Parcours des chaînes de la bibliothèque…"
            )
        if name == "chercher_videos":
            if query:
                return f"Recherche de vidéos {_quoted(query)}…"
            return "Recherche des vidéos de la chaîne…"
        if name == "chercher_dans_les_notes":
            return "Recherche dans les notes générées…"
        if name == "consulter_historique":
            return "Consultation de l'historique de lecture…"
        if name == "chercher_sur_youtube":
            return f"Recherche de la chaîne {_quoted(query)} sur YouTube…"
        return "Ajout de la chaîne à la bibliothèque…"

    def _channel_reference(self, channel_id: int) -> str:
        self.channel_ids.add(channel_id)
        return f"[chaine:{channel_id}]"

    def _video_reference(self, video_id: int) -> str:
        self.video_ids.add(video_id)
        return f"[video:{video_id}]"

    def _search_channels(self, arguments: dict) -> str:
        query = str(arguments.get("requete") or "").strip()
        matches, loose = _ranked(self.db.query(Channel).all(), channel_search_rank, query)
        if not matches:
            self._summary = "Aucune chaîne trouvée."
            return f"Aucune chaîne ne correspond à « {query} »."
        matches.sort(key=lambda match: (match[0], -match[1].rating, match[1].name.casefold()))
        best = matches[0][1].name
        if loose:
            self._summary = f"Chaîne la plus proche : {best}."
        elif len(matches) == 1:
            self._summary = f"Chaîne {best} trouvée."
        else:
            self._summary = f"{len(matches)} chaînes trouvées, dont {best}."
        video_counts = dict(
            self.db.query(Video.channel_id, func.count(Video.id)).group_by(Video.channel_id).all()
        )
        lines = []
        for _, channel in matches[:MAX_CHANNEL_RESULTS]:
            parts = [f"{self._channel_reference(channel.id)} {channel.name}"]
            if channel.category_labels:
                parts.append(f"labels : {channel.category_labels}")
            parts.append(f"note {channel.rating}/5")
            parts.append(f"{video_counts.get(channel.id, 0)} vidéo(s)")
            followed = [
                label
                for label, enabled in (
                    ("vidéos", channel.auto_metadata_enabled),
                    ("shorts", channel.auto_shorts_enabled),
                )
                if enabled
            ]
            if followed:
                parts.append(f"suivie (cloche {' et '.join(followed)} activée)")
            lines.append(" — ".join(parts))
        header = f"{len(matches)} chaîne(s)"
        if loose:
            header += " (aucune ne contient tous les mots ; correspondances partielles)"
        if len(matches) > MAX_CHANNEL_RESULTS:
            header += f", {MAX_CHANNEL_RESULTS} affichées"
        return header + " :\n" + "\n".join(lines)

    def _search_videos(self, arguments: dict) -> str:
        query = str(arguments.get("requete") or "").strip()
        channel_id = arguments.get("chaine_id")
        if not query and channel_id is None:
            return "Précise une requête ou un chaine_id."
        videos_query = self.db.query(Video).options(joinedload(Video.channel))
        if channel_id is not None:
            videos_query = videos_query.filter(Video.channel_id == int(channel_id))
        matches, loose = _ranked(videos_query.all(), video_search_rank, query)
        if not matches:
            self._summary = "Aucune vidéo trouvée."
            return "Aucune vidéo ne correspond."
        self._summary = _plural(len(matches), "vidéo trouvée.", "vidéos trouvées.")
        matches.sort(
            key=lambda match: (
                match[0],
                -(match[1].published_at.timestamp() if match[1].published_at else 0),
            )
        )
        lines = []
        for _, video in matches[:MAX_VIDEO_RESULTS]:
            parts = [f"{self._video_reference(video.id)} {video.title}"]
            if video.channel is not None:
                parts.append(
                    f"chaîne : {video.channel.name} {self._channel_reference(video.channel.id)}"
                )
            if video.published_at:
                parts.append(video.published_at.date().isoformat())
            if video.category_labels:
                parts.append(f"labels : {video.category_labels}")
            lines.append(" — ".join(parts))
        header = f"{len(matches)} vidéo(s)"
        if loose:
            header += " (aucune ne contient tous les mots ; correspondances partielles)"
        if len(matches) > MAX_VIDEO_RESULTS:
            header += f", {MAX_VIDEO_RESULTS} affichées"
        return header + " :\n" + "\n".join(lines)

    def _search_notes(self, arguments: dict) -> str:
        query = str(arguments.get("requete") or "").strip()
        if not query:
            return "Précise une requête."
        chunks = rag_retrieval.retrieve_relevant_chunks(self.db, query)
        if not chunks:
            self._summary = "Aucun extrait pertinent."
            return "Aucun extrait pertinent trouvé dans les notes indexées de la bibliothèque."
        self._summary = _plural(
            len(chunks), "extrait pertinent trouvé.", "extraits pertinents trouvés."
        )
        blocks = []
        for chunk in chunks:
            heading = f"{self._video_reference(chunk.video_id)} {chunk.video_title}"
            if chunk.channel_id is not None:
                heading += (
                    f" — chaîne : {chunk.channel_name} {self._channel_reference(chunk.channel_id)}"
                )
            blocks.append(f"{heading} ({chunk.section})\n{chunk.content}")
        return "\n\n".join(blocks)

    def _playback_history(self, arguments: dict) -> str:
        query = str(arguments.get("requete") or "").strip()
        try:
            days = max(int(arguments.get("jours") or DEFAULT_HISTORY_DAYS), 1)
        except TypeError, ValueError:
            days = DEFAULT_HISTORY_DAYS
        now = datetime.now().astimezone()
        since = now - timedelta(days=days)
        jobs = [
            job
            for job in dashboard_media_activity_logs(self.db, limit=HISTORY_SCAN_LIMIT)
            if local_datetime(job.created_at, now.tzinfo) >= since
        ]
        video_ids = {job.video_id for job in jobs if job.video_id}
        videos = {}
        if video_ids:
            videos = {
                video.id: video
                for video in self.db.query(Video)
                .options(joinedload(Video.channel))
                .filter(Video.id.in_(video_ids))
            }
        entries = []
        for job in jobs:
            playback = playback_activity_view(job)
            video = videos.get(job.video_id)
            title = video.title if video else str(playback["title"] or "")
            channel = video.channel if video else None
            if query and not (
                fold_search_text(query)
                in fold_search_text(f"{title} {channel.name if channel else ''}")
                or (video and video_search_rank(video, query) is not None)
            ):
                continue
            entries.append((job, playback, video, title, channel))
        if not entries:
            self._summary = "Aucune lecture trouvée."
            return f"Aucune lecture dans l'historique sur les {days} derniers jours."
        self._summary = _plural(len(entries), "lecture trouvée.", "lectures trouvées.")
        lines = []
        for job, playback, video, title, channel in entries[:MAX_HISTORY_RESULTS]:
            when = local_datetime(job.created_at, now.tzinfo).strftime("%Y-%m-%d %H:%M")
            if video is not None:
                parts = [f"{self._video_reference(video.id)} {title}"]
            else:
                parts = [f"{title or 'Vidéo supprimée de la bibliothèque'} (supprimée)"]
            if channel is not None:
                parts.append(f"chaîne : {channel.name} {self._channel_reference(channel.id)}")
            parts.append(f"lecture le {when}")
            status = (
                "terminée"
                if playback["is_completed"]
                else f"arrêtée à {playback['position_label']}"
            )
            parts.append(f"{playback['media_label']} {status} sur {playback['duration_label']}")
            parts.append(f"{playback['watched_label']} regardées")
            lines.append(" — ".join(parts))
        header = f"{len(entries)} lecture(s) sur les {days} derniers jours"
        if len(entries) > MAX_HISTORY_RESULTS:
            header += f", {MAX_HISTORY_RESULTS} affichées"
        return header + " :\n" + "\n".join(lines)

    def _search_youtube(self, arguments: dict) -> str:
        query = str(arguments.get("requete") or "").strip()
        if not query:
            return "Précise une requête."
        results = channel_info.search_channels(query)
        if not results:
            self._summary = "Aucune chaîne trouvée sur YouTube."
            return f"Aucune chaîne YouTube ne correspond à « {query} »."
        self._summary = _plural(
            len(results), "chaîne trouvée sur YouTube.", "chaînes trouvées sur YouTube."
        )
        lines = []
        for result in results:
            self.youtube_candidates[result["yt_channel_id"]] = result
            parts = [f"[youtube:{result['yt_channel_id']}] {self._youtube_identity(result)}"]
            if result["description"]:
                parts.append(result["description"].replace("\n", " ")[:160])
            existing = find_channel(self.db, result["url"], result["yt_channel_id"])
            if existing is not None:
                parts.append(f"déjà dans la bibliothèque {self._channel_reference(existing.id)}")
            lines.append(" — ".join(parts))
        return f"{len(results)} chaîne(s) YouTube :\n" + "\n".join(lines)

    def _add_channel(self, arguments: dict) -> str:
        youtube_id = (
            str(arguments.get("youtube_id") or "")
            .strip()
            .removeprefix("[youtube:")
            .removesuffix("]")
        )
        # Only a candidate YouTube itself returned for this question can be
        # added: the model cannot create a channel from an id it made up.
        candidate = self.youtube_candidates.get(youtube_id)
        if candidate is None:
            self._summary = "Ajout impossible : chaîne inconnue."
            return "Identifiant inconnu : appelle d'abord chercher_sur_youtube et reprends un de ses identifiants."
        existing = find_channel(self.db, candidate["url"], youtube_id)
        if existing is not None:
            self._summary = f"{existing.name} est déjà dans la bibliothèque."
            return f"Déjà dans la bibliothèque : {self._channel_reference(existing.id)} {existing.name}"
        channel = Channel(
            url=candidate["url"], name=candidate["name"], yt_channel_id=youtube_id, rating=1
        )
        self.db.add(channel)
        self.db.commit()
        self.added_channel_ids.append(channel.id)
        self._summary = f"Chaîne {candidate['name']} ajoutée."
        # The identity is repeated here so the confirmation can name exactly
        # which of several namesakes was added.
        return f"Chaîne ajoutée : {self._channel_reference(channel.id)} {self._youtube_identity(candidate)}"

    @staticmethod
    def _youtube_identity(candidate: dict) -> str:
        parts = [candidate["name"]]
        if candidate["handle"]:
            parts.append(candidate["handle"])
        if candidate["subscriber_count"] is not None:
            parts.append(f"{candidate['subscriber_count']} abonné(s)")
        return " — ".join(parts)

    def _cited_in_history(self) -> dict[str, set[int]]:
        """Ids earlier answers already cited: they were validated back then, and
        the model sees their `[[...]]` in the history it is given."""
        rows = self.db.query(LibraryChatMessage.sources, LibraryChatMessage.channel_sources).all()
        return {
            "chaine": {item for _, channels in rows for item in parse_source_ids(channels)},
            "video": {item for videos, _ in rows for item in parse_source_ids(videos)},
        }

    def extract_sources(self, text: str) -> tuple[str, dict[str, list[int]]]:
        """Validate the references of an answer and return the ones that are backed.

        An id is backed when a tool returned it during this job or an earlier
        answer already cited it. `[[kind:id|name]]` stays in the text when
        backed (the interface turns it into a link) and falls back to its
        plain name otherwise; a bare `[kind:id]` is removed. Ids are listed in
        order of first mention. A reference to anything else can only be a
        hallucination: it never survives.
        """
        history = self._cited_in_history()
        backed_ids = {
            "chaine": self.channel_ids | history["chaine"],
            "video": self.video_ids | history["video"],
        }
        cited: dict[str, list[int]] = {"chaine": [], "video": []}

        def resolve(match: re.Match[str]) -> str:
            inline = match.group(1) is not None
            kind = match.group(1) or match.group(4)
            item_id = int(match.group(2) or match.group(5))
            backed = item_id in backed_ids[kind]
            if backed and item_id not in cited[kind]:
                cited[kind].append(item_id)
            if not inline:
                return ""
            name = match.group(3) or ""
            if not backed:
                return name
            return f"[[{kind}:{item_id}|{name}]]" if name else f"[[{kind}:{item_id}]]"

        cleaned = _YOUTUBE_REFERENCE_PATTERN.sub("", _REFERENCE_PATTERN.sub(resolve, text)).strip()
        return cleaned, {"channel_ids": cited["chaine"], "video_ids": cited["video"]}
