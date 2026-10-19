import json
import os
import shutil
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import local_media_path
from app.models.channel import Channel
from app.services.files import sanitize_filename
from app.services.job_log import log_job
from app.services.settings import get_media_root
from app.services.youtube import channel_info
from app.services.youtube.url_guard import ensure_public_http_url

CHANNELS_DIRNAME = "_channels"
# Pause between two channels of a backfill, so a long import does not hammer YouTube.
PROFILE_FETCH_DELAY_SECONDS = 2.0
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 20
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def local_media_root(media_root: Path) -> Path:
    """The media root as seen from this machine (MEDIA_ROOT_REMOTE_PREFIX/LOCAL_PREFIX on a dev PC).

    The `media_root` setting holds the server's path, which does not exist on a
    dev PC mirroring the library; every file access goes through this.
    """
    return local_media_path(str(media_root))


def channels_root(media_root: Path) -> Path:
    return media_root / CHANNELS_DIRNAME


def channel_profile_dir(media_root: Path, yt_channel_id: str) -> Path:
    # Keyed by the YouTube id, which never changes, unlike the channel name
    # that names the video folders.
    return channels_root(media_root) / sanitize_filename(yt_channel_id)


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect must not lead from a public address to a private one."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ensure_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_image_bytes(url: str) -> tuple[bytes, str]:
    ensure_public_http_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    opener = urllib.request.build_opener(_PublicRedirectHandler)
    with opener.open(request, timeout=IMAGE_DOWNLOAD_TIMEOUT_SECONDS) as response:
        content = response.read(MAX_IMAGE_BYTES + 1)
        content_type = response.headers.get_content_type()
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Image trop volumineuse")
    return content, content_type


def store_image(url: str, stem: Path) -> Path:
    """Download `url` to `stem` + extension. Atomic, and drops a stale file with another extension."""
    content, content_type = fetch_image_bytes(url)
    extension = IMAGE_EXTENSIONS.get(content_type)
    if extension is None:
        raise ValueError(f"Type d'image non géré : {content_type}")
    stem.parent.mkdir(parents=True, exist_ok=True)
    target = stem.with_suffix(extension)
    # A unique temp name per write: a manual refresh racing a backfill must not share a `.part` file.
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    for other in IMAGE_EXTENSIONS.values():
        if other != extension:
            stem.with_suffix(other).unlink(missing_ok=True)
    return target


def refresh_channel_profile(db: Session, channel: Channel) -> bool:
    """Fetch and store the profile of one channel. False when nothing could be fetched, leaving it pending."""
    if not channel.yt_channel_id:
        return False
    try:
        profile = channel_info.fetch_channel_profile(channel.url)
    except Exception as exc:
        log_job(
            db,
            "failed",
            f"Profil de {channel.name} impossible à récupérer : {exc}",
            channel_id=channel.id,
        )
        return False
    media_root = local_media_root(get_media_root(db))
    folder = channel_profile_dir(media_root, channel.yt_channel_id)
    channel.description = profile["description"]
    channel.keywords = (
        json.dumps(profile["keywords"], ensure_ascii=False) if profile["keywords"] else None
    )
    for kind in ("avatar", "banner"):
        url = profile[f"{kind}_url"]
        if not url:
            continue
        try:
            saved = store_image(url, folder / kind)
        except Exception as exc:
            # An image that fails must not lose the text; the refresh button retries it.
            log_job(
                db,
                "warning",
                f"Image {kind} de {channel.name} non enregistrée : {exc}",
                channel_id=channel.id,
            )
            continue
        setattr(channel, f"{kind}_path", saved.relative_to(media_root).as_posix())
    channel.metadata_fetched_at = datetime.now(UTC)
    db.commit()
    return True


def pending_profile_channel_ids(db: Session) -> list[int]:
    return list(
        db.scalars(
            select(Channel.id)
            .where(Channel.metadata_fetched_at.is_(None), Channel.yt_channel_id.is_not(None))
            .order_by(Channel.id)
        )
    )


def remove_channel_profile_files(media_root: Path, yt_channel_id: str | None) -> None:
    if not yt_channel_id:
        return
    media_root = local_media_root(media_root)
    folder = channel_profile_dir(media_root, yt_channel_id).resolve()
    # The id comes from the DB: never delete anything outside the channels folder.
    if (
        folder.is_relative_to(channels_root(media_root).resolve())
        and folder != channels_root(media_root).resolve()
    ):
        shutil.rmtree(folder, ignore_errors=True)
