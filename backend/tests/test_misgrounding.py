from __future__ import annotations

from app.db.base import Base
from app.db.session import build_engine
from app.models import DocumentChunk, LegalDocument, LegalDocumentType, ValidityStatus
from app.rag import (
    CitationResolutionStatus,
    EntailmentLabel,
    MisgroundingAction,
    MisgroundingChecker,
    MisgroundingStatus,
    PlaceholderKind,
    ResolvedPlaceholder,
)
from sqlalchemy.orm import Session


def _seed_judgment_chunk(
    session: Session,
    *,
    doc_id: str,
    chunk_id: str,
    text: str,
    section_header: str = "Holding",
) -> ResolvedPlaceholder:
    document = LegalDocument(
        doc_id=doc_id,
        doc_type=LegalDocumentType.JUDGMENT,
        court="Supreme Court",
        citation="(2017) 10 SCC 1",
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
        section_header=section_header,
        court="Supreme Court",
        citation="(2017) 10 SCC 1",
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
        rendered_value="Justice K.S. Puttaswamy v Union of India, (2017) 10 SCC 1",
        citation="(2017) 10 SCC 1",
        doc_id=doc_id,
        chunk_id=chunk_id,
        confidence=1.0,
        message="Resolved directly from retrieved corpus context.",
    )


def test_misgrounding_checker_verifies_supported_claims(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'misgrounding_verified.db'}")
    Base.metadata.create_all(engine)
    checker = MisgroundingChecker()

    with Session(engine) as session:
        resolution = _seed_judgment_chunk(
            session,
            doc_id="doc-privacy-verified",
            chunk_id="chunk-privacy-verified",
            text=(
                "The Court held that privacy is a fundamental right protected under "
                "Article 21 and located within the guarantee of life and personal liberty."
            ),
        )
        session.commit()

        result = checker.check_claim(
            session,
            claim="The Court held that privacy is a fundamental right under Article 21.",
            resolution=resolution,
        )

    assert result.status is MisgroundingStatus.VERIFIED
    assert result.entailment_label is EntailmentLabel.ENTAILMENT
    assert result.action is MisgroundingAction.KEEP
    assert result.source_passage is not None


def test_misgrounding_checker_marks_related_but_partial_support_as_uncertain(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'misgrounding_uncertain.db'}")
    Base.metadata.create_all(engine)
    checker = MisgroundingChecker()

    with Session(engine) as session:
        resolution = _seed_judgment_chunk(
            session,
            doc_id="doc-privacy-uncertain",
            chunk_id="chunk-privacy-uncertain",
            text=(
                "The Court addressed privacy concerns in surveillance matters and "
                "required procedural safeguards before telephone interception could occur."
            ),
        )
        session.commit()

        result = checker.check_claim(
            session,
            claim=(
                "The Court expanded dignity jurisprudence while noting privacy concerns "
                "in surveillance matters."
            ),
            resolution=resolution,
        )

    assert result.status is MisgroundingStatus.UNCERTAIN
    assert result.entailment_label is EntailmentLabel.NEUTRAL
    assert result.action is MisgroundingAction.SHOW_SOURCE_TO_USER
    assert result.source_passage is not None


def test_misgrounding_checker_catches_contradicted_claims(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'misgrounding_contradiction.db'}")
    Base.metadata.create_all(engine)
    checker = MisgroundingChecker()

    with Session(engine) as session:
        resolution = _seed_judgment_chunk(
            session,
            doc_id="doc-privacy-contradiction",
            chunk_id="chunk-privacy-contradiction",
            text=(
                "The Court held that privacy was not a fundamental right under "
                "Article 21 in that earlier line of authority."
            ),
        )
        session.commit()

        result = checker.check_claim(
            session,
            claim="The Court held that privacy is a fundamental right under Article 21.",
            resolution=resolution,
        )

    assert result.status is MisgroundingStatus.MISGROUNDED
    assert result.entailment_label is EntailmentLabel.CONTRADICTION
    assert result.action is MisgroundingAction.REMOVE_AND_RERETRIEVE
