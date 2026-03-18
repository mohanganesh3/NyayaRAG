from __future__ import annotations

from datetime import UTC, date, datetime

from app.db.base import Base
from app.db.session import build_engine
from app.models import (
    ApprovalStatus,
    DocumentChunk,
    LegalDocument,
    LegalDocumentType,
    StatuteAmendment,
    StatuteDocument,
    StatuteSection,
    ValidityStatus,
)
from app.rag import (
    CRAGAction,
    CRAGValidator,
    HybridSearchResult,
    QueryRouter,
    TemporalSeverity,
    WebSupplement,
    WebSupplementProvider,
)
from sqlalchemy.orm import Session


class StaticWebProvider(WebSupplementProvider):
    def supplement(self, query, analysis):  # type: ignore[override]
        return [
            WebSupplement(
                title="Primary source fallback",
                url="https://example.org/legal-source",
                snippet=f"Supplement for {query}",
            )
        ]


def _seed_statute(
    session: Session,
    *,
    doc_id: str,
    chunk_id: str,
    act_name: str,
    section_number: str,
    text: str,
    embedded_at: datetime | None = None,
    amendment_effective: date | None = None,
    updated_text: str | None = None,
) -> tuple[LegalDocument, DocumentChunk]:
    statute = LegalDocument(
        doc_id=doc_id,
        doc_type=LegalDocumentType.STATUTE,
        court="Parliament of India",
        bench=[],
        date=date(2023, 7, 1),
        citation=f"{act_name} {section_number}",
        parties={},
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        distinguished_by=[],
        followed_by=[],
        statutes_interpreted=[],
        statutes_applied=[],
        citations_made=[],
        headnotes=[],
        obiter_dicta=[],
        practice_areas=["criminal"],
        language="en",
        full_text=text,
        parser_version="seed-v1",
        approval_status=ApprovalStatus.APPROVED,
    )
    chunk = DocumentChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        doc_type=LegalDocumentType.STATUTE,
        text=text,
        text_normalized=text.lower(),
        chunk_index=0,
        total_chunks=1,
        section_header=f"Section {section_number}",
        court="Parliament of India",
        citation=f"{act_name} {section_number}",
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        practice_area=["criminal"],
        act_name=act_name,
        section_number=section_number,
        is_in_force=True,
        embedded_at=embedded_at,
    )
    section = StatuteSection(
        id=f"section-{doc_id}",
        section_number=section_number,
        heading="Punishment",
        text=updated_text or text,
        original_text=text,
        is_in_force=True,
        corresponding_new_section="BNS 101" if act_name == "IPC" else None,
        punishment="Death or imprisonment for life",
        cases_interpreting=[],
    )
    if amendment_effective is not None:
        section.amendments.append(
            StatuteAmendment(
                id=f"amendment-{doc_id}",
                amendment_label="Amendment Act",
                amendment_date=amendment_effective,
                effective_date=amendment_effective,
                summary="Updated the punishment text.",
                previous_text=text,
                updated_text=updated_text or text,
            )
        )
    statute.statute_document = StatuteDocument(
        doc_id=doc_id,
        act_name=act_name,
        short_title=act_name,
        current_sections_in_force=[section_number],
        jurisdiction="Central",
        enforcement_date=date(2023, 7, 1),
        current_validity=True,
        sections=[section],
    )
    statute.chunks.append(chunk)
    session.add(statute)
    session.flush()
    return statute, chunk


def _seed_judgment(
    session: Session,
    *,
    doc_id: str,
    chunk_id: str,
    case_name: tuple[str, str],
    court: str,
    text: str,
    coram: int = 3,
) -> tuple[LegalDocument, DocumentChunk]:
    judgment = LegalDocument(
        doc_id=doc_id,
        doc_type=LegalDocumentType.JUDGMENT,
        court=court,
        bench=[f"Justice {index}" for index in range(coram)],
        coram=coram,
        date=date(2024, 1, 1),
        citation=f"{doc_id}-citation",
        parties={"appellant": case_name[0], "respondent": case_name[1]},
        jurisdiction_binding=["All India"] if court == "Supreme Court" else [court],
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        distinguished_by=[],
        followed_by=[],
        statutes_interpreted=[],
        statutes_applied=[],
        citations_made=[],
        headnotes=[],
        obiter_dicta=[],
        practice_areas=["criminal"],
        language="en",
        full_text=text,
        parser_version="seed-v1",
        approval_status=ApprovalStatus.APPROVED,
    )
    chunk = DocumentChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        doc_type=LegalDocumentType.JUDGMENT,
        text=text,
        text_normalized=text.lower(),
        chunk_index=0,
        total_chunks=1,
        section_header="Holding",
        court=court,
        citation=judgment.citation,
        jurisdiction_binding=judgment.jurisdiction_binding,
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        practice_area=["criminal"],
    )
    judgment.chunks.append(chunk)
    session.add(judgment)
    session.flush()
    return judgment, chunk


def _result(
    document: LegalDocument,
    chunk: DocumentChunk,
    *,
    rerank_score: float = 0.8,
    authority_class: str = "binding",
) -> HybridSearchResult:
    return HybridSearchResult(
        doc_id=document.doc_id,
        chunk_id=chunk.chunk_id,
        chunk=chunk,
        document=document,
        lexical_score=0.5,
        dense_score=0.5,
        fused_score=0.5,
        rerank_score=rerank_score,
        authority_tier=1,
        authority_class=authority_class,
        authority_label=authority_class,
        authority_reason="seed",
        matched_terms=[],
    )


