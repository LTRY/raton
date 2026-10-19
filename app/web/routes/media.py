import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import local_media_path
from app.db.session import get_db
from app.models.channel import Channel
from app.models.video import Video
from app.services.channels.profile import channels_root
from app.services.channels.scanner import ensure_video_channel
from app.services.media.media_storage import delete_video_media_asset
from app.services.media.thumbnails import THUMBNAIL_WIDTHS, thumbnail_variant_path
from app.services.settings import get_media_root
from app.web.shared import append_query, internal_return_path, redirect

router = APIRouter()


@router.get("/videos/{video_id}/thumbnail", response_class=FileResponse)
def video_thumbnail(video_id: int, db: Session = Depends(get_db), w: int | None = None):
    video = db.get(Video, video_id)
    if video is None or not video.thumbnail_path:
        raise HTTPException(status_code=404, detail="Vignette introuvable")

    folder = local_media_path(video.folder_path).resolve()
    thumbnail = local_media_path(video.thumbnail_path).resolve()
    if not thumbnail.is_file() or not thumbnail.is_relative_to(folder):
        raise HTTPException(status_code=404, detail="Vignette introuvable")

    if w in THUMBNAIL_WIDTHS:
        # A stored copy when it exists; the original otherwise (copies are made after the import).
        variant = thumbnail_variant_path(folder, w).resolve()
        if variant.is_file() and variant.is_relative_to(folder):
            return FileResponse(variant, headers={"Cache-Control": "public, max-age=86400"})

    return FileResponse(thumbnail, headers={"Cache-Control": "public, max-age=86400"})


def channel_image_response(db: Session, channel_id: int, kind: str) -> FileResponse:
    channel = db.get(Channel, channel_id)
    stored = getattr(channel, f"{kind}_path", None) if channel else None
    if not stored:
        raise HTTPException(status_code=404, detail="Image introuvable")
    media_root = get_media_root(db)
    image = local_media_path(str(media_root / stored)).resolve()
    # Same guard as the video routes: a tampered DB path must not reach other files.
    if not image.is_file() or not image.is_relative_to(
        local_media_path(str(channels_root(media_root))).resolve()
    ):
        raise HTTPException(status_code=404, detail="Image introuvable")
    return FileResponse(image, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/channels/{channel_id}/avatar", response_class=FileResponse)
def channel_avatar(channel_id: int, db: Session = Depends(get_db)):
    return channel_image_response(db, channel_id, "avatar")


@router.get("/channels/{channel_id}/banner", response_class=FileResponse)
def channel_banner(channel_id: int, db: Session = Depends(get_db)):
    return channel_image_response(db, channel_id, "banner")


@router.get("/videos/{video_id}/subtitles", response_class=FileResponse)
def video_subtitles(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None or not video.subtitle_path:
        raise HTTPException(status_code=404, detail="Sous-titres introuvables")

    folder = local_media_path(video.folder_path).resolve()
    subtitles = local_media_path(video.subtitle_path).resolve()
    if (
        subtitles.suffix.lower() != ".vtt"
        or not subtitles.is_file()
        or not subtitles.is_relative_to(folder)
    ):
        raise HTTPException(status_code=404, detail="Sous-titres introuvables")

    return FileResponse(subtitles, media_type="text/vtt; charset=utf-8")


def file_byte_ranges(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def parse_range_header(
    range_header: str | None, file_size: int, detail: str = "Plage média invalide"
) -> tuple[int, int, int]:
    if not range_header:
        return 0, file_size - 1, 200
    if not range_header.startswith("bytes=") or "," in range_header:
        raise HTTPException(
            status_code=416,
            detail=detail,
            headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
        )

    start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
    except ValueError as exc:
        raise HTTPException(
            status_code=416,
            detail=detail,
            headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
        ) from exc

    if start < 0 or start >= file_size or end < start:
        raise HTTPException(
            status_code=416,
            detail=detail,
            headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
        )
    return start, min(end, file_size - 1), 206


def media_response_context(
    video: Video,
    media_path: str | None,
    request: Request,
    missing_detail: str,
) -> tuple[Path, int, int, int, str, dict[str, str]]:
    if not media_path:
        raise HTTPException(status_code=404, detail=missing_detail)
    folder = local_media_path(video.folder_path).resolve()
    media = local_media_path(media_path).resolve()
    if not media.is_file() or not media.is_relative_to(folder):
        raise HTTPException(status_code=404, detail=missing_detail)

    file_size = media.stat().st_size
    if file_size <= 0:
        raise HTTPException(status_code=404, detail=missing_detail)

    start, end, status_code = parse_range_header(request.headers.get("range"), file_size)
    media_type = mimetypes.guess_type(media.name)[0] or "application/octet-stream"
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
        "Content-Length": str(end - start + 1),
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    return media, start, end, status_code, media_type, headers


def media_stream_response(
    video: Video, media_path: str | None, request: Request, missing_detail: str
) -> StreamingResponse:
    media, start, end, status_code, media_type, headers = media_response_context(
        video, media_path, request, missing_detail
    )

    return StreamingResponse(
        file_byte_ranges(media, start, end),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )


def media_head_response(
    video: Video, media_path: str | None, request: Request, missing_detail: str
) -> Response:
    _, _, _, status_code, media_type, headers = media_response_context(
        video, media_path, request, missing_detail
    )
    return Response(status_code=status_code, media_type=media_type, headers=headers)


@router.get("/videos/{video_id}/audio")
def video_audio(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Audio introuvable")
    return media_stream_response(video, video.audio_path, request, "Audio introuvable")


@router.head("/videos/{video_id}/audio")
def video_audio_head(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Audio introuvable")
    return media_head_response(video, video.audio_path, request, "Audio introuvable")


@router.get("/videos/{video_id}/video")
def video_file(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    ensure_video_channel(db, video)
    return media_stream_response(video, video.video_path, request, "Vidéo introuvable")


@router.head("/videos/{video_id}/video")
def video_file_head(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    return media_head_response(video, video.video_path, request, "Vidéo introuvable")


@router.post("/videos/{video_id}/media/{media_type}/delete")
def delete_video_media_form(
    request: Request,
    video_id: int,
    media_type: str,
    return_to: str = Form("/videos", alias="next"),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")

    is_fetch = request.headers.get("x-requested-with") == "fetch"
    target = internal_return_path(return_to, f"/videos/{video_id}")
    try:
        delete_video_media_asset(video, media_type)
        db.commit()
    except ValueError as exc:
        db.rollback()
        if is_fetch:
            return JSONResponse({"status": "failed", "message": str(exc)}, status_code=400)
        return redirect(append_query(target, {"level": "error", "message": str(exc)}))

    label = "vidéo" if media_type == "video" else "audio"
    if is_fetch:
        return JSONResponse({"status": "deleted", "message": f"Fichier {label} supprimé."})
    return redirect(append_query(target, {"message": f"Fichier {label} supprimé."}))
