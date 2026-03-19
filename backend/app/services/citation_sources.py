from __future__ import annotations

from app.ingestion.appeal_chain import AppealChainBuilder
from app.models import (
    AppealNode,
    DocumentChunk,
    LegalDocument,
    LegalDocumentType,
    StatuteDocument,
    StatuteSection,
)
from app.rag.appeal import AppealValidator
from app.rag.generator import PlaceholderKind
from app.rag.misgrounding import MisgroundingChecker
from app.rag.resolution import CitationResolver
from app.schemas.citation import (
    AppealChainRead,
    CitationSourceRead,
    CitationVerificationRead,
    StatuteSectionLookupRead,
)
from app.schemas.legal import AppealNodeRead, LegalDocumentRead, StatuteSectionRead
from sqlalchemy import select
from sqlalchemy.orm import Session


class CitationSourceStore:
    def __init__(
        self,
        *,
        appeal_builder: AppealChainBuilder | None = None,
        appeal_validator: AppealValidator | None = None,
        citation_resolver: CitationResolver | None = None,
        misgrounding_checker: MisgroundingChecker | None = None,
    ) -> None:
        self.appeal_builder = appeal_builder or AppealChainBuilder()
        self.citation_resolver = citation_resolver or CitationResolver()
        self.appeal_validator = appeal_validator or AppealValidator(
            builder=self.appeal_builder,
            citation_resolver=self.citation_resolver,
        )
        self.misgrounding_checker = misgrounding_checker or MisgroundingChecker()

    def get_source(
        self,
        session: Session,
        *,
        doc_id: str,
        chunk_id: str | None = None,
    ) -> CitationSourceRead:
        document = self._require_document(session, doc_id)
        chunk = self._resolve_chunk(session, doc_id=doc_id, chunk_id=chunk_id)
        resolution = self.citation_resolver.build_verified_resolution(
            placeholder=f"[SOURCE:{doc_id}]",
            kind=self._placeholder_kind(document),
            document=document,
            chunk=chunk,
            confidence=1.0,
            message="Loaded from the canonical source viewer endpoint.",
        )
        appeal_result = self.appeal_validator.validate(session, resolution=resolution)
        effective_document = self._require_document(
            session,
            appeal_result.effective_resolution.doc_id or doc_id,
        )
        effective_chunk = self._resolve_chunk(
            session,
            doc_id=effective_document.doc_id,
            chunk_id=appeal_result.effective_resolution.chunk_id,
        )

        return CitationSourceRead(
            doc_id=document.doc_id,
            effective_doc_id=effective_document.doc_id,
            chunk_id=chunk.chunk_id if chunk is not None else None,
            effective_chunk_id=effective_chunk.chunk_id if effective_chunk is not None else None,
            doc_type=effective_document.doc_type,
            citation=resolution.rendered_value,
            effective_citation=appeal_result.effective_resolution.rendered_value,
            title=self._title_for_document(effective_document, effective_chunk),
            court=effective_document.court,
            date=effective_document.date,
            section_header=effective_chunk.section_header if effective_chunk is not None else None,
            act_name=effective_chunk.act_name if effective_chunk is not None else None,
            section_number=effective_chunk.section_number if effective_chunk is not None else None,
            current_validity=effective_document.current_validity,
            is_in_force=effective_chunk.is_in_force if effective_chunk is not None else None,
            source_passage=self._source_passage(effective_document, effective_chunk),
            source_url=effective_document.source_url,
            source_system=effective_document.source_system,
            source_document_ref=effective_document.source_document_ref,
            appeal_status=appeal_result.status,
            appeal_severity=appeal_result.severity,
            appeal_warning=appeal_result.warning,
            path_doc_ids=list(appeal_result.path_doc_ids),
        )

    def verify_citation(
        self,
        session: Session,
        *,
        doc_id: str,
        chunk_id: str | None = None,
        claim: str | None = None,
    ) -> CitationVerificationRead:
        document = self._require_document(session, doc_id)
        chunk = self._resolve_chunk(session, doc_id=doc_id, chunk_id=chunk_id)
        resolution = self.citation_resolver.build_verified_resolution(
            placeholder=f"[VERIFY:{doc_id}]",
            kind=self._placeholder_kind(document),
            document=document,
            chunk=chunk,
            confidence=1.0,
            message="Loaded from the canonical citation verification endpoint.",
        )
        appeal_result = self.appeal_validator.validate(session, resolution=resolution)
        effective_document = self._require_document(
            session,
            appeal_result.effective_resolution.doc_id or doc_id,
        )
        effective_chunk = self._resolve_chunk(
            session,
            doc_id=effective_document.doc_id,
            chunk_id=appeal_result.effective_resolution.chunk_id,
        )

        misgrounding_result = (
            self.misgrounding_checker.check_claim(
                session,
                claim=claim,
                resolution=appeal_result.effective_resolution,
            )
            if claim
            else None
        )

        return CitationVerificationRead(
            doc_id=document.doc_id,
            effective_doc_id=effective_document.doc_id,
            chunk_id=chunk.chunk_id if chunk is not None else None,
            effective_chunk_id=effective_chunk.chunk_id if effective_chunk is not None else None,
            citation=resolution.rendered_value,
            effective_citation=appeal_result.effective_resolution.rendered_value,
            resolution_status=appeal_result.effective_resolution.status,
            current_validity=effective_document.current_validity,
            is_in_force=effective_chunk.is_in_force if effective_chunk is not None else None,
            appeal_status=appeal_result.status,
            appeal_severity=appeal_result.severity,
            appeal_warning=appeal_result.warning,
            path_doc_ids=list(appeal_result.path_doc_ids),
            claim=claim,
            grounding_status=misgrounding_result.status if misgrounding_result else None,
            grounding_action=misgrounding_result.action if misgrounding_result else None,
            grounding_confidence=(
                misgrounding_result.confidence if misgrounding_result is not None else None
            ),
            grounding_similarity=(
                misgrounding_result.similarity if misgrounding_result is not None else None
            ),
            source_passage=(
                misgrounding_result.source_passage
                if misgrounding_result is not None
                else self._source_passage(effective_document, effective_chunk)
            ),
            message=(
                misgrounding_result.message
                if misgrounding_result is not None
                else appeal_result.warning
                or appeal_result.effective_resolution.message
            ),
        )

    def get_appeal_chain(self, session: Session, *, doc_id: str) -> AppealChainRead:
        document = self._require_document(session, doc_id)
        authority = self.appeal_builder.resolve_final_authority(session, doc_id)
        nodes = session.scalars(
            select(AppealNode)
            .where(AppealNode.document_doc_id == doc_id)
            .order_by(AppealNode.court_level)
        ).all()

        return AppealChainRead(
            doc_id=document.doc_id,
            use_doc_id=authority.use_doc_id,
            effective_outcome=authority.effective_outcome,
            is_final_authority=authority.is_final_authority,
            warning=authority.warning,
            path_doc_ids=list(authority.path_doc_ids),
            nodes=[AppealNodeRead.model_validate(node) for node in nodes],
        )

    def get_judgment(self, session: Session, *, doc_id: str) -> LegalDocumentRead:
        document = self._require_document(session, doc_id)
        if document.doc_type is not LegalDocumentType.JUDGMENT:
            raise ValueError("The requested document is not a judgment.")
        return LegalDocumentRead.model_validate(document)

    def get_statute_section(
        self,
        session: Session,
        *,
        act_id: str,
        section_number: str,
    ) -> StatuteSectionLookupRead:
        statute_document = session.get(StatuteDocument, act_id)
        if statute_document is None:
            raise ValueError(f"No statute document exists for '{act_id}'.")

        section = session.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_doc_id == act_id,
                StatuteSection.section_number == section_number,
            )
        )
        if section is None:
            raise ValueError(
                f"No section '{section_number}' exists for statute document '{act_id}'."
            )

        return StatuteSectionLookupRead(
            act_id=act_id,
            act_name=statute_document.act_name,
            section_number=section.section_number,
            document=LegalDocumentRead.model_validate(statute_document.document),
            section=StatuteSectionRead.model_validate(section),
        )

    def _require_document(self, session: Session, doc_id: str) -> LegalDocument:
        document = session.get(LegalDocument, doc_id)
        if document is None:
            raise ValueError(f"No legal document exists for '{doc_id}'.")
        return document

    def _resolve_chunk(
        self,
        session: Session,
        *,
        doc_id: str,
        chunk_id: str | None,
    ) -> DocumentChunk | None:
        if chunk_id is not None:
            chunk = session.get(DocumentChunk, chunk_id)
            if chunk is None or chunk.doc_id != doc_id:
                raise ValueError(
                    f"No document chunk '{chunk_id}' exists for legal document '{doc_id}'."
                )
            return chunk

        return session.scalar(
            select(DocumentChunk)
            .where(DocumentChunk.doc_id == doc_id)
            .order_by(DocumentChunk.chunk_index)
        )

    def _placeholder_kind(self, document: LegalDocument) -> PlaceholderKind:
        if document.doc_type in {LegalDocumentType.STATUTE, LegalDocumentType.CONSTITUTION}:
            return PlaceholderKind.STATUTE
        return PlaceholderKind.CITE

    def _source_passage(
        self,
        document: LegalDocument,
        chunk: DocumentChunk | None,
    ) -> str | None:
        if chunk is not None and chunk.text:
            return chunk.text
        return document.ratio_decidendi or document.full_text

    def _title_for_document(
        self,
        document: LegalDocument,
        chunk: DocumentChunk | None,
    ) -> str:
        if document.doc_type is LegalDocumentType.JUDGMENT:
            appellant = document.parties.get("appellant") or document.parties.get("petitioner")
            respondent = document.parties.get("respondent") or document.parties.get(
                "opposite_party"
            )
            if appellant and respondent:
                return f"{appellant} v {respondent}"

        if chunk is not None and chunk.act_name and chunk.section_number:
            return f"{chunk.act_name}, Section {chunk.section_number}"
        if chunk is not None and chunk.section_header:
            return chunk.section_header
        if document.citation:
            return document.citation
        return document.court or document.doc_type.value


citation_source_store = CitationSourceStore()
