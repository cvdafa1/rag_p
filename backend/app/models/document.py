from sqlalchemy import String, Text, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import uuid


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    doc_id:     Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_name:Mapped[str]       = mapped_column(String(255), nullable=False)
    filename:   Mapped[str]       = mapped_column(String(512), nullable=False)
    file_path:  Mapped[str]       = mapped_column(Text, nullable=False)
    file_hash:  Mapped[str | None]= mapped_column(String(64))
    version:    Mapped[str]       = mapped_column(String(32), default="v1.0")
    status:     Mapped[str]       = mapped_column(String(32), default="processing")
    uploader:   Mapped[str | None] = mapped_column(String(128))
    dept:       Mapped[str | None] = mapped_column(String(128))
    chunk_count:Mapped[int]       = mapped_column(Integer, default=0)
    error_msg:  Mapped[str | None] = mapped_column(Text)
    meta:       Mapped[dict]      = mapped_column(JSONB, default=dict)
    created_at: Mapped[DateTime]   = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime]   = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id:         Mapped[int]        = mapped_column(primary_key=True, autoincrement=True)
    doc_id:     Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), index=True)
    version:    Mapped[str]        = mapped_column(String(32))
    filename:   Mapped[str]        = mapped_column(String(512))
    file_path:  Mapped[str]        = mapped_column(Text)
    chunk_ids:  Mapped[list]       = mapped_column(JSONB, default=list)
    status:     Mapped[str]        = mapped_column(String(32))
    created_at: Mapped[DateTime]   = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )