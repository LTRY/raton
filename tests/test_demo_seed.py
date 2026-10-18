from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.base import *  # noqa: F403
from app.db.session import Base
from app.models.channel import Channel
from app.models.video import Video
from app.services.demo_seed import seed_demo


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_seed_demo_fills_an_empty_database():
    db = make_session()

    assert seed_demo(db) is True

    assert db.scalar(select(func.count(Channel.id))) == 3
    assert db.scalar(select(func.count(Video.id))) == 9


def test_seed_demo_is_idempotent():
    db = make_session()
    seed_demo(db)

    assert seed_demo(db) is False

    assert db.scalar(select(func.count(Video.id))) == 9