def test_crag_proceeds_for_strong_statutory_context(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'crag_proceed.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    router = QueryRouter()
    validator = CRAGValidator(router=router)

    with Session(engine) as session:
        statute, statute_chunk = _seed_statute(
            session,
            doc_id="doc-bns-101",
            chunk_id="chunk-bns-101",
            act_name="BNS",
            section_number="101",
            text="Section 101 BNS punishes murder with death or imprisonment for life.",
        )
        judgment, judgment_chunk = _seed_judgment(
            session,
            doc_id="doc-sc-murder",
            chunk_id="chunk-sc-murder",
            case_name=("State of Maharashtra", "Arjun Rao"),
            court="Supreme Court",
            text="The Supreme Court interpreted BNS 101 and explained sentencing for murder.",
        )
        session.commit()

        query = "What does BNS 101 say and how have courts interpreted it?"
        analysis = router.analyze(query, session=session)
        result = validator.validate(
            session,
            query,
            [_result(statute, statute_chunk), _result(judgment, judgment_chunk)],
            analysis=analysis,
        )

    assert result.action is CRAGAction.PROCEED
    assert result.score > 0.70
    assert not result.invalid_chunk_ids
    engine.dispose()


def test_crag_refines_partial_retrieval_with_decomposed_queries(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'crag_refine.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    router = QueryRouter()
    validator = CRAGValidator(router=router)

    with Session(engine) as session:
        statute, statute_chunk = _seed_statute(
            session,
            doc_id="doc-bns-101",
            chunk_id="chunk-bns-101",
            act_name="BNS",
            section_number="101",
            text="Section 101 BNS punishes murder with death or imprisonment for life.",
        )
        _, hc_chunk = _seed_judgment(
            session,
            doc_id="doc-hc-murder",
            chunk_id="chunk-hc-murder",
            case_name=("State of Maharashtra", "Ravi Patil"),
            court="Bombay High Court",
            text="Bombay High Court discussed the transition from IPC 302 to BNS 101.",
            coram=2,
        )
        sc_judgment, sc_chunk = _seed_judgment(
            session,
            doc_id="doc-sc-murder",
            chunk_id="chunk-sc-murder",
            case_name=("State of Maharashtra", "Arjun Rao"),
            court="Supreme Court",
            text="The Supreme Court interpreted BNS 101 and explained sentencing for murder.",
        )
        session.commit()

        query = "What does BNS 101 say and how have courts interpreted it?"
        analysis = router.analyze(query, session=session)
        partial_results = [_result(session.get(LegalDocument, "doc-hc-murder"), hc_chunk)]  # type: ignore[arg-type]
        full_results = [_result(statute, statute_chunk), _result(sc_judgment, sc_chunk)]

        def refine_with(refined_query, refined_analysis):
            return full_results

        result = validator.validate(
            session,
            query,
            partial_results,
            analysis=analysis,
            refine_with=refine_with,
        )

    assert result.action is CRAGAction.REFINED
    assert result.refined_queries
    assert {item.doc_id for item in result.results} == {"doc-bns-101", "doc-sc-murder"}
    engine.dispose()


def test_crag_marks_low_relevance_retrieval_as_insufficient(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'crag_insufficient.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    validator = CRAGValidator(router=QueryRouter())

    with Session(engine) as session:
        judgment, judgment_chunk = _seed_judgment(
            session,
            doc_id="doc-unrelated",
            chunk_id="chunk-unrelated",
            case_name=("State of Maharashtra", "Arjun Rao"),
            court="Supreme Court",
            text="This judgment discusses murder sentencing and criminal intent.",
        )
        session.commit()

        result = validator.validate(
            session,
            "What are maritime salvage rights in Lakshadweep?",
            [_result(judgment, judgment_chunk)],
        )

    assert result.action is CRAGAction.INSUFFICIENT
    assert result.score < 0.40
    assert result.warning is not None
    engine.dispose()


def test_crag_flags_temporally_stale_statute_chunks(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'crag_temporal.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    router = QueryRouter()
    validator = CRAGValidator(router=router)

    with Session(engine) as session:
        statute, chunk = _seed_statute(
            session,
            doc_id="doc-bns-101",
            chunk_id="chunk-bns-101",
            act_name="BNS",
            section_number="101",
            text="Original Section 101 text.",
            embedded_at=datetime(2024, 7, 1, tzinfo=UTC),
            amendment_effective=date(2025, 1, 1),
            updated_text="Updated Section 101 text.",
        )
        session.commit()

        query = "What does BNS 101 say?"
        analysis = router.analyze(query, session=session)
        result = validator.validate(
            session,
            query,
            [_result(statute, chunk)],
            analysis=analysis,
        )

    assert result.action is CRAGAction.INSUFFICIENT
    assert result.invalid_chunk_ids == ["chunk-bns-101"]
    assert result.temporal_findings[0].severity is TemporalSeverity.IMPORTANT
    assert "amended on 2025-01-01" in (result.temporal_findings[0].reason or "")
    engine.dispose()


def test_crag_can_attach_web_supplements_for_low_coverage_queries(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'crag_web.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    validator = CRAGValidator(
        router=QueryRouter(),
        web_provider=StaticWebProvider(),
    )

    with Session(engine) as session:
        result = validator.validate(
            session,
            "What are maritime salvage rights in Lakshadweep?",
            [],
        )

    assert result.action is CRAGAction.WEB_SUPPLEMENTED
    assert result.web_supplements
    engine.dispose()
