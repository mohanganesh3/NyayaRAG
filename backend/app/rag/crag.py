from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date as date_value
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy.orm import Session

from app.models import (
    DocumentChunk,
    LegalDocument,
    LegalDocumentType,
    StatuteSection,
    ValidityStatus,
)
from app.rag.lexical import LegalTokenizer
from app.rag.router import QueryRouter
from app.schemas import QueryAnalysis, QueryEntityType, QueryType


class CRAGAction(StrEnum):
    PROCEED = "PROCEED"
    REFINED = "REFINED"
    INSUFFICIENT = "INSUFFICIENT"
    WEB_SUPPLEMENTED = "WEB_SUPPLEMENTED"


class TemporalSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    IMPORTANT = "IMPORTANT"
    WARNING = "WARNING"


class RetrievalResultLike(Protocol):
    doc_id: str
    chunk_id: str
    chunk: DocumentChunk
    document: LegalDocument


class RetrievalPipelineLike(Protocol):
    def retrieve(
        self,
        session: Session,
        query: str,
        *,
        analysis: QueryAnalysis | None = None,
    ) -> Sequence[RetrievalResultLike]: ...


@dataclass(slots=True)
class WebSupplement:
    title: str
    url: str
    snippet: str


@dataclass(slots=True)
class TemporalValidationResult:
    doc_id: str
    chunk_id: str
    valid: bool
    severity: TemporalSeverity | None = None
    reason: str | None = None
    warning: str | None = None
    replacement_doc_id: str | None = None
    current_text: str | None = None
    corresponding_new_section: str | None = None


@dataclass(slots=True)
class CRAGResult:
    action: CRAGAction
    score: float
    average_relevance: float
    entity_coverage: float
    results: list[RetrievalResultLike]
    temporal_findings: list[TemporalValidationResult] = field(default_factory=list)
    invalid_chunk_ids: list[str] = field(default_factory=list)
    refined_queries: list[str] = field(default_factory=list)
    refinement_note: str | None = None
    warning: str | None = None
    web_supplements: list[WebSupplement] = field(default_factory=list)


class WebSupplementProvider(ABC):
    @abstractmethod
    def supplement(
        self,
        query: str,
        analysis: QueryAnalysis,
    ) -> list[WebSupplement]: ...


class NullWebSupplementProvider(WebSupplementProvider):
    def supplement(
        self,
        query: str,
        analysis: QueryAnalysis,
    ) -> list[WebSupplement]:
        return []


RefineCallable = Callable[[str, QueryAnalysis], Sequence[RetrievalResultLike]]


