from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_value
from enum import StrEnum
from statistics import fmean

from sqlalchemy.orm import Session

from app.services.criminal_code_mappings import CriminalCodeMappingResolver


class LegalCitationKind(StrEnum):
    JUDGMENT = "judgment"
    STATUTE = "statute"


class AuthorityLabel(StrEnum):
    BINDING = "binding"
    PERSUASIVE = "persuasive"


@dataclass(slots=True, frozen=True)
class CitationEvaluationRecord:
    record_id: str
    kind: LegalCitationKind
    exists: bool
    supports_claim: bool | None = None
    surfaced_doc_id: str | None = None
    final_authority_doc_id: str | None = None
    claimed_authority_label: AuthorityLabel | None = None
    expected_authority_label: AuthorityLabel | None = None
    statute_in_force: bool | None = None
    uses_current_text: bool | None = None


@dataclass(slots=True, frozen=True)
class MultiHopEvaluationCase:
    case_id: str
    expected_doc_ids: tuple[str, ...]
    surfaced_doc_ids: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class CriminalCodeAwarenessCase:
    case_id: str
    query_reference: str
    reference_date: date_value
    expected_preferred_reference: str


@dataclass(slots=True, frozen=True)
class MultiHopEvaluationResult:
    case: MultiHopEvaluationCase
    completeness: float


@dataclass(slots=True, frozen=True)
class CriminalCodeAwarenessResult:
    case: CriminalCodeAwarenessCase
    actual_preferred_reference: str
    correct: bool


@dataclass(slots=True, frozen=True)
class IndiaLegalMetrics:
    citation_existence_rate: float
    citation_accuracy_rate: float
    appeal_chain_accuracy: float
    jurisdiction_binding_accuracy: float
    temporal_validity_rate: float
    amendment_awareness_rate: float
    multi_hop_completeness: float
    bns_bnss_bsa_awareness: float


@dataclass(slots=True, frozen=True)
class IndiaLegalEvaluationRun:
    metrics: IndiaLegalMetrics
    multi_hop_results: tuple[MultiHopEvaluationResult, ...]
    criminal_code_results: tuple[CriminalCodeAwarenessResult, ...]


