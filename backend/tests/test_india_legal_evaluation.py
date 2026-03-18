from __future__ import annotations

from datetime import date as date_value

import pytest
from app.db.base import Base
from app.db.session import build_engine
from app.evaluation import (
    AuthorityLabel,
    CitationEvaluationRecord,
    CriminalCodeAwarenessCase,
    IndiaLegalEvaluationSuite,
    LegalCitationKind,
    MultiHopEvaluationCase,
)
from app.models import CriminalCode, CriminalCodeMappingStatus
from app.services.criminal_code_mappings import CriminalCodeMappingResolver
from sqlalchemy.orm import Session


def test_india_legal_evaluation_suite_computes_all_core_metrics() -> None:
    suite = IndiaLegalEvaluationSuite()
    run = suite.run(
        citation_records=[
            CitationEvaluationRecord(
                record_id="j-1",
                kind=LegalCitationKind.JUDGMENT,
                exists=True,
                supports_claim=True,
                surfaced_doc_id="doc-a",
                final_authority_doc_id="doc-a",
                claimed_authority_label=AuthorityLabel.BINDING,
                expected_authority_label=AuthorityLabel.BINDING,
            ),
            CitationEvaluationRecord(
                record_id="j-2",
                kind=LegalCitationKind.JUDGMENT,
                exists=False,
            ),
            CitationEvaluationRecord(
                record_id="j-3",
                kind=LegalCitationKind.JUDGMENT,
                exists=True,
                supports_claim=False,
                surfaced_doc_id="doc-c",
                final_authority_doc_id="doc-d",
                claimed_authority_label=AuthorityLabel.PERSUASIVE,
                expected_authority_label=AuthorityLabel.BINDING,
            ),
            CitationEvaluationRecord(
                record_id="s-1",
                kind=LegalCitationKind.STATUTE,
                exists=True,
                statute_in_force=True,
                uses_current_text=True,
            ),
            CitationEvaluationRecord(
                record_id="s-2",
                kind=LegalCitationKind.STATUTE,
                exists=True,
                statute_in_force=False,
                uses_current_text=False,
            ),
        ],
        multi_hop_cases=[
            MultiHopEvaluationCase(
                case_id="privacy",
                expected_doc_ids=("doc-a", "doc-b", "doc-c"),
                surfaced_doc_ids=("doc-a", "doc-c"),
            ),
            MultiHopEvaluationCase(
                case_id="bail",
                expected_doc_ids=("doc-d",),
                surfaced_doc_ids=("doc-d",),
            ),
        ],
    )

    assert run.metrics.citation_existence_rate == pytest.approx(2 / 3)
    assert run.metrics.citation_accuracy_rate == pytest.approx(0.5)
    assert run.metrics.appeal_chain_accuracy == pytest.approx(0.5)
    assert run.metrics.jurisdiction_binding_accuracy == pytest.approx(0.5)
    assert run.metrics.temporal_validity_rate == pytest.approx(0.5)
    assert run.metrics.amendment_awareness_rate == pytest.approx(0.5)
    assert run.metrics.multi_hop_completeness == pytest.approx(5 / 6)
    assert run.metrics.bns_bnss_bsa_awareness == pytest.approx(0.0)
    assert run.multi_hop_results[0].completeness == pytest.approx(2 / 3)
    assert run.multi_hop_results[1].completeness == pytest.approx(1.0)


def test_india_legal_evaluation_suite_checks_bns_bnss_bsa_awareness(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'india_legal_eval.db'}")
    Base.metadata.create_all(engine)
    resolver = CriminalCodeMappingResolver()
    suite = IndiaLegalEvaluationSuite(criminal_code_resolver=resolver)

    with Session(engine) as session:
        resolver.upsert_mapping(
            session,
            legacy_code=CriminalCode.IPC,
            legacy_section="302",
            new_code=CriminalCode.BNS,
            new_section="101",
            mapping_status=CriminalCodeMappingStatus.DIRECT,
            legacy_title="Murder",
            new_title="Murder",
        )
        resolver.upsert_mapping(
            session,
            legacy_code=CriminalCode.CRPC,
            legacy_section="437",
            new_code=CriminalCode.BNSS,
            new_section="480",
            mapping_status=CriminalCodeMappingStatus.DIRECT,
            legacy_title="Bail in non-bailable offence",
            new_title="Bail in non-bailable offence",
        )
        session.commit()

        run = suite.run(
            session=session,
            criminal_code_cases=[
                CriminalCodeAwarenessCase(
                    case_id="post-cutover-ipc",
                    query_reference="IPC 302",
                    reference_date=date_value(2024, 7, 1),
                    expected_preferred_reference="BNS 101",
                ),
                CriminalCodeAwarenessCase(
                    case_id="pre-cutover-bnss",
                    query_reference="BNSS 480",
                    reference_date=date_value(2024, 6, 30),
                    expected_preferred_reference="CrPC 437",
                ),
                CriminalCodeAwarenessCase(
                    case_id="intentionally-wrong",
                    query_reference="IPC 302",
                    reference_date=date_value(2024, 6, 30),
                    expected_preferred_reference="BNS 101",
                ),
            ],
        )

    assert run.metrics.bns_bnss_bsa_awareness == pytest.approx(2 / 3)
    assert run.criminal_code_results[0].actual_preferred_reference == "BNS 101"
    assert run.criminal_code_results[1].actual_preferred_reference == "CrPC 437"
    assert run.criminal_code_results[2].correct is False
