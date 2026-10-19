import base64
import csv
import io
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel import Channel

CHANNEL_ID_HEADER = "ID des chaînes"
CHANNEL_URL_HEADER = "URL des chaînes"
CHANNEL_NAME_HEADER = "Titres des chaînes"
REQUIRED_HEADERS = {CHANNEL_ID_HEADER, CHANNEL_URL_HEADER, CHANNEL_NAME_HEADER}


class SubscriptionsCsvError(ValueError):
    pass


def parse_subscriptions_csv(content: bytes) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SubscriptionsCsvError("Fichier CSV illisible (encodage non supporté).") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not REQUIRED_HEADERS.issubset(set(reader.fieldnames or [])):
        raise SubscriptionsCsvError(
            "Format de CSV non reconnu (export des abonnements YouTube attendu)."
        )

    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for raw_row in reader:
        channel_id = (raw_row.get(CHANNEL_ID_HEADER) or "").strip()
        name = (raw_row.get(CHANNEL_NAME_HEADER) or "").strip()
        url = (raw_row.get(CHANNEL_URL_HEADER) or "").strip()
        if not channel_id or not name or channel_id in seen_ids:
            continue
        seen_ids.add(channel_id)
        if not url:
            url = f"https://www.youtube.com/channel/{channel_id}"
        elif url.startswith("http://"):
            url = f"https://{url[len('http://') :]}"
        rows.append({"channel_id": channel_id, "url": url, "name": name})

    if not rows:
        raise SubscriptionsCsvError("Aucun abonnement trouvé dans ce fichier.")
    return rows


def encode_import_token(row: dict[str, str]) -> str:
    payload = json.dumps([row["channel_id"], row["url"], row["name"]], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_import_token(token: str) -> dict[str, str] | None:
    try:
        channel_id, url, name = json.loads(
            base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        )
    except Exception:
        return None
    if not channel_id or not url or not name:
        return None
    return {"channel_id": str(channel_id), "url": str(url), "name": str(name)}


def _known_channels(db: Session) -> tuple[set[str], set[str]]:
    """YouTube ids and URLs of the library's channels: a subscription matching either is known."""
    ids = {
        cid
        for (cid,) in db.execute(
            select(Channel.yt_channel_id).where(Channel.yt_channel_id.is_not(None))
        )
    }
    urls = {url for (url,) in db.execute(select(Channel.url))}
    return ids, urls


def preview_subscriptions(db: Session, rows: list[dict[str, str]]) -> list[dict]:
    """The CSV rows sorted by name, each flagged `already_imported`, with a token for the new ones."""
    ids, urls = _known_channels(db)
    preview_rows = []
    for row in rows:
        already_imported = row["channel_id"] in ids or row["url"] in urls
        preview_rows.append(
            {
                **row,
                "already_imported": already_imported,
                "token": None if already_imported else encode_import_token(row),
            }
        )
    preview_rows.sort(key=lambda row: row["name"].casefold())
    return preview_rows


def add_subscriptions(db: Session, tokens: list[str]) -> int:
    """Add the channels of the confirmed preview rows not yet in the library; returns how many."""
    ids, urls = _known_channels(db)
    added = 0
    for token in tokens:
        row = decode_import_token(token)
        if row is None or row["channel_id"] in ids or row["url"] in urls:
            continue
        ids.add(row["channel_id"])
        db.add(Channel(url=row["url"], name=row["name"], yt_channel_id=row["channel_id"], rating=1))
        added += 1
    db.commit()
    return added
