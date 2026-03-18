from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.contracts import (
    ChunkDraft,
    EmbeddingTask,
    ExtractedMetadata,
    IngestionExecutionResult,
)
from app.ingestion.qdrant_collections import QdrantCollectionManager
from app.models import (
    DocumentChunk,
    LegalDocumentType,
    VectorStoreBackend,
    VectorStorePoint,
)


@dataclass(slots=True)
class EmbeddedVector:
    chunk_key: str
    embedding_model: str
    embedding_version: str
    vector_dimension: int
    vector: list[float]
    text_checksum: str


@dataclass(slots=True)
class VectorPointDraft:
    point_id: str
    chunk_id: str
    doc_id: str
    backend: VectorStoreBackend
    collection_name: str
    embedding_model: str
    embedding_version: str
    vector_dimension: int
    vector: list[float]
    payload: dict[str, object]
    projected_at: datetime


@dataclass(slots=True)
class EmbeddingProjectionResult:
    point_ids: list[str]
    collection_name: str
    embedding_model: str
    embedding_version: str


@dataclass(slots=True)
class ReembeddingPlan:
    chunk_ids: list[str]
    target_model: str
    target_version: str


class EmbeddingService(ABC):
    def __init__(
        self,
        *,
        embedding_model: str,
        embedding_version: str,
        vector_dimension: int,
    ) -> None:
        self.embedding_model = embedding_model
        self.embedding_version = embedding_version
        self.vector_dimension = vector_dimension

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    def embed_tasks(self, tasks: list[EmbeddingTask]) -> list[EmbeddedVector]:
        if not tasks:
            return []

        vectors = self.embed_texts([task.text for task in tasks])
        embedded: list[EmbeddedVector] = []
        for task, vector in zip(tasks, vectors, strict=True):
            model_name = task.embedding_model or self.embedding_model
            version = task.embedding_version or self.embedding_version
            vector_dimension = task.vector_dimension or len(vector)
            embedded.append(
                EmbeddedVector(
                    chunk_key=task.chunk_key,
                    embedding_model=model_name,
                    embedding_version=version,
                    vector_dimension=vector_dimension,
                    vector=vector,
                    text_checksum=sha256(task.text.encode("utf-8")).hexdigest(),
                )
            )
        return embedded


class DeterministicBgeM3EmbeddingService(EmbeddingService):
    def __init__(
        self,
        *,
        embedding_model: str = "BGE-M3-v1.5",
        embedding_version: str = "deterministic-v1",
        vector_dimension: int = 24,
    ) -> None:
        super().__init__(
            embedding_model=embedding_model,
            embedding_version=embedding_version,
            vector_dimension=vector_dimension,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_single(text) for text in texts]

    def _embed_single(self, text: str) -> list[float]:
        buckets = [0.0] * self.vector_dimension
        tokens = text.lower().split()
        if not tokens:
            return buckets

        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            for index in range(self.vector_dimension):
                byte = digest[index % len(digest)]
                centered = (byte / 255.0) - 0.5
                buckets[index] += centered

        norm = math.sqrt(sum(value * value for value in buckets))
        if norm == 0:
            return buckets
        return [round(value / norm, 8) for value in buckets]


class VectorCollectionResolver:
    def resolve(self, metadata: ExtractedMetadata) -> str:
        if metadata.doc_type is LegalDocumentType.JUDGMENT:
            if (metadata.court or "").strip().lower() == "supreme court":
                return "sc_judgments"
            return "hc_judgments"
        if metadata.doc_type is LegalDocumentType.STATUTE:
            return "statutes"
        if metadata.doc_type is LegalDocumentType.CONSTITUTION:
            return "constitution"
        if metadata.doc_type is LegalDocumentType.ORDER:
            return "tribunal_orders"
        if metadata.doc_type is LegalDocumentType.LC_REPORT:
            return "lc_reports"
        return "doctrine_clusters"


