from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    ArtifactPromotionState,
    ArtifactProvenance,
    ProvenanceTier,
    SourcePartition,
    SourcePartitionStatus,
)

_ENSURE_SOURCE_URL_INDEX_SQL = text(
    "CREATE INDEX IF NOT EXISTS idx_legal_documents_source_system_source_url "
    "ON legal_documents(source_system, source_url)"
)
_EXISTS_BY_SOURCE_URL_SQL = text(
    "SELECT 1 "
    "FROM legal_documents "
    "WHERE source_system = :source_system AND source_url = :source_url "
    "LIMIT 1"
)


def ensure_source_url_index(session: Session) -> None:
    """Create the lookup index once so collectors can cheaply skip existing URLs."""
    session.execute(_ENSURE_SOURCE_URL_INDEX_SQL)
    session.commit()


def document_exists_by_source_url(
    session: Session,
    *,
    source_system: str,
    source_url: str,
) -> bool:
    row = session.execute(
        _EXISTS_BY_SOURCE_URL_SQL,
        {"source_system": source_system, "source_url": source_url},
    ).first()
    return row is not None


def _table_columns(session: Session, table_name: str) -> set[str]:
    rows = session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {str(row[1]) for row in rows if len(row) > 1}


def _ensure_column(session: Session, table_name: str, column_name: str, ddl: str) -> None:
    if column_name in _table_columns(session, table_name):
        return
    session.execute(text(ddl))


def ensure_collection_control_schema(session: Session) -> None:
    bind = session.get_bind()
    if bind is not None:
        Base.metadata.create_all(
            bind,
            tables=[SourcePartition.__table__, ArtifactProvenance.__table__],
            checkfirst=True,
        )

    legal_doc_columns = {
        "title": "ALTER TABLE legal_documents ADD COLUMN title VARCHAR(1000)",
        "date_text": "ALTER TABLE legal_documents ADD COLUMN date_text VARCHAR(255)",
        "decision_date": "ALTER TABLE legal_documents ADD COLUMN decision_date DATE",
        "publication_date": "ALTER TABLE legal_documents ADD COLUMN publication_date DATE",
        "collector_run_id": "ALTER TABLE legal_documents ADD COLUMN collector_run_id VARCHAR(36)",
        "seed_url": "ALTER TABLE legal_documents ADD COLUMN seed_url VARCHAR(1000)",
        "detail_url": "ALTER TABLE legal_documents ADD COLUMN detail_url VARCHAR(1000)",
        "artifact_url": "ALTER TABLE legal_documents ADD COLUMN artifact_url VARCHAR(1000)",
        "source_surface": "ALTER TABLE legal_documents ADD COLUMN source_surface VARCHAR(255)",
        "provenance_tier": "ALTER TABLE legal_documents ADD COLUMN provenance_tier VARCHAR(100)",
        "mime_type": "ALTER TABLE legal_documents ADD COLUMN mime_type VARCHAR(255)",
        "is_ocr": "ALTER TABLE legal_documents ADD COLUMN is_ocr BOOLEAN",
        "ocr_confidence": "ALTER TABLE legal_documents ADD COLUMN ocr_confidence FLOAT",
    }
    for column_name, ddl in legal_doc_columns.items():
        _ensure_column(session, "legal_documents", column_name, ddl)

    registry_columns = {
        "collector_type": "ALTER TABLE source_registries ADD COLUMN collector_type VARCHAR(100)",
        "canonical_surfaces": "ALTER TABLE source_registries ADD COLUMN canonical_surfaces JSON",
        "mirror_surfaces": "ALTER TABLE source_registries ADD COLUMN mirror_surfaces JSON",
        "partition_scheme": "ALTER TABLE source_registries ADD COLUMN partition_scheme VARCHAR(255)",
        "expected_proof_type": "ALTER TABLE source_registries ADD COLUMN expected_proof_type VARCHAR(100)",
        "auth_mode": "ALTER TABLE source_registries ADD COLUMN auth_mode VARCHAR(100)",
        "critical": "ALTER TABLE source_registries ADD COLUMN critical BOOLEAN NOT NULL DEFAULT 1",
        "metadata_profile": "ALTER TABLE source_registries ADD COLUMN metadata_profile JSON",
    }
    for column_name, ddl in registry_columns.items():
        _ensure_column(session, "source_registries", column_name, ddl)

    session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_source_partitions_source_status "
            "ON source_partitions(source_key, status)"
        )
    )
    session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_artifact_provenance_doc_sha "
            "ON artifact_provenance(doc_id, sha256)"
        )
    )
    session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_legal_documents_source_system_source_document_ref "
            "ON legal_documents(source_system, source_document_ref)"
        )
    )
    session.flush()


