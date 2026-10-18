from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Raton"
    database_url: str = Field(
        default="postgresql+psycopg://raton:raton@localhost:5432/raton",
        alias="DATABASE_URL",
    )
    media_root: Path = Field(
        default_factory=lambda: Path.home() / "Documents" / "media" / "YouTube",
        alias="MEDIA_ROOT",
    )
    media_root_remote_prefix: Path | None = Field(default=None, alias="MEDIA_ROOT_REMOTE_PREFIX")
    media_root_local_prefix: Path | None = Field(default=None, alias="MEDIA_ROOT_LOCAL_PREFIX")
    global_quota_bytes: int = Field(default=100 * 1024 * 1024 * 1024, alias="GLOBAL_QUOTA_BYTES")
    auto_create_tables: bool = Field(default=False, alias="APP_AUTO_CREATE_TABLES")
    scheduler_enabled: bool = Field(default=True, alias="APP_SCHEDULER_ENABLED")
    trusted_origins: str = Field(default="", alias="APP_TRUSTED_ORIGINS")
    log_dir: Path | None = Field(default=None, alias="LOG_DIR")
    llm_provider: str = Field(default="anthropic", alias="LLM_PROVIDER")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-5", alias="ANTHROPIC_MODEL")
    voyage_api_key: str = Field(default="", alias="VOYAGE_API_KEY")
    embedding_model: str = Field(default="voyage-3.5", alias="EMBEDDING_MODEL")
    rerank_model: str = Field(default="rerank-2.5", alias="RERANK_MODEL")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def local_media_path(stored_path: str) -> Path:
    """Map a DB-stored absolute media path to where it actually lives on this machine.

    On a dev machine mirroring the media library over the network (NFS/SMB), the
    library's folder_path/thumbnail_path/etc. are baked in at download time using
    whatever media_root the machine that downloaded them used (e.g. /media/youtube
    inside the production Docker container). MEDIA_ROOT_REMOTE_PREFIX/MEDIA_ROOT_LOCAL_PREFIX
    let this machine substitute its own local mount point without touching the shared DB.
    """
    settings = get_settings()
    remote_prefix = settings.media_root_remote_prefix
    local_prefix = settings.media_root_local_prefix
    if remote_prefix is None or local_prefix is None:
        return Path(stored_path)
    try:
        relative = Path(stored_path).relative_to(remote_prefix)
    except ValueError:
        return Path(stored_path)
    return local_prefix / relative
