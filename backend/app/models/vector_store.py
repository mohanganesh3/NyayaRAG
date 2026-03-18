from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.legal import DocumentChunk, LegalDocument


class VectorStoreBackend(StrEnum):
    QDRANT = "qdrant"


class VectorDistanceMetric(StrEnum):
    COSINE = "cosine"


class VectorStoreCollection(TimestampMixin, Base):
    __tablename__ = "vector_store_collections"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    backend: Mapped[VectorStoreBackend] = mapped_column(
        Enum(VectorStoreBackend, native_enum=False),
        nullable=False,
        default=VectorStoreBackend.QDRANT,
    )
    vector_size: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_metric: Mapped[VectorDistanceMetric] = mapped_column(
        Enum(VectorDistanceMetric, native_enum=False),
        nullable=False,
        default=VectorDistanceMetric.COSINE,
    )
    indexed_payload_fields: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class VectorStorePoint(TimestampMixin, Base):
    __tablename__ = "vector_store_points"

    point_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("document_chunks.chunk_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    doc_id: Mapped[str] = mapped_column(
        ForeignKey("legal_documents.doc_id", ondelete="CASCADE"),
        nullable=False,
    )
    backend: Mapped[VectorStoreBackend] = mapped_column(
        Enum(VectorStoreBackend, native_enum=False),
        nullable=False,
        default=VectorStoreBackend.QDRANT,
    )
    collection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(100), nullable=False)
    vector_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    projected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    chunk: Mapped[DocumentChunk] = relationship(back_populates="vector_point")
    document: Mapped[LegalDocument] = relationship()
