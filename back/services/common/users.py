"""The users of Raton: list, add, rename, delete, and which one a request acts for.

There is no password: Raton runs on a trusted LAN (docs/spec/15-securite.md), so choosing a user
only says whose Vu, stars, playlists and discussions a page shows.
"""

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from back.models.job import DownloadJob
from back.models.library_chat_conversation import LibraryChatConversation
from back.models.library_chat_message import LibraryChatMessage
from back.models.llm_job import LlmJob
from back.models.playlist import Playlist, PlaylistItem
from back.models.user import USER_NAME_LENGTH, User, UserChannel, UserSetting, UserVideo

# The user the first migration hands the existing data to; also created on an empty DB.
FIRST_USER_NAME = "Moi"


class UserNameError(ValueError):
    pass


class UserNotFoundError(ValueError):
    pass


class LastUserError(ValueError):
    pass


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))


def default_user(db: Session) -> User:
    """The oldest user, created when the DB has none (demo, tests, a fresh install)."""
    # No autoflush: the caller may be halfway through building rows of its own.
    with db.no_autoflush:
        user = db.scalars(select(User).order_by(User.id).limit(1)).first()
    if user is None:
        user = User(name=FIRST_USER_NAME)
        db.add(user)
        db.commit()
    return user


def current_user(db: Session, requested: str | int | None) -> User:
    """The user a request names (its id), or the default one when it names none or a deleted one."""
    try:
        user_id = int(requested) if requested is not None else None
    except ValueError:
        user_id = None
    user = db.get(User, user_id) if user_id is not None else None
    return user or default_user(db)


def _user_name(db: Session, name: str, except_id: int | None = None) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise UserNameError("Le nom de l'utilisateur est obligatoire.")
    if len(cleaned) > USER_NAME_LENGTH:
        raise UserNameError(f"Le nom ne doit pas dépasser {USER_NAME_LENGTH} caractères.")
    taken = db.scalar(
        select(User.id).where(func.lower(User.name) == cleaned.lower(), User.id != except_id)
        if except_id is not None
        else select(User.id).where(func.lower(User.name) == cleaned.lower())
    )
    if taken is not None:
        raise UserNameError("Un utilisateur porte déjà ce nom.")
    return cleaned


def find_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError("Utilisateur introuvable.")
    return user


def create_user(db: Session, name: str) -> User:
    """A new user starts with nothing of their own: no Vu, no stars, no cloche, no playlist."""
    user = User(name=_user_name(db, name))
    db.add(user)
    db.commit()
    return user


def rename_user(db: Session, user: User, name: str) -> User:
    user.name = _user_name(db, name, except_id=user.id)
    db.commit()
    return user


def delete_user(db: Session, user: User) -> None:
    """Delete a user and everything that was theirs (cascade); the shared fiches stay."""
    if db.scalar(select(func.count(User.id))) <= 1:
        raise LastUserError("Impossible de supprimer le dernier utilisateur.")
    # The foreign keys cascade on Postgres; spelled out so sqlite (demo, tests) ends the same.
    playlists = select(Playlist.id).where(Playlist.user_id == user.id)
    conversations = select(LibraryChatConversation.id).where(
        LibraryChatConversation.user_id == user.id
    )
    db.execute(delete(PlaylistItem).where(PlaylistItem.playlist_id.in_(playlists)))
    db.execute(delete(Playlist).where(Playlist.user_id == user.id))
    db.execute(
        update(LlmJob).where(LlmJob.conversation_id.in_(conversations)).values(conversation_id=None)
    )
    db.execute(
        delete(LibraryChatMessage).where(LibraryChatMessage.conversation_id.in_(conversations))
    )
    db.execute(delete(LibraryChatConversation).where(LibraryChatConversation.user_id == user.id))
    db.execute(update(LlmJob).where(LlmJob.user_id == user.id).values(user_id=None))
    db.execute(update(DownloadJob).where(DownloadJob.user_id == user.id).values(user_id=None))
    for model in (UserVideo, UserChannel, UserSetting):
        db.execute(delete(model).where(model.user_id == user.id))
    db.delete(user)
    db.commit()
