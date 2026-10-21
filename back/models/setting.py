from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from back.db.session import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