def record_source_partition(
    session: Session,
    *,
    source_key: str,
    partition_key: str,
    surface_url: str,
    partition_kind: str | None = None,
    expected_hint: str | None = None,
    discovered_increment: int = 0,
    ingested_increment: int = 0,
    status: SourcePartitionStatus | str | None = None,
    error_class: str | None = None,
    proof_note: str | None = None,
    ingestion_run_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> SourcePartition:
    ensure_collection_control_schema(session)
    row = session.execute(
        select(SourcePartition).where(
            SourcePartition.source_key == source_key,
            SourcePartition.partition_key == partition_key,
            SourcePartition.surface_url == surface_url,
        )
    ).scalar_one_or_none()
    if row is None:
        row = SourcePartition(
            source_key=source_key,
            ingestion_run_id=ingestion_run_id,
            partition_key=partition_key,
            surface_url=surface_url,
            partition_kind=partition_kind,
            expected_hint=expected_hint,
            discovered_count=max(0, int(discovered_increment)),
            ingested_count=max(0, int(ingested_increment)),
            status=(
                SourcePartitionStatus(str(status))
                if status is not None
                else SourcePartitionStatus.DISCOVERING
            ),
            last_verified_at=datetime.now(UTC),
            error_class=error_class,
            proof_note=proof_note,
            payload=payload or None,
        )
        session.add(row)
        session.flush()
        return row

    row.partition_kind = partition_kind or row.partition_kind
    row.expected_hint = expected_hint or row.expected_hint
    row.ingestion_run_id = ingestion_run_id or row.ingestion_run_id
    row.discovered_count = max(0, int(row.discovered_count) + int(discovered_increment))
    row.ingested_count = max(0, int(row.ingested_count) + int(ingested_increment))
    if status is not None:
        row.status = SourcePartitionStatus(str(status))
    elif ingested_increment > 0 or discovered_increment > 0:
        row.status = SourcePartitionStatus.RUNNING
    row.last_verified_at = datetime.now(UTC)
    row.error_class = error_class
    row.proof_note = proof_note or row.proof_note
    if payload:
        row.payload = {**(row.payload or {}), **payload}
    session.flush()
    return row


def record_artifact_provenance(
    session: Session,
    *,
    doc_id: str | None,
    source_key: str | None,
    canonical_url: str | None,
    mirror_url: str | None,
    retrieved_from: str | None,
    provenance_tier: ProvenanceTier | str,
    sha256: str | None,
    mime_type: str | None,
    http_status: int | None,
    fetched_at: datetime | None,
    promotion_state: ArtifactPromotionState | str,
    ingestion_run_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> ArtifactProvenance:
    ensure_collection_control_schema(session)
    row = session.execute(
        select(ArtifactProvenance).where(
            ArtifactProvenance.doc_id == doc_id,
            ArtifactProvenance.canonical_url == canonical_url,
            ArtifactProvenance.sha256 == sha256,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ArtifactProvenance(
            doc_id=doc_id,
            source_key=source_key,
            ingestion_run_id=ingestion_run_id,
            canonical_url=canonical_url,
            mirror_url=mirror_url,
            retrieved_from=retrieved_from,
            provenance_tier=ProvenanceTier(str(provenance_tier)),
            sha256=sha256,
            mime_type=mime_type,
            http_status=http_status,
            fetched_at=fetched_at,
            promotion_state=ArtifactPromotionState(str(promotion_state)),
            payload=payload or None,
        )
        session.add(row)
        session.flush()
        return row

    row.source_key = source_key or row.source_key
    row.ingestion_run_id = ingestion_run_id or row.ingestion_run_id
    row.mirror_url = mirror_url or row.mirror_url
    row.retrieved_from = retrieved_from or row.retrieved_from
    row.provenance_tier = ProvenanceTier(str(provenance_tier))
    row.mime_type = mime_type or row.mime_type
    row.http_status = http_status if http_status is not None else row.http_status
    row.fetched_at = fetched_at or row.fetched_at
    row.promotion_state = ArtifactPromotionState(str(promotion_state))
    if payload:
        row.payload = {**(row.payload or {}), **payload}
    session.flush()
    return row
