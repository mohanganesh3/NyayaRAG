from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.rag.resolution import CitationResolutionStatus, ResolvedAnswerDraft, ResolvedPlaceholder
from app.rag.self_rag import SelfRAGClaimResult, SelfRAGClaimStatus, SelfRAGVerificationResult


class CitationBadgeStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNCERTAIN = "UNCERTAIN"
    UNVERIFIED = "UNVERIFIED"


class StructuredAnswerSectionKind(StrEnum):
    LEGAL_POSITION = "LEGAL_POSITION"
    APPLICABLE_LAW = "APPLICABLE_LAW"
    KEY_CASES = "KEY_CASES"
    VERIFICATION_STATUS = "VERIFICATION_STATUS"


@dataclass(slots=True, frozen=True)
class InlineCitationBadge:
    placeholder_token: str
    label: str
    status: CitationBadgeStatus
    citation: str | None
    message: str
    doc_id: str | None
    chunk_id: str | None
    source_passage: str | None
    appeal_warning: str | None


@dataclass(slots=True, frozen=True)
class StructuredClaim:
    text: str
    status: CitationBadgeStatus
    reason: str
    citation: str | None
    source_passage: str | None
    appeal_warning: str | None
    reretrieved: bool
    citation_badges: tuple[InlineCitationBadge, ...]


@dataclass(slots=True, frozen=True)
class VerificationStatusItem:
    label: str
    value: str
    status: CitationBadgeStatus


@dataclass(slots=True, frozen=True)
class StructuredAnswerSection:
    kind: StructuredAnswerSectionKind
    title: str
    claims: tuple[StructuredClaim, ...] = ()
    status_items: tuple[VerificationStatusItem, ...] = ()


@dataclass(slots=True, frozen=True)
class StructuredAnswer:
    query: str
    overall_status: CitationBadgeStatus
    sections: tuple[StructuredAnswerSection, ...]

    def section(
        self,
        kind: StructuredAnswerSectionKind,
    ) -> StructuredAnswerSection:
        for section in self.sections:
            if section.kind is kind:
                return section
        raise KeyError(f"Section {kind} not found")


