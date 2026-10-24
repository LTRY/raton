"""How Raton speaks to a user in the chat: tutoiement or vouvoiement, and the name it calls them
by. Stored per user (`user_settings`); the chat prompts read it (back/services/llm/prompts.py)."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.models.user import UserSetting

RATON_ADDRESS_KEY = "raton_address"
RATON_NICKNAME_KEY = "raton_nickname"
RATON_ADDRESSES = ("vous", "tu")
DEFAULT_RATON_ADDRESS = "vous"
RATON_NICKNAME_LENGTH = 40


class RatonLanguageError(ValueError):
    """A refused preference; the message is shown to the person."""


@dataclass(frozen=True)
class RatonLanguage:
    # "vous" or "tu".
    address: str
    # Empty: Raton calls the user nothing in particular.
    nickname: str


def normalize_raton_nickname(value: str) -> str:
    nickname = " ".join(value.split())
    if len(nickname) > RATON_NICKNAME_LENGTH:
        raise RatonLanguageError(
            f"Le surnom ne doit pas dépasser {RATON_NICKNAME_LENGTH} caractères."
        )
    return nickname


def read_raton_language(db: Session, user_id: int) -> RatonLanguage:
    stored = dict(
        db.execute(
            select(UserSetting.key, UserSetting.value).where(
                UserSetting.user_id == user_id,
                UserSetting.key.in_((RATON_ADDRESS_KEY, RATON_NICKNAME_KEY)),
            )
        ).all()
    )
    address = stored.get(RATON_ADDRESS_KEY, DEFAULT_RATON_ADDRESS)
    return RatonLanguage(
        address=address if address in RATON_ADDRESSES else DEFAULT_RATON_ADDRESS,
        nickname=stored.get(RATON_NICKNAME_KEY, ""),
    )
