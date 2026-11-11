"""Downscaled copies of a channel's avatar and banner.

YouTube's originals are up to 2560 px wide, far more than a card shows. The copies live in a
`thumbs/` subfolder next to the images and go away with the channel's folder.
"""

import logging
import subprocess
from pathlib import Path

from back.services.media.thumbnails import THUMBNAILS_DIRNAME, resize_image

logger = logging.getLogger(__name__)

# 1280 serves the banner of a full-width card on a 3x phone screen.
CHANNEL_IMAGE_WIDTHS = (320, 640, 1280)
# The copy is a JPEG, which has no transparency: a PNG, WebP or GIF would get a black background.
_JPEG_SUFFIXES = {".jpg", ".jpeg"}


def channel_image_variant(image: Path, width: int) -> Path | None:
    """The copy of a channel's avatar or banner at `width`, made on the first request.

    Named after the image and redone when the image is newer. None when there is no copy (image
    that is not a JPEG, no ffmpeg, corrupt image): the caller serves the original.
    """
    if image.suffix.lower() not in _JPEG_SUFFIXES:
        return None
    target = image.parent / THUMBNAILS_DIRNAME / f"{image.stem}-{width}.jpg"
    try:
        if not target.is_file() or target.stat().st_mtime < image.stat().st_mtime:
            resize_image(image, target, width)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("channel image copy failed for %s: %s", image, exc)
        return None
    return target
