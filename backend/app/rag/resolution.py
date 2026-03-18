from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentChunk, LegalDocument, LegalDocumentType, ValidityStatus
from app.rag.generator import (
    GeneratedAnswerDraft,
    GeneratedPlaceholder,
    PlaceholderKind,
)
from app.rag.lexical import LegalTokenizer

_GENERIC_CITE_STOPWORDS = {
    "authority",
    "binding",
    "court",
    "current",
    "development",
    "doctrinal",
    "fallback",
    "foundational",
    "high",
    "interpreting",
    "issue",
    "key",
    "on",
    "primary",
    "stage",
    "supreme",
    "the",
}


class CitationResolutionStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


@dataclass(slots=True, frozen=True)
class ResolvedPlaceholder:
    placeholder: str
    kind: PlaceholderKind
    status: CitationResolutionStatus
    rendered_value: str
    citation: str | None
    doc_id: str | None
    chunk_id: str | None
    confidence: float
    message: str


@dataclass(slots=True, frozen=True)
class ResolvedAnswerDraft:
    draft: GeneratedAnswerDraft
    rendered_text: str
    resolutions: tuple[ResolvedPlaceholder, ...]

    def resolution_for(self, placeholder: str) -> ResolvedPlaceholder | None:
        for resolution in self.resolutions:
            if resolution.placeholder == placeholder:
                return resolution
        return None


