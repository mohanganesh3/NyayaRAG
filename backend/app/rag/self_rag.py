from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from app.rag.appeal import AppealValidationResult, AppealValidationStatus, AppealValidator
from app.rag.misgrounding import MisgroundingChecker, MisgroundingResult, MisgroundingStatus
from app.rag.resolution import (
    CitationResolutionStatus,
    ResolvedAnswerDraft,
    ResolvedPlaceholder,
)

_CLAIM_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


class SelfRAGClaimStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNCERTAIN = "UNCERTAIN"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(slots=True, frozen=True)
class ExtractedClaim:
    section_title: str
    claim: str
    placeholder_tokens: tuple[str, ...]
    resolutions: tuple[ResolvedPlaceholder, ...]


@dataclass(slots=True, frozen=True)
class SelfRAGClaimResult:
    section_title: str
    claim: str
    citation: str | None
    status: SelfRAGClaimStatus
    reason: str
    source_passage: str | None
    appeal_warning: str | None
    source_doc_id: str | None
    source_chunk_id: str | None
    placeholder_tokens: tuple[str, ...]
    reretrieved: bool


@dataclass(slots=True, frozen=True)
class SelfRAGVerificationResult:
    claims: tuple[SelfRAGClaimResult, ...]

    @property
    def verified_count(self) -> int:
        return sum(1 for claim in self.claims if claim.status is SelfRAGClaimStatus.VERIFIED)

    @property
    def uncertain_count(self) -> int:
        return sum(1 for claim in self.claims if claim.status is SelfRAGClaimStatus.UNCERTAIN)

    @property
    def unsupported_count(self) -> int:
        return sum(1 for claim in self.claims if claim.status is SelfRAGClaimStatus.UNSUPPORTED)


ReretrieveCallback = Callable[[Session, str], ResolvedPlaceholder | None]


