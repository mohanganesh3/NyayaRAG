from __future__ import annotations

from app.db.base import Base
from app.db.session import build_engine
from app.models import DocumentChunk, LegalDocument, LegalDocumentType, ValidityStatus
from app.rag import (
    CitationResolutionStatus,
    CitationResolver,
    GeneratedAnswerDraft,
    GeneratedPlaceholder,
    GeneratedSection,
    HybridSearchResult,
    PlaceholderKind,
    PlaceholderOnlyGenerator,
    QueryRouter,
)
from sqlalchemy.orm import Session


def _seed_document_with_chunk(
    session: Session,
    *,
    doc_id: str,
    chunk_id: str,
    doc_type: LegalDocumentType,
    text: str,
    court: str | None = None,
    citation: str | None = None,
    parties: dict[str, str] | None = None,
    section_header: str | None = None,
    act_name: str | None = None,
    section_number: str | None = None,
    practice_areas: list[str] | None = None,
    coram: int | None = None,
) -> tuple[LegalDocument, DocumentChunk]:
    document = LegalDocument(
        doc_id=doc_id,
        doc_type=doc_type,
        court=court,
        citation=citation,
        parties=parties or {},
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        practice_areas=practice_areas or [],
        bench=["Justice A"] * (coram or 0),
        coram=coram,
        language="en",
        full_text=text,
        parser_version="test-v1",
    )
    chunk = DocumentChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        doc_type=doc_type,
        text=text,
        text_normalized=text.lower(),
        chunk_index=0,
        total_chunks=1,
        section_header=section_header,
        act_name=act_name,
        section_number=section_number,
        court=court,
        citation=citation,
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        practice_area=practice_areas or [],
        is_in_force=doc_type is LegalDocumentType.STATUTE,
    )
    session.add(document)
    session.add(chunk)
    return document, chunk


def _hybrid_result(
    *,
    document: LegalDocument,
    chunk: DocumentChunk,
    authority_class: str = "binding",
) -> HybridSearchResult:
    return HybridSearchResult(
        doc_id=document.doc_id,
        chunk_id=chunk.chunk_id,
        chunk=chunk,
        document=document,
        lexical_score=2.1,
        dense_score=0.84,
        fused_score=0.92,
        rerank_score=0.96,
        authority_tier=1,
        authority_class=authority_class,
        authority_label=authority_class,
        authority_reason="seeded authority",
        matched_terms=["seed"],
    )


def test_citation_resolver_resolves_direct_placeholders_to_verified_citations(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'citation_resolver_direct.db'}")
    Base.metadata.create_all(engine)
    router = QueryRouter()
    generator = PlaceholderOnlyGenerator()
    resolver = CitationResolver()

    with Session(engine) as session:
        statute_document, statute_chunk = _seed_document_with_chunk(
            session,
            doc_id="doc-bns-101",
            chunk_id="chunk-bns-101",
            doc_type=LegalDocumentType.STATUTE,
            text="Whoever commits murder shall be punished with death or life imprisonment.",
            section_header="Section 101 - Murder",
            act_name="Bharatiya Nyaya Sanhita",
            section_number="101",
            practice_areas=["criminal"],
        )
        judgment_document, judgment_chunk = _seed_document_with_chunk(
            session,
            doc_id="doc-sc-murder",
            chunk_id="chunk-sc-murder",
            doc_type=LegalDocumentType.JUDGMENT,
            text="The Court interpreted the murder provision and clarified the mens rea rule.",
            court="Supreme Court",
            citation="(2024) 2 SCC 500",
            parties={"appellant": "State of Maharashtra", "respondent": "Arjun Rao"},
            section_header="Holding",
            practice_areas=["criminal"],
            coram=3,
        )
        session.commit()

        analysis = router.analyze("What does BNS 101 say and how have courts interpreted it?")
        draft = generator.generate(
            analysis.raw_query,
            analysis,
            [
                _hybrid_result(document=statute_document, chunk=statute_chunk),
                _hybrid_result(document=judgment_document, chunk=judgment_chunk),
            ],
        )
        resolved = resolver.resolve(session, draft)

    assert "[STATUTE:" not in resolved.rendered_text
    assert "[CITE:" not in resolved.rendered_text
    assert "Bharatiya Nyaya Sanhita, Section 101" in resolved.rendered_text
    assert "State of Maharashtra v Arjun Rao, (2024) 2 SCC 500" in resolved.rendered_text
    assert all(
        resolution.status is CitationResolutionStatus.VERIFIED
        for resolution in resolved.resolutions
    )


def test_citation_resolver_falls_back_to_corpus_for_statute_placeholders_without_doc_links(
    tmp_path,
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'citation_resolver_statute_search.db'}")
    Base.metadata.create_all(engine)
    resolver = CitationResolver()

    with Session(engine) as session:
        _seed_document_with_chunk(
            session,
            doc_id="doc-bns-101",
            chunk_id="chunk-bns-101",
            doc_type=LegalDocumentType.STATUTE,
            text="Whoever commits murder shall be punished with death or life imprisonment.",
            section_header="Section 101 - Murder",
            act_name="Bharatiya Nyaya Sanhita",
            section_number="101",
            practice_areas=["criminal"],
        )
        session.commit()

        token = "[STATUTE: Bharatiya Nyaya Sanhita, Section 101]"
        draft = GeneratedAnswerDraft(
            query="What does BNS 101 say?",
            sections=(
                GeneratedSection(
                    title="Applicable Law",
                    paragraphs=(f"The applicable provision is {token}.",),
                ),
            ),
            placeholders=(
                GeneratedPlaceholder(
                    token=token,
                    kind=PlaceholderKind.STATUTE,
                    description="Bharatiya Nyaya Sanhita, Section 101",
                    doc_id=None,
                    chunk_id=None,
                ),
            ),
        )

        resolved = resolver.resolve(session, draft)

    assert "Bharatiya Nyaya Sanhita, Section 101" in resolved.rendered_text
    assert resolved.resolutions[0].status is CitationResolutionStatus.VERIFIED
    assert resolved.resolutions[0].citation == "Bharatiya Nyaya Sanhita, Section 101"


def test_citation_resolver_marks_unverified_when_corpus_match_fails(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'citation_resolver_unverified.db'}")
    Base.metadata.create_all(engine)
    resolver = CitationResolver()

    with Session(engine) as session:
        draft = GeneratedAnswerDraft(
            query="What is the remedy here?",
            sections=(
                GeneratedSection(
                    title="Key Authorities",
                    paragraphs=(
                        "The primary authority is [CITE: binding authority on the unusual remedy].",
                    ),
                ),
            ),
            placeholders=(
                GeneratedPlaceholder(
                    token="[CITE: binding authority on the unusual remedy]",
                    kind=PlaceholderKind.CITE,
                    description="binding authority on the unusual remedy",
                    doc_id=None,
                    chunk_id=None,
                ),
            ),
        )

        resolved = resolver.resolve(session, draft)

    assert "[UNVERIFIED: binding authority on the unusual remedy]" in resolved.rendered_text
    assert resolved.resolutions[0].status is CitationResolutionStatus.UNVERIFIED