class CitationResolver:
    def __init__(
        self,
        *,
        tokenizer: LegalTokenizer | None = None,
        direct_match_threshold: float = 0.85,
        corpus_match_threshold: float = 0.80,
    ) -> None:
        self.tokenizer = tokenizer or LegalTokenizer()
        self.direct_match_threshold = direct_match_threshold
        self.corpus_match_threshold = corpus_match_threshold

    def resolve(
        self,
        session: Session,
        draft: GeneratedAnswerDraft,
    ) -> ResolvedAnswerDraft:
        rendered_text = draft.rendered_text()
        resolutions: list[ResolvedPlaceholder] = []

        for placeholder in draft.placeholders:
            resolution = self._resolve_placeholder(session, placeholder)
            resolutions.append(resolution)
            rendered_text = rendered_text.replace(placeholder.token, resolution.rendered_value)

        return ResolvedAnswerDraft(
            draft=draft,
            rendered_text=rendered_text,
            resolutions=tuple(resolutions),
        )

    def _resolve_placeholder(
        self,
        session: Session,
        placeholder: GeneratedPlaceholder,
    ) -> ResolvedPlaceholder:
        if placeholder.kind is PlaceholderKind.UNSUPPORTED:
            return self._unverified_resolution(
                placeholder,
                message=(
                    "Legal proposition remains unsupported and requires "
                    "primary-source verification."
                ),
            )

        direct_candidate = self._resolve_direct_candidate(session, placeholder)
        if direct_candidate is not None:
            document, chunk = direct_candidate
            return self._verified_resolution(
                placeholder,
                document=document,
                chunk=chunk,
                confidence=1.0,
                message="Resolved directly from retrieved corpus context.",
            )

        corpus_candidate = self._search_corpus(session, placeholder)
        if corpus_candidate is not None:
            score, document, chunk = corpus_candidate
            threshold = (
                self.direct_match_threshold
                if placeholder.kind is PlaceholderKind.STATUTE
                else self.corpus_match_threshold
            )
            if score >= threshold:
                return self._verified_resolution(
                    placeholder,
                    document=document,
                    chunk=chunk,
                    confidence=score,
                    message="Resolved from canonical corpus search.",
                )

        return self._unverified_resolution(
            placeholder,
            message="Specific primary authority could not be located in the corpus.",
        )

    def _resolve_direct_candidate(
        self,
        session: Session,
        placeholder: GeneratedPlaceholder,
    ) -> tuple[LegalDocument, DocumentChunk | None] | None:
        document = session.get(LegalDocument, placeholder.doc_id) if placeholder.doc_id else None
        if document is None or document.current_validity is not ValidityStatus.GOOD_LAW:
            return None

        chunk = session.get(DocumentChunk, placeholder.chunk_id) if placeholder.chunk_id else None
        if chunk is not None and chunk.current_validity is not ValidityStatus.GOOD_LAW:
            return None

        if (
            placeholder.kind is PlaceholderKind.STATUTE
            and chunk is not None
            and chunk.is_in_force is False
        ):
            return None

        return (document, chunk)

    def _search_corpus(
        self,
        session: Session,
        placeholder: GeneratedPlaceholder,
    ) -> tuple[float, LegalDocument, DocumentChunk | None] | None:
        if placeholder.kind is PlaceholderKind.STATUTE:
            return self._search_statute(session, placeholder)
        if placeholder.kind is PlaceholderKind.CITE:
            return self._search_judgment(session, placeholder)
        return None

    def _search_statute(
        self,
        session: Session,
        placeholder: GeneratedPlaceholder,
    ) -> tuple[float, LegalDocument, DocumentChunk | None] | None:
        candidates = session.execute(
            select(DocumentChunk, LegalDocument)
            .join(LegalDocument, DocumentChunk.doc_id == LegalDocument.doc_id)
            .where(
                DocumentChunk.doc_type.in_(
                    [LegalDocumentType.STATUTE, LegalDocumentType.CONSTITUTION]
                ),
                LegalDocument.current_validity == ValidityStatus.GOOD_LAW,
            )
        ).all()
        if not candidates:
            return None

        query_tokens = self._statute_tokens(placeholder.description)
        best: tuple[float, LegalDocument, DocumentChunk | None] | None = None
        for chunk, document in candidates:
            if chunk.is_in_force is False:
                continue
            score = self._statute_match_score(
                query_tokens,
                placeholder.description,
                document,
                chunk,
            )
            if best is None or score > best[0]:
                best = (score, document, chunk)
        return best

    def _search_judgment(
        self,
        session: Session,
        placeholder: GeneratedPlaceholder,
    ) -> tuple[float, LegalDocument, DocumentChunk | None] | None:
        candidates = session.execute(
            select(DocumentChunk, LegalDocument)
            .join(LegalDocument, DocumentChunk.doc_id == LegalDocument.doc_id)
            .where(
                DocumentChunk.doc_type == LegalDocumentType.JUDGMENT,
                LegalDocument.current_validity == ValidityStatus.GOOD_LAW,
            )
        ).all()
        if not candidates:
            return None

        query_tokens = self._cite_tokens(placeholder.description)
        best: tuple[float, LegalDocument, DocumentChunk | None] | None = None
        for chunk, document in candidates:
            score = self._cite_match_score(query_tokens, placeholder.description, document, chunk)
            if best is None or score > best[0]:
                best = (score, document, chunk)
        return best

    def _statute_match_score(
        self,
        query_tokens: set[str],
        description: str,
        document: LegalDocument,
        chunk: DocumentChunk,
    ) -> float:
        candidate_tokens = self._tokens_for_text(
            " ".join(
                part
                for part in [
                    chunk.act_name or "",
                    chunk.section_number or "",
                    chunk.section_header or "",
                    chunk.text[:300],
                ]
                if part
            )
        )
        overlap = self._overlap(query_tokens, candidate_tokens)

        score = overlap
        description_lower = description.lower()
        act_name = (chunk.act_name or "").lower()
        if act_name and act_name in description_lower:
            score += 0.35
        section_number = (chunk.section_number or "").lower()
        if section_number and f"section {section_number}" in description_lower:
            score += 0.45
        if (
            document.doc_type is LegalDocumentType.CONSTITUTION
            and "constitution" in description_lower
        ):
            score += 0.15
        return min(score, 1.0)

    def _cite_match_score(
        self,
        query_tokens: set[str],
        description: str,
        document: LegalDocument,
        chunk: DocumentChunk,
    ) -> float:
        candidate_tokens = self._tokens_for_text(
            " ".join(
                part
                for part in [
                    document.court or "",
                    chunk.section_header or "",
                    " ".join(document.practice_areas),
                    chunk.text[:220],
                ]
                if part
            )
        )
        overlap = self._overlap(query_tokens, candidate_tokens)

        score = overlap
        description_lower = description.lower()
        court = (document.court or "").lower()
        if "supreme court" in description_lower and "supreme court" in court:
            score += 0.25
        if "high court" in description_lower and "high court" in court:
            score += 0.25
        for practice_area in document.practice_areas:
            if practice_area.lower() in description_lower:
                score += 0.15
                break
        header_tokens = self._tokens_for_text(chunk.section_header or "")
        if self._overlap(query_tokens, header_tokens) > 0.5:
            score += 0.10
        return min(score, 1.0)

    def _statute_tokens(self, text: str) -> set[str]:
        return self._tokens_for_text(text)

    def _cite_tokens(self, text: str) -> set[str]:
        tokens = self._tokens_for_text(text)
        return {
            token
            for token in tokens
            if token not in _GENERIC_CITE_STOPWORDS or token.isdigit()
        }

    def _tokens_for_text(self, text: str) -> set[str]:
        return set(self.tokenizer.tokenize(text.lower()))

    def _overlap(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left)

    def _verified_resolution(
        self,
        placeholder: GeneratedPlaceholder,
        *,
        document: LegalDocument,
        chunk: DocumentChunk | None,
        confidence: float,
        message: str,
    ) -> ResolvedPlaceholder:
        return self.build_verified_resolution(
            placeholder=placeholder.token,
            kind=placeholder.kind,
            document=document,
            chunk=chunk,
            confidence=confidence,
            message=message,
        )

    def build_verified_resolution(
        self,
        *,
        placeholder: str,
        kind: PlaceholderKind,
        document: LegalDocument,
        chunk: DocumentChunk | None,
        confidence: float,
        message: str,
    ) -> ResolvedPlaceholder:
        rendered_value = self._render_verified_value(kind, document, chunk)
        citation = self._canonical_citation(kind, document, chunk)
        return ResolvedPlaceholder(
            placeholder=placeholder,
            kind=kind,
            status=CitationResolutionStatus.VERIFIED,
            rendered_value=rendered_value,
            citation=citation,
            doc_id=document.doc_id,
            chunk_id=chunk.chunk_id if chunk is not None else None,
            confidence=confidence,
            message=message,
        )

    def _unverified_resolution(
        self,
        placeholder: GeneratedPlaceholder,
        *,
        message: str,
    ) -> ResolvedPlaceholder:
        rendered_value = f"[UNVERIFIED: {placeholder.description}]"
        return ResolvedPlaceholder(
            placeholder=placeholder.token,
            kind=placeholder.kind,
            status=CitationResolutionStatus.UNVERIFIED,
            rendered_value=rendered_value,
            citation=None,
            doc_id=None,
            chunk_id=None,
            confidence=0.0,
            message=message,
        )

    def _render_verified_value(
        self,
        kind: PlaceholderKind,
        document: LegalDocument,
        chunk: DocumentChunk | None,
    ) -> str:
        if kind is PlaceholderKind.STATUTE:
            act_name = (
                (chunk.act_name if chunk is not None else None)
                or document.court
                or "Unknown Act"
            )
            section_number = chunk.section_number if chunk is not None else None
            if section_number is not None:
                return f"{act_name}, Section {section_number}"
            header = chunk.section_header if chunk is not None else None
            return header or act_name

        case_name = self._case_name(document)
        citation = document.citation or (chunk.citation if chunk is not None else None)
        if case_name and citation:
            return f"{case_name}, {citation}"
        if citation:
            return citation
        if case_name:
            return case_name
        return document.court or "Verified authority"

    def _canonical_citation(
        self,
        kind: PlaceholderKind,
        document: LegalDocument,
        chunk: DocumentChunk | None,
    ) -> str | None:
        if kind is PlaceholderKind.STATUTE:
            act_name = (chunk.act_name if chunk is not None else None) or document.court
            section_number = chunk.section_number if chunk is not None else None
            if act_name and section_number:
                return f"{act_name}, Section {section_number}"
            return act_name or chunk.section_header if chunk is not None else None
        return document.citation or (chunk.citation if chunk is not None else None)

    def _case_name(self, document: LegalDocument) -> str | None:
        appellant = document.parties.get("appellant") or document.parties.get("petitioner")
        respondent = document.parties.get("respondent") or document.parties.get("opposite_party")
        if appellant and respondent:
            return f"{appellant} v {respondent}"
        return None
