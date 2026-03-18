from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.appeal_chain import AppealAuthorityResolution, AppealChainBuilder
from app.models import AppealOutcome, DocumentChunk, LegalDocument
from app.rag.resolution import CitationResolutionStatus, CitationResolver, ResolvedPlaceholder


class AppealSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AppealValidationStatus(StrEnum):
    VALID = "VALID"
    PENDING = "PENDING"
    REDIRECTED = "REDIRECTED"
    MODIFIED = "MODIFIED"
    REMANDED = "REMANDED"
    DISMISSED = "DISMISSED"


@dataclass(slots=True, frozen=True)
class AppealValidationResult:
    original_resolution: ResolvedPlaceholder
    effective_resolution: ResolvedPlaceholder
    status: AppealValidationStatus
    severity: AppealSeverity
    warning: str | None
    show_reversal_banner: bool
    supplementary_doc_id: str | None
    path_doc_ids: tuple[str, ...]


class AppealValidator:
    def __init__(
        self,
        *,
        builder: AppealChainBuilder | None = None,
        citation_resolver: CitationResolver | None = None,
    ) -> None:
        self.builder = builder or AppealChainBuilder()
        self.citation_resolver = citation_resolver or CitationResolver()

    def validate(
        self,
        session: Session,
        *,
        resolution: ResolvedPlaceholder,
    ) -> AppealValidationResult:
        if resolution.status is not CitationResolutionStatus.VERIFIED or resolution.doc_id is None:
            return AppealValidationResult(
                original_resolution=resolution,
                effective_resolution=resolution,
                status=AppealValidationStatus.VALID,
                severity=AppealSeverity.INFO,
                warning=None,
                show_reversal_banner=False,
                supplementary_doc_id=None,
                path_doc_ids=tuple(),
            )

        document = session.get(LegalDocument, resolution.doc_id)
        if document is None:
            return AppealValidationResult(
                original_resolution=resolution,
                effective_resolution=resolution,
                status=AppealValidationStatus.VALID,
                severity=AppealSeverity.INFO,
                warning=None,
                show_reversal_banner=False,
                supplementary_doc_id=None,
                path_doc_ids=(resolution.doc_id,),
            )

        authority = self.builder.resolve_final_authority(session, resolution.doc_id)
        if self._is_pending(document, authority):
            return AppealValidationResult(
                original_resolution=resolution,
                effective_resolution=resolution,
                status=AppealValidationStatus.PENDING,
                severity=AppealSeverity.WARNING,
                warning="Appeal pending — this may not be the final judgment.",
                show_reversal_banner=False,
                supplementary_doc_id=None,
                path_doc_ids=tuple(authority.path_doc_ids),
            )

        effective_resolution = resolution
        supplementary_doc_id: str | None = None
        if authority.use_doc_id != resolution.doc_id:
            target_document = session.get(LegalDocument, authority.use_doc_id)
            target_chunk = None
            if target_document is not None:
                target_chunk = self._best_chunk(session, authority.use_doc_id)
            if target_document is not None:
                effective_resolution = self.citation_resolver.build_verified_resolution(
                    placeholder=resolution.placeholder,
                    kind=resolution.kind,
                    document=target_document,
                    chunk=target_chunk,
                    confidence=resolution.confidence,
                    message="Updated to the final authority after appeal-chain validation.",
                )
                supplementary_doc_id = authority.use_doc_id

        status, severity, warning, show_reversal_banner = self._classify(authority, resolution)

        return AppealValidationResult(
            original_resolution=resolution,
            effective_resolution=effective_resolution,
            status=status,
            severity=severity,
            warning=warning,
            show_reversal_banner=show_reversal_banner,
            supplementary_doc_id=supplementary_doc_id,
            path_doc_ids=tuple(authority.path_doc_ids),
        )

    def _classify(
        self,
        authority: AppealAuthorityResolution,
        resolution: ResolvedPlaceholder,
    ) -> tuple[AppealValidationStatus, AppealSeverity, str | None, bool]:
        if (
            authority.effective_outcome is AppealOutcome.REVERSED
            and authority.use_doc_id != resolution.doc_id
        ):
            return (
                AppealValidationStatus.REDIRECTED,
                AppealSeverity.CRITICAL,
                authority.warning
                or (
                    "This judgment was reversed on appeal. "
                    f"Use final authority: {authority.use_doc_id}."
                ),
                True,
            )

        if authority.effective_outcome is AppealOutcome.MODIFIED:
            return (
                AppealValidationStatus.MODIFIED,
                AppealSeverity.WARNING,
                authority.warning
                or (
                    "This judgment was modified on appeal. "
                    f"Use final authority: {authority.use_doc_id}."
                ),
                False,
            )

        if authority.effective_outcome is AppealOutcome.REMANDED:
            return (
                AppealValidationStatus.REMANDED,
                AppealSeverity.WARNING,
                authority.warning or "This matter was remanded on appeal.",
                False,
            )

        if authority.effective_outcome is AppealOutcome.DISMISSED and authority.warning is not None:
            return (
                AppealValidationStatus.DISMISSED,
                AppealSeverity.INFO,
                authority.warning,
                False,
            )

        return (AppealValidationStatus.VALID, AppealSeverity.INFO, authority.warning, False)

    def _is_pending(
        self,
        document: LegalDocument,
        authority: AppealAuthorityResolution,
    ) -> bool:
        if not document.appeal_history:
            return False
        if any(node.is_final_authority for node in document.appeal_history):
            return False
        if authority.use_doc_id != document.doc_id:
            return False
        return True

    def _best_chunk(
        self,
        session: Session,
        doc_id: str,
    ) -> DocumentChunk | None:
        return session.scalar(
            select(DocumentChunk)
            .where(DocumentChunk.doc_id == doc_id)
            .order_by(DocumentChunk.chunk_index)
        )
