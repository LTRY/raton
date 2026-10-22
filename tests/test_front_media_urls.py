"""Media files (video, audio, thumbnail, subtitles) are served by the back under
`/api/videos/{id}/...`; the front has no such route since the back/front split.
A `/videos/{id}/audio` left in a script or template loads a 404 page into the
player ("Lecture impossible pour ce fichier." in the playlist player)."""

import re
from pathlib import Path

FRONT = Path(__file__).resolve().parent.parent / "front"

# `/videos/<id>/<file>` not preceded by `/api`, where <id> is a JS `${...}` or a
# Jinja `{{ ... }}` and <file> a media kind or a JS placeholder for one.
FRONT_MEDIA_URL = re.compile(
    r"(?<!/api)/videos/(?:\$\{[^}]+\}|\{\{[^}]+\}\})/(?:video|audio|thumbnail|subtitles|\$\{)"
)


def test_media_urls_go_through_the_api():
    files = [*FRONT.glob("static/js/*.js"), *FRONT.glob("templates/**/*.html")]
    assert files
    offenders = [
        f"{path.relative_to(FRONT)}:{number}: {line.strip()}"
        for path in files
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if FRONT_MEDIA_URL.search(line)
    ]
    assert offenders == []