class IndiaLegalEvaluationSuite:
    def __init__(
        self,
        *,
        criminal_code_resolver: CriminalCodeMappingResolver | None = None,
    ) -> None:
        self.criminal_code_resolver = criminal_code_resolver or CriminalCodeMappingResolver()

    def run(
        self,
        *,
        session: Session | None = None,
        citation_records: tuple[CitationEvaluationRecord, ...]
        | list[CitationEvaluationRecord] = (),
        multi_hop_cases: tuple[MultiHopEvaluationCase, ...] | list[MultiHopEvaluationCase] = (),
        criminal_code_cases: tuple[CriminalCodeAwarenessCase, ...]
        | list[CriminalCodeAwarenessCase] = (),
    ) -> IndiaLegalEvaluationRun:
        multi_hop_results = tuple(
            MultiHopEvaluationResult(
                case=case,
                completeness=self._multi_hop_completeness(case),
            )
            for case in multi_hop_cases
        )
        criminal_code_results = self._evaluate_criminal_code_cases(
            session=session,
            cases=criminal_code_cases,
        )

        metrics = IndiaLegalMetrics(
            citation_existence_rate=self._citation_existence_rate(citation_records),
            citation_accuracy_rate=self._citation_accuracy_rate(citation_records),
            appeal_chain_accuracy=self._appeal_chain_accuracy(citation_records),
            jurisdiction_binding_accuracy=self._jurisdiction_binding_accuracy(citation_records),
            temporal_validity_rate=self._temporal_validity_rate(citation_records),
            amendment_awareness_rate=self._amendment_awareness_rate(citation_records),
            multi_hop_completeness=(
                fmean(result.completeness for result in multi_hop_results)
                if multi_hop_results
                else 0.0
            ),
            bns_bnss_bsa_awareness=(
                fmean(1.0 if result.correct else 0.0 for result in criminal_code_results)
                if criminal_code_results
                else 0.0
            ),
        )
        return IndiaLegalEvaluationRun(
            metrics=metrics,
            multi_hop_results=multi_hop_results,
            criminal_code_results=criminal_code_results,
        )

    def _citation_existence_rate(
        self,
        records: tuple[CitationEvaluationRecord, ...] | list[CitationEvaluationRecord],
    ) -> float:
        judgments = [record for record in records if record.kind is LegalCitationKind.JUDGMENT]
        if not judgments:
            return 0.0
        return sum(1 for record in judgments if record.exists) / len(judgments)

    def _citation_accuracy_rate(
        self,
        records: tuple[CitationEvaluationRecord, ...] | list[CitationEvaluationRecord],
    ) -> float:
        judgments = [
            record
            for record in records
            if record.kind is LegalCitationKind.JUDGMENT and record.supports_claim is not None
        ]
        if not judgments:
            return 0.0
        return sum(1 for record in judgments if record.supports_claim) / len(judgments)

    def _appeal_chain_accuracy(
        self,
        records: tuple[CitationEvaluationRecord, ...] | list[CitationEvaluationRecord],
    ) -> float:
        judgments = [
            record
            for record in records
            if record.kind is LegalCitationKind.JUDGMENT
            and (record.surfaced_doc_id is not None or record.final_authority_doc_id is not None)
        ]
        if not judgments:
            return 0.0
        return (
            sum(
                1
                for record in judgments
                if record.final_authority_doc_id is None
                or record.surfaced_doc_id == record.final_authority_doc_id
            )
            / len(judgments)
        )

    def _jurisdiction_binding_accuracy(
        self,
        records: tuple[CitationEvaluationRecord, ...] | list[CitationEvaluationRecord],
    ) -> float:
        labeled = [
            record
            for record in records
            if record.claimed_authority_label is not None
            and record.expected_authority_label is not None
        ]
        if not labeled:
            return 0.0
        return (
            sum(
                1
                for record in labeled
                if record.claimed_authority_label == record.expected_authority_label
            )
            / len(labeled)
        )

    def _temporal_validity_rate(
        self,
        records: tuple[CitationEvaluationRecord, ...] | list[CitationEvaluationRecord],
    ) -> float:
        statutes = [
            record
            for record in records
            if record.kind is LegalCitationKind.STATUTE and record.statute_in_force is not None
        ]
        if not statutes:
            return 0.0
        return sum(1 for record in statutes if record.statute_in_force) / len(statutes)

    def _amendment_awareness_rate(
        self,
        records: tuple[CitationEvaluationRecord, ...] | list[CitationEvaluationRecord],
    ) -> float:
        statutes = [
            record
            for record in records
            if record.kind is LegalCitationKind.STATUTE and record.uses_current_text is not None
        ]
        if not statutes:
            return 0.0
        return sum(1 for record in statutes if record.uses_current_text) / len(statutes)

    def _multi_hop_completeness(self, case: MultiHopEvaluationCase) -> float:
        expected = set(case.expected_doc_ids)
        if not expected:
            return 0.0
        surfaced = set(case.surfaced_doc_ids)
        return len(expected & surfaced) / len(expected)

    def _evaluate_criminal_code_cases(
        self,
        *,
        session: Session | None,
        cases: tuple[CriminalCodeAwarenessCase, ...] | list[CriminalCodeAwarenessCase],
    ) -> tuple[CriminalCodeAwarenessResult, ...]:
        if not cases:
            return tuple()
        if session is None:
            raise ValueError("A database session is required to evaluate criminal-code cases.")

        results: list[CriminalCodeAwarenessResult] = []
        for case in cases:
            resolution = self.criminal_code_resolver.resolve_reference(
                session,
                case.query_reference,
                reference_date=case.reference_date,
            )
            actual = self.criminal_code_resolver.format_reference(resolution.preferred_reference)
            results.append(
                CriminalCodeAwarenessResult(
                    case=case,
                    actual_preferred_reference=actual,
                    correct=actual == case.expected_preferred_reference,
                )
            )
        return tuple(results)