class QdrantPointBuilder:
    def __init__(self, resolver: VectorCollectionResolver | None = None) -> None:
        self.resolver = resolver or VectorCollectionResolver()

    def build(
        self,
        *,
        doc_id: str,
        execution: IngestionExecutionResult,
        persisted_chunks: dict[str, DocumentChunk],
        embedded_vectors: list[EmbeddedVector],
    ) -> list[VectorPointDraft]:
        collection_name = self.resolver.resolve(execution.metadata)
        chunk_lookup = {chunk.chunk_key: chunk for chunk in execution.chunks}
        vector_lookup = {vector.chunk_key: vector for vector in embedded_vectors}
        projected_at = datetime.now(UTC)
        points: list[VectorPointDraft] = []

        for chunk_key, persisted_chunk in persisted_chunks.items():
            chunk_draft = chunk_lookup[chunk_key]
            vector = vector_lookup[chunk_key]
            payload = self._payload_for_chunk(
                doc_id=doc_id,
                chunk=persisted_chunk,
                chunk_draft=chunk_draft,
                metadata=execution.metadata,
                collection_name=collection_name,
                embedding_model=vector.embedding_model,
                embedding_version=vector.embedding_version,
            )
            points.append(
                VectorPointDraft(
                    point_id=persisted_chunk.chunk_id,
                    chunk_id=persisted_chunk.chunk_id,
                    doc_id=doc_id,
                    backend=VectorStoreBackend.QDRANT,
                    collection_name=collection_name,
                    embedding_model=vector.embedding_model,
                    embedding_version=vector.embedding_version,
                    vector_dimension=vector.vector_dimension,
                    vector=vector.vector,
                    payload=payload,
                    projected_at=projected_at,
                )
            )

        return points

    def _payload_for_chunk(
        self,
        *,
        doc_id: str,
        chunk: DocumentChunk,
        chunk_draft: ChunkDraft,
        metadata: ExtractedMetadata,
        collection_name: str,
        embedding_model: str,
        embedding_version: str,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "doc_id": doc_id,
            "chunk_id": chunk.chunk_id,
            "doc_type": metadata.doc_type.value,
            "court": chunk.court,
            "date": chunk.date.isoformat() if chunk.date is not None else None,
            "citation": chunk.citation,
            "section_header": chunk.section_header,
            "jurisdiction_binding": chunk.jurisdiction_binding,
            "jurisdiction_persuasive": chunk.jurisdiction_persuasive,
            "jurisdiction": metadata.attributes.get("jurisdiction"),
            "current_validity": chunk.current_validity.value,
            "practice_area": chunk.practice_area,
            "act_name": chunk.act_name,
            "section_number": chunk.section_number,
            "is_in_force": chunk.is_in_force,
            "bench_size": len(metadata.bench),
            "state": metadata.attributes.get("state"),
            "amendment_date": (
                chunk.amendment_date.isoformat() if chunk.amendment_date is not None else None
            ),
            "chunk_type": chunk_draft.attributes.get("chunk_type"),
            "doctrine_name": chunk_draft.attributes.get("doctrine_name")
            or metadata.attributes.get("doctrine_name"),
            "area_of_law": chunk_draft.attributes.get("area_of_law")
            or metadata.attributes.get("area_of_law"),
            "report_num": chunk_draft.attributes.get("report_num")
            or metadata.attributes.get("report_num"),
            "topic": chunk_draft.attributes.get("topic")
            or metadata.attributes.get("topic"),
            "year": chunk_draft.attributes.get("year") or metadata.attributes.get("year"),
            "collection_name": collection_name,
            "embedding_model": embedding_model,
            "embedding_version": embedding_version,
            "source_document_ref": metadata.source_document_ref,
        }
        for key, value in chunk_draft.attributes.items():
            payload.setdefault(key, value)
        return payload


class VectorStorePersister:
    def upsert(
        self,
        session: Session,
        point_drafts: list[VectorPointDraft],
    ) -> list[VectorStorePoint]:
        persisted: list[VectorStorePoint] = []
        for point in point_drafts:
            row = session.get(VectorStorePoint, point.point_id)
            if row is None:
                row = VectorStorePoint(
                    point_id=point.point_id,
                    chunk_id=point.chunk_id,
                    doc_id=point.doc_id,
                )
                session.add(row)

            row.backend = point.backend
            row.collection_name = point.collection_name
            row.embedding_model = point.embedding_model
            row.embedding_version = point.embedding_version
            row.vector_dimension = point.vector_dimension
            row.vector = point.vector
            row.payload = point.payload
            row.projected_at = point.projected_at
            row.is_active = True
            persisted.append(row)

        session.flush()
        return persisted


