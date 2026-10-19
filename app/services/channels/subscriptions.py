import base64
import csv
import io
import json

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
