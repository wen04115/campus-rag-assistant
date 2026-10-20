from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    index_collection: Mapped[str | None] = mapped_column(
        String(63),
        nullable=True,
    )

class KnowledgeDocument(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    original_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    storage_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )

    size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id"),
        nullable=False,
        index=True,
    )

class KnowledgeChatRecord(Base):
    __tablename__ = "knowledge_chat_records"

    __table_args__ = (
        Index(
            "ix_knowledge_chat_records_kb_id_id",
            "knowledge_base_id",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey(
            "knowledge_bases.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    question: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    answer: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    sources: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
    )

    citations: Mapped[list[dict]] = mapped_column(
        JSON,
        nullable=False,
    )

    # 统一存储 UTC 时间；数据库字段不带时区。
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
    )
