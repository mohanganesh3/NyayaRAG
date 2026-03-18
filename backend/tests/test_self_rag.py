from __future__ import annotations

from app.db.base import Base
from app.db.session import build_engine
from app.models import DocumentChunk, LegalDocument, LegalDocumentType, ValidityStatus
from app.rag import (
    CitationResolutionStatus,
    GeneratedAnswerDraft,
    GeneratedPlaceholder,
    GeneratedSection,
    PlaceholderKind,
    ResolvedAnswerDraft,
    ResolvedPlaceholder,
    SelfRAGClaimStatus,
    SelfRAGVerifier,
)
from sqlalchemy.orm import Session


def _seed_judgment(
    session: Session,
    *,
    doc_id: str,
    chunk_id: str,
    citation: str,
    text: str,
) -> ResolvedPlaceholder:
    document = LegalDocument(
        doc_id=doc_id,
        doc_type=LegalDocumentType.JUDGMENT,
        court="Supreme Court",
        citation=citation,
        parties={"appellant": "Justice K.S. Puttaswamy", "respondent": "Union of India"},
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        practice_areas=["constitutional"],
        bench=["Justice A", "Justice B", "Justice C"],
        coram=3,
        language="en",
        full_text=text,
        parser_version="test-v1",
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
        court="Supreme Court",
        citation=citation,
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        practice_area=["constitutional"],
    )
    session.add(document)
    session.add(chunk)
    return ResolvedPlaceholder(
        placeholder="[CITE: current doctrinal authority on the constitutional issue]",
        kind=PlaceholderKind.CITE,
        status=CitationResolutionStatus.VERIFIED,
        rendered_value=f"Justice K.S. Puttaswamy v Union of India, {citation}",
        citation=citation,
        doc_id=doc_id,
        chunk_id=chunk_id,
        confidence=1.0,
        message="Resolved directly from retrieved corpus context.",
    )


def _resolved_draft(
    paragraph: str,
    resolutions: tuple[ResolvedPlaceholder, ...],
) -> ResolvedAnswerDraft:
    placeholders = tuple(
        GeneratedPlaceholder(
            token=resolution.placeholder,
            kind=resolution.kind,
            description="placeholder",
            doc_id=resolution.doc_id,
            chunk_id=resolution.chunk_id,
        )
        for resolution in resolutions
    )
    draft = GeneratedAnswerDraft(
        query="What is the legal position?",
        sections=(GeneratedSection(title="Legal Position", paragraphs=(paragraph,)),),
        placeholders=placeholders,
    )
    return ResolvedAnswerDraft(
        draft=draft,
        rendered_text=paragraph,
        resolutions=resolutions,
    )


def test_self_rag_verifier_marks_supported_claims_as_verified(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'self_rag_verified.db'}")
    Base.metadata.create_all(engine)
    verifier = SelfRAGVerifier()

    with Session(engine) as session:
        resolution = _seed_judgment(
            session,
            doc_id="doc-privacy-verified",
            chunk_id="chunk-privacy-verified",
            citation="(2017) 10 SCC 1",
            text=(
                "The Court held that privacy is a fundamental right protected under "
                "Article 21 and forms part of the guarantee of life and personal liberty."
            ),
        )
        session.commit()

        result = verifier.verify(
            session,
            resolved_draft=_resolved_draft(
                "The Court held that privacy is a fundamental right under Article 21 "
                "[CITE: current doctrinal authority on the constitutional issue].",
                (resolution,),
            ),
        )

    assert len(result.claims) == 1
    assert result.claims[0].status is SelfRAGClaimStatus.VERIFIED
    assert result.claims[0].citation == "Justice K.S. Puttaswamy v Union of India, (2017) 10 SCC 1"


def test_self_rag_verifier_labels_claims_without_citations_as_unsupported(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'self_rag_unsupported.db'}")
    Base.metadata.create_all(engine)
    verifier = SelfRAGVerifier()

    with Session(engine) as session:
        result = verifier.verify(
            session,
            resolved_draft=_resolved_draft(
                "Natural justice requires fairness in every case.",
                tuple(),
            ),
        )

    assert len(result.claims) == 1
    assert result.claims[0].status is SelfRAGClaimStatus.UNSUPPORTED
    assert result.claims[0].citation is None


def test_self_rag_verifier_can_reretrieve_for_misgrounded_claims(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'self_rag_reretrieve.db'}")
    Base.metadata.create_all(engine)
    verifier = SelfRAGVerifier()

    with Session(engine) as session:
        original_resolution = _seed_judgment(
            session,
            doc_id="doc-privacy-wrong",
            chunk_id="chunk-privacy-wrong",
            citation="(1963) 2 SCR 100",
            text="The Court held that privacy was not a fundamental right under Article 21.",
        )
        replacement_resolution = _seed_judgment(
            session,
            doc_id="doc-privacy-correct",
            chunk_id="chunk-privacy-correct",
            citation="(2017) 10 SCC 1",
            text=(
                "The Court held that privacy is a fundamental right protected under "
                "Article 21 and located within life and personal liberty."
            ),
        )
        session.commit()

        result = verifier.verify(
            session,
            resolved_draft=_resolved_draft(
                "The Court held that privacy is a fundamental right under Article 21 "
                "[CITE: current doctrinal authority on the constitutional issue].",
                (original_resolution,),
            ),
            reretrieve=lambda _session, claim: replacement_resolution
            if "privacy is a fundamental right" in claim
            else None,
        )

    assert len(result.claims) == 1
    assert result.claims[0].status is SelfRAGClaimStatus.VERIFIED
    assert result.claims[0].reretrieved is True
    assert result.claims[0].citation == "Justice K.S. Puttaswamy v Union of India, (2017) 10 SCC 1"