class SelfRAGVerifier:
    def __init__(
        self,
        *,
        appeal_validator: AppealValidator | None = None,
        misgrounding_checker: MisgroundingChecker | None = None,
    ) -> None:
        self.appeal_validator = appeal_validator or AppealValidator()
        self.misgrounding_checker = misgrounding_checker or MisgroundingChecker()

    def verify(
        self,
        session: Session,
        *,
        resolved_draft: ResolvedAnswerDraft,
        reretrieve: ReretrieveCallback | None = None,
    ) -> SelfRAGVerificationResult:
        extracted_claims = self.extract_claims(resolved_draft)
        results = [
            self._verify_claim(
                session,
                extracted_claim=claim,
                reretrieve=reretrieve,
            )
            for claim in extracted_claims
        ]
        return SelfRAGVerificationResult(claims=tuple(results))

    def extract_claims(
        self,
        resolved_draft: ResolvedAnswerDraft,
    ) -> list[ExtractedClaim]:
        claims: list[ExtractedClaim] = []
        for section in resolved_draft.draft.sections:
            for paragraph in section.paragraphs:
                linked_resolutions = [
                    resolution
                    for resolution in resolved_draft.resolutions
                    if resolution.placeholder in paragraph
                ]
                rendered_paragraph = paragraph
                for resolution in linked_resolutions:
                    rendered_paragraph = rendered_paragraph.replace(
                        resolution.placeholder,
                        "",
                    )
                rendered_paragraph = self._normalize_claim_text(rendered_paragraph)
                for claim in self._split_claims(rendered_paragraph):
                    claims.append(
                        ExtractedClaim(
                            section_title=section.title,
                            claim=claim,
                            placeholder_tokens=tuple(
                                resolution.placeholder for resolution in linked_resolutions
                            ),
                            resolutions=tuple(linked_resolutions),
                        )
                    )
        return claims

    def _verify_claim(
        self,
        session: Session,
        *,
        extracted_claim: ExtractedClaim,
        reretrieve: ReretrieveCallback | None,
    ) -> SelfRAGClaimResult:
        initial = self._assess_claim(session, extracted_claim.claim, extracted_claim.resolutions)
        if initial.status is not SelfRAGClaimStatus.UNSUPPORTED or reretrieve is None:
            return SelfRAGClaimResult(
                section_title=extracted_claim.section_title,
                claim=extracted_claim.claim,
                citation=initial.citation,
                status=initial.status,
                reason=initial.reason,
                source_passage=initial.source_passage,
                appeal_warning=initial.appeal_warning,
                source_doc_id=initial.source_doc_id,
                source_chunk_id=initial.source_chunk_id,
                placeholder_tokens=extracted_claim.placeholder_tokens,
                reretrieved=False,
            )

        replacement = reretrieve(session, extracted_claim.claim)
        if replacement is None:
            return SelfRAGClaimResult(
                section_title=extracted_claim.section_title,
                claim=extracted_claim.claim,
                citation=initial.citation,
                status=initial.status,
                reason=initial.reason,
                source_passage=initial.source_passage,
                appeal_warning=initial.appeal_warning,
                source_doc_id=initial.source_doc_id,
                source_chunk_id=initial.source_chunk_id,
                placeholder_tokens=extracted_claim.placeholder_tokens,
                reretrieved=False,
            )

        retry = self._assess_claim(session, extracted_claim.claim, (replacement,))
        return SelfRAGClaimResult(
            section_title=extracted_claim.section_title,
            claim=extracted_claim.claim,
            citation=retry.citation,
            status=retry.status,
            reason=retry.reason,
            source_passage=retry.source_passage,
            appeal_warning=retry.appeal_warning,
            source_doc_id=retry.source_doc_id,
            source_chunk_id=retry.source_chunk_id,
            placeholder_tokens=extracted_claim.placeholder_tokens,
            reretrieved=True,
        )

    def _assess_claim(
        self,
        session: Session,
        claim: str,
        resolutions: Sequence[ResolvedPlaceholder],
    ) -> _ClaimAssessment:
        if not resolutions:
            return _ClaimAssessment(
                status=SelfRAGClaimStatus.UNSUPPORTED,
                citation=None,
                reason="No citation was attached to the claim.",
                source_passage=None,
                appeal_warning=None,
                source_doc_id=None,
                source_chunk_id=None,
            )

        statuses: list[SelfRAGClaimStatus] = []
        reasons: list[str] = []
        citations: list[str] = []
        passages: list[str] = []
        warnings: list[str] = []
        source_doc_id: str | None = None
        source_chunk_id: str | None = None

        for resolution in resolutions:
            if resolution.status is not CitationResolutionStatus.VERIFIED:
                statuses.append(SelfRAGClaimStatus.UNSUPPORTED)
                reasons.append("Citation could not be verified against the corpus.")
                continue

            appeal_result = self.appeal_validator.validate(session, resolution=resolution)
            effective_resolution = appeal_result.effective_resolution
            if effective_resolution.rendered_value not in citations:
                citations.append(effective_resolution.rendered_value)
            if appeal_result.warning is not None and appeal_result.warning not in warnings:
                warnings.append(appeal_result.warning)

            misgrounding = self.misgrounding_checker.check_claim(
                session,
                claim=claim,
                resolution=effective_resolution,
            )
            if (
                misgrounding.source_passage is not None
                and misgrounding.source_passage not in passages
            ):
                passages.append(misgrounding.source_passage)
            if source_doc_id is None and misgrounding.doc_id is not None:
                source_doc_id = misgrounding.doc_id
            if source_chunk_id is None and misgrounding.chunk_id is not None:
                source_chunk_id = misgrounding.chunk_id

            statuses.append(self._status_for_validation(appeal_result, misgrounding))
            reasons.append(self._reason_for_validation(appeal_result, misgrounding))

        final_status = self._combine_statuses(statuses)
        return _ClaimAssessment(
            status=final_status,
            citation="; ".join(citations) or None,
            reason="; ".join(reasons) if reasons else "No verification result available.",
            source_passage="\n\n".join(passages) if passages else None,
            appeal_warning="; ".join(warnings) if warnings else None,
            source_doc_id=source_doc_id,
            source_chunk_id=source_chunk_id,
        )

    def _status_for_validation(
        self,
        appeal_result: AppealValidationResult,
        misgrounding: MisgroundingResult,
    ) -> SelfRAGClaimStatus:
        if misgrounding.status is MisgroundingStatus.MISGROUNDED:
            return SelfRAGClaimStatus.UNSUPPORTED
        if appeal_result.status in {
            AppealValidationStatus.PENDING,
            AppealValidationStatus.REMANDED,
        }:
            return SelfRAGClaimStatus.UNCERTAIN
        if misgrounding.status is MisgroundingStatus.UNCERTAIN:
            return SelfRAGClaimStatus.UNCERTAIN
        return SelfRAGClaimStatus.VERIFIED

    def _reason_for_validation(
        self,
        appeal_result: AppealValidationResult,
        misgrounding: MisgroundingResult,
    ) -> str:
        parts = [misgrounding.message]
        if appeal_result.warning is not None:
            parts.append(appeal_result.warning)
        return " ".join(parts)

    def _combine_statuses(
        self,
        statuses: Sequence[SelfRAGClaimStatus],
    ) -> SelfRAGClaimStatus:
        if not statuses:
            return SelfRAGClaimStatus.UNSUPPORTED
        if SelfRAGClaimStatus.UNSUPPORTED in statuses:
            return SelfRAGClaimStatus.UNSUPPORTED
        if SelfRAGClaimStatus.UNCERTAIN in statuses:
            return SelfRAGClaimStatus.UNCERTAIN
        return SelfRAGClaimStatus.VERIFIED

    def _split_claims(self, paragraph: str) -> list[str]:
        claims = [
            segment.strip()
            for segment in _CLAIM_SPLIT_PATTERN.split(paragraph.strip())
            if segment.strip()
        ]
        if claims:
            return claims
        normalized = paragraph.strip()
        return [normalized] if normalized else []

    def _normalize_claim_text(self, paragraph: str) -> str:
        cleaned = " ".join(paragraph.split())
        cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
        return cleaned.strip()


@dataclass(slots=True, frozen=True)
class _ClaimAssessment:
    status: SelfRAGClaimStatus
    citation: str | None
    reason: str
    source_passage: str | None
    appeal_warning: str | None
    source_doc_id: str | None
    source_chunk_id: str | None