class StructuredAnswerBuilder:
    def build(
        self,
        *,
        resolved_draft: ResolvedAnswerDraft,
        verification_result: SelfRAGVerificationResult,
    ) -> StructuredAnswer:
        grouped_claims: dict[StructuredAnswerSectionKind, list[StructuredClaim]] = {
            StructuredAnswerSectionKind.LEGAL_POSITION: [],
            StructuredAnswerSectionKind.APPLICABLE_LAW: [],
            StructuredAnswerSectionKind.KEY_CASES: [],
        }

        for claim in verification_result.claims:
            section_kind = self._map_section_kind(claim.section_title)
            grouped_claims[section_kind].append(
                self._build_claim(
                    claim=claim,
                    resolved_draft=resolved_draft,
                )
            )

        verification_section = StructuredAnswerSection(
            kind=StructuredAnswerSectionKind.VERIFICATION_STATUS,
            title="Verification Status",
            status_items=self._build_verification_items(
                resolved_draft=resolved_draft,
                verification_result=verification_result,
            ),
        )

        sections = (
            StructuredAnswerSection(
                kind=StructuredAnswerSectionKind.LEGAL_POSITION,
                title="Legal Position",
                claims=tuple(grouped_claims[StructuredAnswerSectionKind.LEGAL_POSITION]),
            ),
            StructuredAnswerSection(
                kind=StructuredAnswerSectionKind.APPLICABLE_LAW,
                title="Applicable Law",
                claims=tuple(grouped_claims[StructuredAnswerSectionKind.APPLICABLE_LAW]),
            ),
            StructuredAnswerSection(
                kind=StructuredAnswerSectionKind.KEY_CASES,
                title="Key Cases",
                claims=tuple(grouped_claims[StructuredAnswerSectionKind.KEY_CASES]),
            ),
            verification_section,
        )

        return StructuredAnswer(
            query=resolved_draft.draft.query,
            overall_status=self._overall_status(verification_result),
            sections=sections,
        )

    def _build_claim(
        self,
        *,
        claim: SelfRAGClaimResult,
        resolved_draft: ResolvedAnswerDraft,
    ) -> StructuredClaim:
        badges = tuple(
            self._build_badge(
                claim=claim,
                resolution=resolved_draft.resolution_for(token),
                placeholder_token=token,
            )
            for token in claim.placeholder_tokens
        )

        if not badges and claim.citation is not None:
            badges = (
                InlineCitationBadge(
                    placeholder_token="",
                    label=claim.citation,
                    status=self._status_for_claim(claim.status),
                    citation=claim.citation,
                    message=claim.reason,
                    doc_id=claim.source_doc_id,
                    chunk_id=claim.source_chunk_id,
                    source_passage=claim.source_passage,
                    appeal_warning=claim.appeal_warning,
                ),
            )

        return StructuredClaim(
            text=claim.claim,
            status=self._status_for_claim(claim.status),
            reason=claim.reason,
            citation=claim.citation,
            source_passage=claim.source_passage,
            appeal_warning=claim.appeal_warning,
            reretrieved=claim.reretrieved,
            citation_badges=badges,
        )

    def _build_badge(
        self,
        *,
        claim: SelfRAGClaimResult,
        resolution: ResolvedPlaceholder | None,
        placeholder_token: str,
    ) -> InlineCitationBadge:
        status = self._status_for_resolution(claim=claim, resolution=resolution)
        label = self._badge_label(claim=claim, resolution=resolution)
        message_parts = [claim.reason]
        if resolution is not None and resolution.message not in message_parts:
            message_parts.append(resolution.message)

        return InlineCitationBadge(
            placeholder_token=placeholder_token,
            label=label,
            status=status,
            citation=claim.citation if status is not CitationBadgeStatus.UNVERIFIED else None,
            message=" ".join(part for part in message_parts if part),
            doc_id=claim.source_doc_id or (resolution.doc_id if resolution is not None else None),
            chunk_id=claim.source_chunk_id
            or (resolution.chunk_id if resolution is not None else None),
            source_passage=claim.source_passage,
            appeal_warning=claim.appeal_warning,
        )

    def _build_verification_items(
        self,
        *,
        resolved_draft: ResolvedAnswerDraft,
        verification_result: SelfRAGVerificationResult,
    ) -> tuple[VerificationStatusItem, ...]:
        verified_resolutions = sum(
            1
            for resolution in resolved_draft.resolutions
            if resolution.status is CitationResolutionStatus.VERIFIED
        )
        unverified_resolutions = len(resolved_draft.resolutions) - verified_resolutions

        return (
            VerificationStatusItem(
                label="Verified Claims",
                value=str(verification_result.verified_count),
                status=CitationBadgeStatus.VERIFIED,
            ),
            VerificationStatusItem(
                label="Claims Requiring Review",
                value=str(verification_result.uncertain_count),
                status=(
                    CitationBadgeStatus.UNCERTAIN
                    if verification_result.uncertain_count > 0
                    else CitationBadgeStatus.VERIFIED
                ),
            ),
            VerificationStatusItem(
                label="Unverified Claims",
                value=str(verification_result.unsupported_count),
                status=(
                    CitationBadgeStatus.UNVERIFIED
                    if verification_result.unsupported_count > 0
                    else CitationBadgeStatus.VERIFIED
                ),
            ),
            VerificationStatusItem(
                label="Resolved Citations",
                value=str(verified_resolutions),
                status=CitationBadgeStatus.VERIFIED,
            ),
            VerificationStatusItem(
                label="Unresolved Citations",
                value=str(unverified_resolutions),
                status=(
                    CitationBadgeStatus.UNVERIFIED
                    if unverified_resolutions > 0
                    else CitationBadgeStatus.VERIFIED
                ),
            ),
        )

    def _overall_status(
        self,
        verification_result: SelfRAGVerificationResult,
    ) -> CitationBadgeStatus:
        if verification_result.unsupported_count > 0:
            return CitationBadgeStatus.UNVERIFIED
        if verification_result.uncertain_count > 0:
            return CitationBadgeStatus.UNCERTAIN
        return CitationBadgeStatus.VERIFIED

    def _map_section_kind(self, title: str) -> StructuredAnswerSectionKind:
        normalized = title.strip().lower()
        if "law" in normalized or "statute" in normalized:
            return StructuredAnswerSectionKind.APPLICABLE_LAW
        if "authorit" in normalized or "case" in normalized:
            return StructuredAnswerSectionKind.KEY_CASES
        return StructuredAnswerSectionKind.LEGAL_POSITION

    def _status_for_claim(
        self,
        status: SelfRAGClaimStatus,
    ) -> CitationBadgeStatus:
        if status is SelfRAGClaimStatus.VERIFIED:
            return CitationBadgeStatus.VERIFIED
        if status is SelfRAGClaimStatus.UNCERTAIN:
            return CitationBadgeStatus.UNCERTAIN
        return CitationBadgeStatus.UNVERIFIED

    def _status_for_resolution(
        self,
        *,
        claim: SelfRAGClaimResult,
        resolution: ResolvedPlaceholder | None,
    ) -> CitationBadgeStatus:
        if resolution is None or resolution.status is CitationResolutionStatus.UNVERIFIED:
            return CitationBadgeStatus.UNVERIFIED
        return self._status_for_claim(claim.status)

    def _badge_label(
        self,
        *,
        claim: SelfRAGClaimResult,
        resolution: ResolvedPlaceholder | None,
    ) -> str:
        if resolution is None:
            return claim.citation or "[UNVERIFIED]"
        if resolution.status is CitationResolutionStatus.UNVERIFIED:
            return resolution.rendered_value
        if claim.citation is not None and len(claim.placeholder_tokens) == 1:
            return claim.citation
        return resolution.rendered_value