class EmbeddingPipeline:
    def __init__(
        self,
        *,
        service: EmbeddingService | None = None,
        point_builder: QdrantPointBuilder | None = None,
        collection_manager: QdrantCollectionManager | None = None,
        persister: VectorStorePersister | None = None,
    ) -> None:
        self.service = service or DeterministicBgeM3EmbeddingService()
        self.point_builder = point_builder or QdrantPointBuilder()
        self.collection_manager = collection_manager or QdrantCollectionManager(
            default_vector_size=self.service.vector_dimension
        )
        self.persister = persister or VectorStorePersister()

    def project(
        self,
        session: Session,
        *,
        execution: IngestionExecutionResult,
        doc_id: str,
    ) -> EmbeddingProjectionResult:
        if not execution.embedding_tasks:
            collection_name = self.point_builder.resolver.resolve(execution.metadata)
            return EmbeddingProjectionResult(
                point_ids=[],
                collection_name=collection_name,
                embedding_model=self.service.embedding_model,
                embedding_version=self.service.embedding_version,
            )

        persisted_chunks = self._load_persisted_chunks(session, doc_id, execution)
        embedded_vectors = self.service.embed_tasks(execution.embedding_tasks)
        point_drafts = self.point_builder.build(
            doc_id=doc_id,
            execution=execution,
            persisted_chunks=persisted_chunks,
            embedded_vectors=embedded_vectors,
        )
        if point_drafts:
            self.collection_manager.ensure_collection(
                session,
                point_drafts[0].collection_name,
                vector_size=point_drafts[0].vector_dimension,
            )
        persisted_points = self.persister.upsert(session, point_drafts)

        vector_lookup = {vector.chunk_key: vector for vector in embedded_vectors}
        if point_drafts:
            collection_name = point_drafts[0].collection_name
        else:
            collection_name = self.point_builder.resolver.resolve(execution.metadata)
        for chunk_key, chunk in persisted_chunks.items():
            vector = vector_lookup[chunk_key]
            chunk.embedding_id = chunk.chunk_id
            chunk.embedding_model = vector.embedding_model
            chunk.embedding_version = vector.embedding_version
            chunk.vector_collection = collection_name
            chunk.embedded_at = point_drafts[0].projected_at if point_drafts else datetime.now(UTC)
            chunk.needs_reembedding = False
            chunk.projection_stale = False
            chunk.stale_reason = None

        session.flush()
        return EmbeddingProjectionResult(
            point_ids=[point.point_id for point in persisted_points],
            collection_name=collection_name,
            embedding_model=embedded_vectors[0].embedding_model,
            embedding_version=embedded_vectors[0].embedding_version,
        )

    def _load_persisted_chunks(
        self,
        session: Session,
        doc_id: str,
        execution: IngestionExecutionResult,
    ) -> dict[str, DocumentChunk]:
        rows = session.execute(
            select(DocumentChunk).where(DocumentChunk.doc_id == doc_id)
        ).scalars().all()
        row_lookup = {row.chunk_id: row for row in rows}

        persisted: dict[str, DocumentChunk] = {}
        for chunk in execution.chunks:
            chunk_id = self._chunk_id_for(doc_id, chunk)
            persisted[chunk.chunk_key] = row_lookup[chunk_id]
        return persisted

    def _chunk_id_for(self, doc_id: str, chunk: ChunkDraft) -> str:
        from uuid import NAMESPACE_URL, uuid5

        return str(uuid5(NAMESPACE_URL, f"{doc_id}|{chunk.chunk_key}"))


class EmbeddingUpgradePlanner:
    def flag_for_reembedding(
        self,
        session: Session,
        *,
        target_model: str,
        target_version: str,
    ) -> ReembeddingPlan:
        rows = session.execute(select(DocumentChunk)).scalars().all()
        chunk_ids: list[str] = []
        for row in rows:
            if row.embedding_id is None:
                continue
            if row.embedding_model != target_model or row.embedding_version != target_version:
                row.needs_reembedding = True
                row.projection_stale = True
                row.stale_reason = (
                    f"Embedding upgrade required: {row.embedding_model}/{row.embedding_version}"
                    f" -> {target_model}/{target_version}"
                )
                chunk_ids.append(row.chunk_id)
        session.flush()
        return ReembeddingPlan(
            chunk_ids=chunk_ids,
            target_model=target_model,
            target_version=target_version,
        )
