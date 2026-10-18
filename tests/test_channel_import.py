import io

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.channel import Channel
from app.services.subscriptions import (
    SubscriptionsCsvError,
    decode_import_token,
    encode_import_token,
    parse_subscriptions_csv,
)
from app.web.routes import channels as channels_routes

CSV_SAMPLE = (
    "ID des chaînes,URL des chaînes,Titres des chaînes\n"
    "UC111,http://www.youtube.com/channel/UC111,Chaine Un\n"
    "UC222,http://www.youtube.com/channel/UC222,Chaine Deux\n"
    "UC111,http://www.youtube.com/channel/UC111,Chaine Un Dupliquee\n"
).encode("utf-8-sig")


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def make_request(method="POST", path="/channels/import-csv", query_string=b""):
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query_string,
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


def test_parse_subscriptions_csv_normalizes_url_and_dedupes():
    rows = parse_subscriptions_csv(CSV_SAMPLE)

    assert rows == [
        {
            "channel_id": "UC111",
            "url": "https://www.youtube.com/channel/UC111",
            "name": "Chaine Un",
        },
        {
            "channel_id": "UC222",
            "url": "https://www.youtube.com/channel/UC222",
            "name": "Chaine Deux",
        },
    ]


def test_parse_subscriptions_csv_rejects_wrong_headers():
    with pytest.raises(SubscriptionsCsvError):
        parse_subscriptions_csv(b"a,b,c\n1,2,3\n")


def test_parse_subscriptions_csv_rejects_empty_result():
    with pytest.raises(SubscriptionsCsvError):
        parse_subscriptions_csv(
            "ID des chaînes,URL des chaînes,Titres des chaînes\n,,\n".encode("utf-8-sig")
        )


def test_import_token_round_trip():
    row = {
        "channel_id": "UC111",
        "url": "https://www.youtube.com/channel/UC111",
        "name": "Chaine Un",
    }

    assert decode_import_token(encode_import_token(row)) == row


def test_decode_import_token_rejects_garbage():
    assert decode_import_token("not-a-valid-token") is None


def test_import_channels_csv_preview_flags_already_imported():
    db = make_session()
    db.add(
        Channel(
            url="https://www.youtube.com/channel/UC111",
            name="Chaine Un existante",
            yt_channel_id="UC111",
        )
    )
    db.commit()

    upload = UploadFile(file=io.BytesIO(CSV_SAMPLE), filename="abonnements.csv")
    response = channels_routes.import_channels_csv_preview(make_request(), csv_file=upload, db=db)
    rendered = response.body.decode()

    assert "Chaine Deux" in rendered
    assert "Déjà importée" in rendered
    assert 'name="import_rows"' in rendered
    assert rendered.count('name="import_rows"') == 1


def test_import_channels_csv_preview_rejects_bad_csv():
    db = make_session()
    upload = UploadFile(file=io.BytesIO(b"nope"), filename="abonnements.csv")

    response = channels_routes.import_channels_csv_preview(make_request(), csv_file=upload, db=db)

    assert response.status_code == 303
    assert "level=error" in response.headers["location"]


def test_import_channels_csv_confirm_adds_only_selected_new_channels():
    db = make_session()
    db.add(
        Channel(
            url="https://www.youtube.com/channel/UC111",
            name="Chaine Un existante",
            yt_channel_id="UC111",
        )
    )
    db.commit()

    new_row = {
        "channel_id": "UC222",
        "url": "https://www.youtube.com/channel/UC222",
        "name": "Chaine Deux",
    }
    already_imported_row = {
        "channel_id": "UC111",
        "url": "https://www.youtube.com/channel/UC111",
        "name": "Chaine Un",
    }

    response = channels_routes.import_channels_csv_confirm(
        import_rows=[encode_import_token(new_row), encode_import_token(already_imported_row)],
        db=db,
    )

    channels = db.scalars(select(Channel)).all()
    assert len(channels) == 2
    assert {channel.yt_channel_id for channel in channels} == {"UC111", "UC222"}
    assert (
        response.headers["location"] == "/channels?sort=added&message=1+cha%C3%AEne+ajout%C3%A9e."
    )


def test_import_channels_csv_confirm_with_no_rows_reports_error():
    db = make_session()

    response = channels_routes.import_channels_csv_confirm(import_rows=[], db=db)

    assert "level=error" in response.headers["location"]
