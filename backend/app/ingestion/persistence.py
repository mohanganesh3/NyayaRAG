from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as date_value
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.orm import Session

from app.ingestion.contracts import (
    ChunkDraft,
    IngestionExecutionResult,
    IngestionJobContext,
    ProjectionPlan,
    ProjectionTarget,
)
from app.ingestion.source_catalog import SOURCE_CATALOG
from app.models import (
    ApprovalStatus,
    DocumentChunk,
    IngestionRun,
    IngestionRunStatus,
    LegalDocument,
    LegalDocumentType,
    SourceRegistry,
    SourceType,
    StatuteAmendment,
    StatuteDocument,
    StatuteSection,
    ValidityStatus,
)


@dataclass(slots=True)
class PersistedIngestionResult:
    doc_id: str
    ingestion_run_id: str
    source_key: str


class CanonicalIngestionPersister:
    def persist(
        self,
        session: Session,
        result: IngestionExecutionResult,
        context: IngestionJobContext,
    ) -> PersistedIngestionResult:
        registry = self._ensure_source_registry(session, context)
        ingestion_run = IngestionRun(
            source_registry=registry,
            status=IngestionRunStatus.RUNNING,
            parser_version=context.parser_version,
            triggered_by="ingestion_orchestrator",
            started_at=datetime.now(UTC),
            checksum_algorithm="sha256",
            source_snapshot_url=context.source_url,
            approval_status=registry.approval_status,
        )
        session.add(ingestion_run)
        session.flush()

        canonical_projection = self._get_projection(
            result.projections,
            ProjectionTarget.CANONICAL_DB,
        )
        doc_id = self._persist_document(
            session,
            result,
            context,
            canonical_projection,
            registry,
            ingestion_run,
        )

        ingestion_run.status = IngestionRunStatus.SUCCEEDED
        ingestion_run.completed_at = datetime.now(UTC)
        ingestion_run.document_count = 1
        ingestion_run.new_document_count = 1
        ingestion_run.updated_document_count = 0
        ingestion_run.failed_document_count = 0
        session.flush()

        return PersistedIngestionResult(
            doc_id=doc_id,
            ingestion_run_id=ingestion_run.id,
            source_key=context.source_key,
        )

    def _ensure_source_registry(
        self,
        session: Session,
        context: IngestionJobContext,
    ) -> SourceRegistry:
        registry = session.get(SourceRegistry, context.source_key)
        entry = SOURCE_CATALOG.get(context.source_key)
        if registry is None:
            source_type = (
                entry.source_type
                if entry is not None
                else self._coerce_source_type(context.metadata.get("source_type"))
            )
            registry = SourceRegistry(
                source_key=context.source_key,
                display_name=entry.display_name if entry else context.source_key,
                source_type=source_type,
                base_url=entry.base_url if entry else context.source_url,
                canonical_hostname=entry.canonical_hostname if entry else context.source_url,
                jurisdiction_scope=entry.jurisdiction_scope if entry else ["All India"],
                update_frequency=entry.update_frequency if entry else "unknown",
                access_method=entry.access_method if entry else "manual",
                is_public=True,
                is_active=True,
                approval_status=entry.approval_status if entry else ApprovalStatus.APPROVED,
                default_parser_version=(
                    entry.default_parser_version if entry else context.parser_version
                ),
                notes=entry.notes if entry else None,
            )
            session.add(registry)
            session.flush()
            return registry

        if entry is not None:
            registry.display_name = entry.display_name
            registry.base_url = entry.base_url
            registry.canonical_hostname = entry.canonical_hostname
            registry.jurisdiction_scope = entry.jurisdiction_scope
            registry.update_frequency = entry.update_frequency
            registry.access_method = entry.access_method
            registry.default_parser_version = entry.default_parser_version
            registry.approval_status = entry.approval_status
        return registry

    def _persist_document(
        self,
        session: Session,
        result: IngestionExecutionResult,
        context: IngestionJobContext,
        canonical_projection: ProjectionPlan,
        registry: SourceRegistry,
        ingestion_run: IngestionRun,
    ) -> str:
        metadata = result.metadata
        parsed = result.parsed
        projection_payload = canonical_projection.payload
        document_payload = self._as_object_dict(projection_payload.get("document"))
        metadata_attrs = metadata.attributes
        parsed_attrs = parsed.attributes

        doc_id = str(
            uuid5(
                NAMESPACE_URL,
                f"{context.source_key}|{metadata.source_document_ref}|{result.fetched.checksum}",
            )
        )

        legal_document = session.get(LegalDocument, doc_id)
        if legal_document is None:
            legal_document = LegalDocument(doc_id=doc_id, doc_type=metadata.doc_type)
            session.add(legal_document)
            session.flush()

        date_text = document_payload.get("date") or metadata.date_text
        legal_document.doc_type = metadata.doc_type
        legal_document.court = (
            self._as_optional_str(document_payload.get("court")) or metadata.court
        )
        legal_document.bench = self._as_str_list(document_payload.get("bench")) or metadata.bench
        legal_document.coram = self._as_optional_int(document_payload.get("coram")) or (
            len(metadata.bench) or None
        )
        legal_document.date = self._parse_date(date_text)
        legal_document.citation = (
            self._as_optional_str(document_payload.get("citation")) or metadata.citation
        )
        legal_document.neutral_citation = (
            self._as_optional_str(document_payload.get("neutral_citation"))
            or metadata.neutral_citation
        )
        legal_document.parties = (
            self._as_str_dict(document_payload.get("parties")) or metadata.parties
        )
        legal_document.jurisdiction_binding = (
            self._as_str_list(document_payload.get("jurisdiction_binding"))
            or self._as_str_list(metadata_attrs.get("jurisdiction_binding"))
            or self._default_binding(metadata.court, metadata.doc_type)
        )
        legal_document.jurisdiction_persuasive = (
            self._as_str_list(document_payload.get("jurisdiction_persuasive"))
            or self._as_str_list(metadata_attrs.get("jurisdiction_persuasive"))
            or []
        )
        legal_document.current_validity = self._coerce_validity(
            document_payload.get("current_validity")
            or metadata_attrs.get("current_validity")
            or ValidityStatus.GOOD_LAW
        )
        legal_document.distinguished_by = self._as_str_list(
            document_payload.get("distinguished_by")
        )
        legal_document.followed_by = self._as_str_list(document_payload.get("followed_by"))
        legal_document.statutes_interpreted = self._as_object_dict_list(
            document_payload.get("statutes_interpreted")
        )
        legal_document.statutes_applied = self._as_object_dict_list(
            document_payload.get("statutes_applied")
        )
        legal_document.citations_made = []
        legal_document.headnotes = self._as_str_list(parsed_attrs.get("headnotes"))
        legal_document.ratio_decidendi = self._as_optional_str(parsed_attrs.get("ratio_decidendi"))
        legal_document.obiter_dicta = self._as_str_list(parsed_attrs.get("obiter_dicta"))
        legal_document.practice_areas = (
            self._as_str_list(document_payload.get("practice_areas"))
            or self._as_str_list(metadata_attrs.get("practice_areas"))
            or []
        )
        legal_document.language = metadata.language
        legal_document.full_text = (
            self._as_optional_str(document_payload.get("full_text")) or parsed.body_text
        )
        legal_document.source_registry = registry
        legal_document.source_url = context.source_url
        legal_document.source_document_ref = metadata.source_document_ref
        legal_document.fetched_at = result.fetched.fetched_at
        legal_document.checksum = result.fetched.checksum
        legal_document.parser_version = context.parser_version
        legal_document.ingestion_run = ingestion_run
        legal_document.approval_status = registry.approval_status

        legal_document.appeal_history.clear()
        legal_document.chunks.clear()
        if legal_document.statute_document is not None:
            legal_document.statute_document.sections.clear()
            legal_document.statute_document = None

        chunk_overrides = self._as_object_dict(projection_payload.get("chunks"))
        for chunk in result.chunks:
            legal_document.chunks.append(
                self._build_chunk(doc_id, chunk, result, legal_document, chunk_overrides)
            )

        statute_payload = self._as_object_dict(parsed_attrs.get("statute_document")) or (
            self._as_object_dict(projection_payload.get("statute_document"))
        )
        if statute_payload:
            legal_document.statute_document = self._build_statute_document(doc_id, statute_payload)

        session.flush()
        return doc_id

    def _build_chunk(
        self,
        doc_id: str,
        chunk: ChunkDraft,
        result: IngestionExecutionResult,
        legal_document: LegalDocument,
        chunk_overrides: dict[str, object],
    ) -> DocumentChunk:
        embedding_lookup = {task.chunk_key: task for task in result.embedding_tasks}
        task = embedding_lookup.get(chunk.chunk_key)
        statute_payload = self._as_object_dict(result.parsed.attributes.get("statute_document"))

        return DocumentChunk(
            chunk_id=str(uuid5(NAMESPACE_URL, f"{doc_id}|{chunk.chunk_key}")),
            doc_id=doc_id,
            doc_type=legal_document.doc_type,
            text=chunk.text,
            text_normalized=" ".join(chunk.text.split()),
            chunk_index=chunk.chunk_index,
            total_chunks=chunk.total_chunks,
            section_header=chunk.section_header,
            court=legal_document.court,
            date=legal_document.date,
            citation=legal_document.citation,
            jurisdiction_binding=legal_document.jurisdiction_binding,
            jurisdiction_persuasive=legal_document.jurisdiction_persuasive,
            current_validity=legal_document.current_validity,
            practice_area=legal_document.practice_areas,
            act_name=self._as_optional_str(chunk.attributes.get("act_name"))
            or self._as_optional_str(statute_payload.get("act_name")),
            section_number=self._as_optional_str(chunk.attributes.get("section_number")),
            is_in_force=self._as_optional_bool(chunk.attributes.get("is_in_force")),
            amendment_date=self._parse_date(chunk.attributes.get("amendment_date")),
            embedding_model=task.embedding_model if task else None,
            embedding_version=task.embedding_version if task else None,
        )

    def _build_statute_document(
        self,
        doc_id: str,
        payload: dict[str, object],
    ) -> StatuteDocument:
        statute_document = StatuteDocument(
            doc_id=doc_id,
            act_name=str(payload["act_name"]),
            short_title=self._as_optional_str(payload.get("short_title")),
            replaced_by=self._as_optional_str(payload.get("replaced_by")),
            replaced_on=self._parse_date(payload.get("replaced_on")),
            current_sections_in_force=self._as_str_list(payload.get("current_sections_in_force")),
            jurisdiction=str(payload.get("jurisdiction", "Central")),
            enforcement_date=self._parse_date(payload.get("enforcement_date")),
            current_validity=bool(payload.get("current_validity", True)),
        )

        for section_payload in self._as_object_dict_list(payload.get("sections")):
            section_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"{doc_id}|section|{section_payload['section_number']}",
                )
            )
            section = StatuteSection(
                id=section_id,
                section_number=str(section_payload["section_number"]),
                heading=self._as_optional_str(section_payload.get("heading")),
                text=str(section_payload["text"]),
                original_text=self._as_optional_str(section_payload.get("original_text")),
                is_in_force=bool(section_payload.get("is_in_force", True)),
                corresponding_new_section=self._as_optional_str(
                    section_payload.get("corresponding_new_section")
                ),
                punishment=self._as_optional_str(section_payload.get("punishment")),
                cases_interpreting=self._as_str_list(section_payload.get("cases_interpreting")),
            )
            for amendment_payload in self._as_object_dict_list(section_payload.get("amendments")):
                section.amendments.append(
                    StatuteAmendment(
                        id=str(
                            uuid5(
                                NAMESPACE_URL,
                                f"{section_id}|amendment|{amendment_payload['amendment_label']}",
                            )
                        ),
                        amendment_label=str(amendment_payload["amendment_label"]),
                        amendment_date=self._parse_date(amendment_payload.get("amendment_date")),
                        effective_date=self._parse_date(amendment_payload.get("effective_date")),
                        summary=self._as_optional_str(amendment_payload.get("summary")),
                        previous_text=self._as_optional_str(amendment_payload.get("previous_text")),
                        updated_text=self._as_optional_str(amendment_payload.get("updated_text")),
                    )
                )
            statute_document.sections.append(section)

        return statute_document

    def _get_projection(
        self,
        projections: list[ProjectionPlan],
        target: ProjectionTarget,
    ) -> ProjectionPlan:
        for projection in projections:
            if projection.target is target:
                return projection
        raise ValueError(f"Missing required projection target: {target}")

    def _parse_date(self, value: object) -> date_value | None:
        if value is None:
            return None
        if isinstance(value, date_value):
            return value
        if not isinstance(value, str):
            return None

        for fmt in ("%Y-%m-%d", "%B %d, %Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    def _default_binding(
        self,
        court: str | None,
        doc_type: LegalDocumentType,
    ) -> list[str]:
        if doc_type in {LegalDocumentType.CONSTITUTION, LegalDocumentType.STATUTE}:
            return ["All India"]
        if court == "Supreme Court":
            return ["All India"]
        if court:
            return [court]
        return ["All India"]

    def _coerce_validity(self, value: object) -> ValidityStatus:
        if isinstance(value, ValidityStatus):
            return value
        if isinstance(value, str):
            return ValidityStatus(value)
        return ValidityStatus.GOOD_LAW

    def _as_optional_str(self, value: object) -> str | None:
        if value is None:
            return None
        return str(value)

    def _as_optional_bool(self, value: object) -> bool | None:
        if value is None:
            return None
        return bool(value)

    def _as_optional_int(self, value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def _as_str_list(self, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    def _as_str_dict(self, value: object) -> dict[str, str]:
        if isinstance(value, dict):
            return {str(key): str(item) for key, item in value.items()}
        return {}

    def _as_object_dict(self, value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return value
        return {}

    def _as_object_dict_list(self, value: object) -> list[dict[str, object]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def _coerce_source_type(self, value: object) -> SourceType:
        if isinstance(value, SourceType):
            return value
        if isinstance(value, str):
            return SourceType(value)
        return SourceType.OTHER
