import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back.db.base import *  # noqa: F403
from back.db.session import Base
from back.models.channel import Channel
from back.services.channels.subscriptions import (
    SubscriptionsCsvError,
    decode_import_token,
    encode_import_token,
    parse_subscriptions_csv,
)

CSV_SAMPLE = (
    "ID des chaînes,URL des chaînes,Titres des chaînes\n"
    "UC111,http://www.youtube.com/channel/UC111,Chaine Un\n"
    "UC222,http://www.youtube.com/channel/UC222,Chaine Deux\n"
    "UC111,http://www.youtube.com/channel/UC111,Chaine Un Dupliquee\n"
).encode("utf-8-sig")


def make_session():
    # One connection shared across threads: the back serves the front's calls from another one.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture(autouse=True)
def no_profile_backfill(monkeypatch):
    # Adding channels starts the profile backfill, which would reach YouTube.
    monkeypatch.setattr("back.api.channels.run_channel_profile_backfill_job", lambda: None)


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


def test_import_channels_csv_preview_flags_already_imported(front_client):
    db = make_session()
    db.add(
        Channel(
            url="https://www.youtube.com/channel/UC111",
            name="Chaine Un existante",
            yt_channel_id="UC111",
        )
    )
    db.commit()

    response = front_client(db).post(
        "/channels/import-csv", files={"csv_file": ("abonnements.csv", CSV_SAMPLE)}
    )
    rendered = response.text

    assert "Chaine Deux" in rendered
    assert "Déjà importée" in rendered
    assert 'name="import_rows"' in rendered
    assert rendered.count('name="import_rows"') == 1


def test_import_channels_csv_preview_rejects_bad_csv(front_client):
    response = front_client(make_session()).post(
        "/channels/import-csv",
        files={"csv_file": ("abonnements.csv", b"nope")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "level=error" in response.headers["location"]


def test_import_channels_csv_confirm_adds_only_selected_new_channels(front_client):
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

    response = front_client(db).post(
        "/channels/import-csv/confirm",
        data={
            "import_rows": [encode_import_token(new_row), encode_import_token(already_imported_row)]
        },
        follow_redirects=False,
    )

    channels = db.scalars(select(Channel)).all()
    assert len(channels) == 2
    assert {channel.yt_channel_id for channel in channels} == {"UC111", "UC222"}
    assert (
        response.headers["location"] == "/channels?sort=added&message=1+cha%C3%AEne+ajout%C3%A9e."
    )


def test_import_channels_csv_confirm_with_no_rows_reports_error(front_client):
    response = front_client(make_session()).post(
        "/channels/import-csv/confirm", data={}, follow_redirects=False
    )

    assert "level=error" in response.headers["location"]