class CRAGValidator:
    def __init__(
        self,
        *,
        router: QueryRouter | None = None,
        web_provider: WebSupplementProvider | None = None,
        tokenizer: LegalTokenizer | None = None,
    ) -> None:
        self.router = router or QueryRouter()
        self.web_provider = web_provider or NullWebSupplementProvider()
        self.tokenizer = tokenizer or LegalTokenizer()

    def validate(
        self,
        session: Session,
        query: str,
        results: Sequence[RetrievalResultLike],
        *,
        analysis: QueryAnalysis | None = None,
        refine_with: RefineCallable | None = None,
        allow_refine: bool = True,
    ) -> CRAGResult:
        active_analysis = analysis or self.router.analyze(query, session=session)
        filtered_results, temporal_findings, invalid_chunk_ids = self._apply_temporal_validation(
            session,
            results,
            active_analysis,
        )
        average_relevance = self._average_relevance(query, filtered_results, active_analysis)
        entity_coverage = self._entity_coverage(filtered_results, active_analysis)
        retrieval_coverage = self._retrieval_coverage(
            query,
            filtered_results,
            active_analysis,
        )
        score = (
            0.4 * average_relevance
            + 0.25 * entity_coverage
            + 0.35 * retrieval_coverage
        )

        if score > 0.70 and filtered_results:
            return CRAGResult(
                action=CRAGAction.PROCEED,
                score=score,
                average_relevance=average_relevance,
                entity_coverage=entity_coverage,
                results=filtered_results,
                temporal_findings=temporal_findings,
                invalid_chunk_ids=invalid_chunk_ids,
                warning=self._warning_from_temporal_findings(temporal_findings),
            )

        if score > 0.40:
            refined_queries = self._decompose_query(query, active_analysis)
            if allow_refine and refine_with is not None and refined_queries:
                refined_results = self._run_refinement(
                    active_analysis,
                    refined_queries,
                    refine_with=refine_with,
                    session=session,
                )
                refined_filtered, refined_temporal, refined_invalid = (
                    self._apply_temporal_validation(
                        session,
                        refined_results,
                        active_analysis,
                    )
                )
                refined_average = self._average_relevance(
                    query,
                    refined_filtered,
                    active_analysis,
                )
                refined_coverage = self._entity_coverage(
                    refined_filtered,
                    active_analysis,
                )
                refined_retrieval_coverage = self._retrieval_coverage(
                    query,
                    refined_filtered,
                    active_analysis,
                )
                refined_score = (
                    0.4 * refined_average
                    + 0.25 * refined_coverage
                    + 0.35 * refined_retrieval_coverage
                )
                return CRAGResult(
                    action=CRAGAction.REFINED,
                    score=refined_score,
                    average_relevance=refined_average,
                    entity_coverage=refined_coverage,
                    results=refined_filtered,
                    temporal_findings=refined_temporal,
                    invalid_chunk_ids=refined_invalid,
                    refined_queries=refined_queries,
                    refinement_note="Query decomposed for better retrieval coverage.",
                    warning=self._warning_from_temporal_findings(refined_temporal),
                )

            return CRAGResult(
                action=CRAGAction.REFINED,
                score=score,
                average_relevance=average_relevance,
                entity_coverage=entity_coverage,
                results=filtered_results,
                temporal_findings=temporal_findings,
                invalid_chunk_ids=invalid_chunk_ids,
                refined_queries=refined_queries,
                refinement_note="Retrieval quality is partial; refinement is recommended.",
                warning=self._warning_from_temporal_findings(temporal_findings),
            )

        supplements = self.web_provider.supplement(query, active_analysis)
        if supplements:
            return CRAGResult(
                action=CRAGAction.WEB_SUPPLEMENTED,
                score=score,
                average_relevance=average_relevance,
                entity_coverage=entity_coverage,
                results=filtered_results,
                temporal_findings=temporal_findings,
                invalid_chunk_ids=invalid_chunk_ids,
                warning="Limited corpus coverage; supplemental web sources attached.",
                web_supplements=supplements,
            )

        return CRAGResult(
            action=CRAGAction.INSUFFICIENT,
            score=score,
            average_relevance=average_relevance,
            entity_coverage=entity_coverage,
            results=filtered_results,
            temporal_findings=temporal_findings,
            invalid_chunk_ids=invalid_chunk_ids,
            warning=(
                "Insufficient information in corpus for this query. "
                "Please verify with primary sources."
            ),
        )

    def _average_relevance(
        self,
        query: str,
        results: Sequence[RetrievalResultLike],
        analysis: QueryAnalysis,
    ) -> float:
        if not results:
            return 0.0
        return sum(
            self._relevance_score(query, result, analysis) for result in results
        ) / len(results)

    def _relevance_score(
        self,
        query: str,
        result: RetrievalResultLike,
        analysis: QueryAnalysis,
    ) -> float:
        query_tokens = set(self.tokenizer.tokenize(query))
        result_text = self._result_text(result)
        result_tokens = set(self.tokenizer.tokenize(result_text))
        overlap = len(query_tokens & result_tokens) / max(len(query_tokens), 1)

        section_bonus = self._section_bonus(result, analysis)
        case_bonus = self._case_bonus(result, analysis)
        document_type_bonus = self._document_type_bonus(result, analysis)
        interpretation_bonus = self._interpretation_bonus(query, result, analysis)
        practice_bonus = self._practice_bonus(result, analysis)
        jurisdiction_bonus = self._jurisdiction_bonus(result, analysis)
        authority_bonus = self._authority_bonus(result)

        return min(
            0.35 * overlap
            + section_bonus
            + case_bonus
            + document_type_bonus
            + interpretation_bonus
            + practice_bonus
            + jurisdiction_bonus
            + authority_bonus,
            1.0,
        )

    def _entity_coverage(
        self,
        results: Sequence[RetrievalResultLike],
        analysis: QueryAnalysis,
    ) -> float:
        if not analysis.entities:
            return 1.0
        combined = " ".join(self._result_text(result).lower() for result in results)
        matched = 0
        for entity in analysis.entities:
            if entity.text.lower() in combined:
                matched += 1
                continue
            if entity.entity_type is QueryEntityType.SECTION:
                section_value = entity.text.split(" ")[-1].lower()
                if section_value in combined:
                    matched += 1
            elif entity.entity_type is QueryEntityType.ARTICLE:
                article_value = entity.text.replace("Article ", "").lower()
                if article_value in combined:
                    matched += 1
        return matched / len(analysis.entities)

    def _retrieval_coverage(
        self,
        query: str,
        results: Sequence[RetrievalResultLike],
        analysis: QueryAnalysis,
    ) -> float:
        if not results:
            return 0.0

        if analysis.query_type is QueryType.STATUTORY_LOOKUP:
            wants_interpretation = any(
                signal in query.lower()
                for signal in ("interpret", "interpreted", "held", "courts", "case law")
            )
            has_statute = any(
                result.document.doc_type
                in {LegalDocumentType.STATUTE, LegalDocumentType.CONSTITUTION}
                for result in results
            )
            has_judgment = any(
                result.document.doc_type is LegalDocumentType.JUDGMENT
                for result in results
            )
            score = 0.5 if has_statute else 0.0
            if wants_interpretation:
                score += 0.5 if has_judgment else 0.0
            else:
                score += 0.5
            return score

        if analysis.query_type is QueryType.CASE_SPECIFIC:
            return 1.0 if any(
                result.document.doc_type is LegalDocumentType.JUDGMENT
                for result in results
            ) else 0.0

        if analysis.query_type is QueryType.VAGUE_NATURAL:
            return 1.0

        return 0.5 if analysis.entities else 0.0

    def _apply_temporal_validation(
        self,
        session: Session,
        results: Sequence[RetrievalResultLike],
        analysis: QueryAnalysis,
    ) -> tuple[list[RetrievalResultLike], list[TemporalValidationResult], list[str]]:
        filtered_results: list[RetrievalResultLike] = []
        findings: list[TemporalValidationResult] = []
        invalid_chunk_ids: list[str] = []

        for result in results:
            finding = self.validate_temporal_validity(session, result, analysis)
            findings.append(finding)
            if not finding.valid and finding.severity in {
                TemporalSeverity.CRITICAL,
                TemporalSeverity.IMPORTANT,
            }:
                invalid_chunk_ids.append(result.chunk_id)
                continue
            filtered_results.append(result)

        return filtered_results, findings, invalid_chunk_ids

    def validate_temporal_validity(
        self,
        session: Session,
        result: RetrievalResultLike,
        analysis: QueryAnalysis,
    ) -> TemporalValidationResult:
        document = session.get(LegalDocument, result.doc_id) or result.document
        chunk = result.chunk

        if document.doc_type in {LegalDocumentType.STATUTE, LegalDocumentType.CONSTITUTION}:
            statute_document = getattr(document, "statute_document", None)
            if statute_document is not None and not statute_document.current_validity:
                return TemporalValidationResult(
                    doc_id=result.doc_id,
                    chunk_id=result.chunk_id,
                    valid=False,
                    severity=TemporalSeverity.CRITICAL,
                    reason=f"Act repealed. Replaced by: {statute_document.replaced_by}",
                    replacement_doc_id=statute_document.replaced_by,
                )

            section_number = chunk.section_number
            if statute_document is not None and section_number is not None:
                section = self._find_section(
                    statute_document.sections,
                    section_number,
                )
                if section is not None:
                    amendment_finding = self._amendment_finding(section, result, analysis)
                    if amendment_finding is not None:
                        return amendment_finding

                    legacy_warning = self._legacy_code_warning(section, chunk, analysis, result)
                    if legacy_warning is not None:
                        return legacy_warning

            return TemporalValidationResult(
                doc_id=result.doc_id,
                chunk_id=result.chunk_id,
                valid=True,
            )

        if document.current_validity in {
            ValidityStatus.OVERRULED,
            ValidityStatus.REVERSED_ON_APPEAL,
        }:
            return TemporalValidationResult(
                doc_id=result.doc_id,
                chunk_id=result.chunk_id,
                valid=False,
                severity=TemporalSeverity.CRITICAL,
                reason=f"Judgment validity is {document.current_validity.value}.",
                replacement_doc_id=document.overruled_by,
            )

        return TemporalValidationResult(
            doc_id=result.doc_id,
            chunk_id=result.chunk_id,
            valid=True,
        )

    def _find_section(
        self,
        sections: Sequence[StatuteSection],
        section_number: str,
    ) -> StatuteSection | None:
        for section in sections:
            if section.section_number == section_number:
                return section
        return None

    def _amendment_finding(
        self,
        section: StatuteSection,
        result: RetrievalResultLike,
        analysis: QueryAnalysis,
    ) -> TemporalValidationResult | None:
        if not section.amendments:
            return None

        latest = max(
            section.amendments,
            key=lambda amendment: (
                amendment.effective_date or amendment.amendment_date or date_value.min
            ),
        )
        latest_effective = latest.effective_date or latest.amendment_date
        if latest_effective is None:
            return None

        embedded_at = getattr(result.chunk, "embedded_at", None)
        amendment_date = getattr(result.chunk, "amendment_date", None)
        chunk_reference_date = self._chunk_reference_date(embedded_at, amendment_date)

        if chunk_reference_date is not None and latest_effective > chunk_reference_date:
            return TemporalValidationResult(
                doc_id=result.doc_id,
                chunk_id=result.chunk_id,
                valid=False,
                severity=TemporalSeverity.IMPORTANT,
                reason=f"Section amended on {latest_effective.isoformat()}",
                current_text=section.text,
            )
        return None

    def _legacy_code_warning(
        self,
        section: StatuteSection,
        chunk: object,
        analysis: QueryAnalysis,
        result: RetrievalResultLike,
    ) -> TemporalValidationResult | None:
        act_name = (getattr(chunk, "act_name", None) or "").lower()
        if (
            analysis.reference_date >= date_value(2024, 7, 1)
            and act_name in {"ipc", "crpc", "indian evidence act"}
            and section.corresponding_new_section
        ):
            return TemporalValidationResult(
                doc_id=result.doc_id,
                chunk_id=result.chunk_id,
                valid=True,
                severity=TemporalSeverity.WARNING,
                warning=(
                    f"New equivalent: {section.corresponding_new_section}. "
                    "Use the new criminal code provision for post-July-2024 offences."
                ),
                corresponding_new_section=section.corresponding_new_section,
            )
        return None

    def _chunk_reference_date(
        self,
        embedded_at: datetime | None,
        amendment_date: date_value | None,
    ) -> date_value | None:
        if embedded_at is not None:
            return embedded_at.date()
        return amendment_date

    def _decompose_query(
        self,
        query: str,
        analysis: QueryAnalysis,
    ) -> list[str]:
        queries: list[str] = []
        seen: set[str] = set()

        if analysis.query_type is QueryType.STATUTORY_LOOKUP:
            primary_reference = (
                analysis.bnss_equivalents[0]
                if analysis.bnss_equivalents
                else analysis.sections_mentioned[0]
                if analysis.sections_mentioned
                else None
            )
            if primary_reference is not None:
                self._append_query(queries, seen, f"What does {primary_reference} say?")
                self._append_query(
                    queries,
                    seen,
                    f"How have courts interpreted {primary_reference}?",
                )

        if analysis.query_type is QueryType.CASE_SPECIFIC:
            case_names = [
                entity.text
                for entity in analysis.entities
                if entity.entity_type is QueryEntityType.CASE_NAME
            ]
            for case_name in case_names:
                self._append_query(queries, seen, f"What was held in {case_name}?")

        if not queries and " and " in query.lower():
            for part in query.split(" and "):
                cleaned = part.strip().rstrip("?")
                if cleaned:
                    self._append_query(queries, seen, cleaned)

        return queries

    def _append_query(
        self,
        queries: list[str],
        seen: set[str],
        query: str,
    ) -> None:
        normalized = " ".join(query.split())
        if normalized in seen:
            return
        seen.add(normalized)
        queries.append(normalized)

    def _run_refinement(
        self,
        analysis: QueryAnalysis,
        refined_queries: Sequence[str],
        *,
        refine_with: RefineCallable,
        session: Session,
    ) -> list[RetrievalResultLike]:
        refined_results: dict[str, RetrievalResultLike] = {}
        for refined_query in refined_queries:
            refined_analysis = self.router.analyze(
                refined_query,
                session=session,
                reference_date=analysis.reference_date,
            )
            for result in refine_with(refined_query, refined_analysis):
                refined_results[result.chunk_id] = result
        return list(refined_results.values())

    def _section_bonus(
        self,
        result: RetrievalResultLike,
        analysis: QueryAnalysis,
    ) -> float:
        section_number = getattr(result.chunk, "section_number", None)
        if section_number is None:
            return 0.0
        targets = {
            reference.split(" ")[-1].upper()
            for reference in [*analysis.sections_mentioned, *analysis.bnss_equivalents]
            if " " in reference
        }
        if section_number.upper() in targets:
            return 0.25
        return 0.0

    def _case_bonus(
        self,
        result: RetrievalResultLike,
        analysis: QueryAnalysis,
    ) -> float:
        case_entities = [
            entity.text.lower()
            for entity in analysis.entities
            if entity.entity_type is QueryEntityType.CASE_NAME
        ]
        if not case_entities:
            return 0.0
        title = self._result_text(result).lower()
        if any(case_name in title for case_name in case_entities):
            return 0.25
        return 0.0

    def _document_type_bonus(
        self,
        result: RetrievalResultLike,
        analysis: QueryAnalysis,
    ) -> float:
        if (
            analysis.query_type is QueryType.STATUTORY_LOOKUP
            and result.document.doc_type
            in {LegalDocumentType.STATUTE, LegalDocumentType.CONSTITUTION}
        ):
            return 0.20
        if (
            analysis.query_type is QueryType.CASE_SPECIFIC
            and result.document.doc_type is LegalDocumentType.JUDGMENT
        ):
            return 0.15
        return 0.0

    def _interpretation_bonus(
        self,
        query: str,
        result: RetrievalResultLike,
        analysis: QueryAnalysis,
    ) -> float:
        if result.document.doc_type is not LegalDocumentType.JUDGMENT:
            return 0.0
        if analysis.query_type is QueryType.CASE_SPECIFIC:
            return 0.10
        if any(
            signal in query.lower()
            for signal in ("interpret", "interpreted", "held", "courts", "case law")
        ):
            return 0.18
        return 0.0

    def _practice_bonus(
        self,
        result: RetrievalResultLike,
        analysis: QueryAnalysis,
    ) -> float:
        practice_areas = set(getattr(result.chunk, "practice_area", [])) | set(
            getattr(result.document, "practice_areas", [])
        )
        if analysis.practice_area.value in practice_areas:
            return 0.05
        return 0.0

    def _jurisdiction_bonus(
        self,
        result: RetrievalResultLike,
        analysis: QueryAnalysis,
    ) -> float:
        court = getattr(result.document, "court", None)
        if court and court == analysis.jurisdiction_court:
            return 0.05
        return 0.0

    def _authority_bonus(self, result: RetrievalResultLike) -> float:
        authority_class = getattr(result, "authority_class", "")
        if authority_class == "binding":
            return 0.05
        return 0.0

    def _result_text(self, result: RetrievalResultLike) -> str:
        chunk = result.chunk
        document = result.document
        parts = [
            getattr(chunk, "text", ""),
            getattr(chunk, "section_header", "") or "",
            getattr(chunk, "act_name", "") or "",
            getattr(chunk, "section_number", "") or "",
            getattr(document, "citation", "") or "",
            getattr(document, "court", "") or "",
        ]
        parties = getattr(document, "parties", {})
        if isinstance(parties, dict):
            parts.extend(str(value) for value in parties.values())
        return " ".join(part for part in parts if part)

    def _warning_from_temporal_findings(
        self,
        findings: Sequence[TemporalValidationResult],
    ) -> str | None:
        warnings = [finding.warning for finding in findings if finding.warning]
        if warnings:
            return warnings[0]
        return None


class CorrectiveRAGPipeline:
    def __init__(
        self,
        *,
        primary_pipeline: RetrievalPipelineLike,
        validator: CRAGValidator | None = None,
        router: QueryRouter | None = None,
    ) -> None:
        self.primary_pipeline = primary_pipeline
        self.validator = validator or CRAGValidator(router=router)
        self.router = router or QueryRouter()

    def retrieve(
        self,
        session: Session,
        query: str,
        *,
        analysis: QueryAnalysis | None = None,
    ) -> CRAGResult:
        active_analysis = analysis or self.router.analyze(query, session=session)
        results = self.primary_pipeline.retrieve(
            session,
            query,
            analysis=active_analysis,
        )
        return self.validator.validate(
            session,
            query,
            results,
            analysis=active_analysis,
            refine_with=lambda refined_query, refined_analysis: self.primary_pipeline.retrieve(
                session,
                refined_query,
                analysis=refined_analysis,
            ),
        )
