from __future__ import annotations

from datetime import date

from app.db.base import Base
from app.db.session import build_engine
from app.models import (
    AppealNode,
    AppealOutcome,
    DocumentChunk,
    LegalDocument,
    LegalDocumentType,
    ValidityStatus,
)
from app.rag import (
    AppealSeverity,
    AppealValidationStatus,
    AppealValidator,
    CitationResolutionStatus,
    PlaceholderKind,
    ResolvedPlaceholder,
)
from sqlalchemy.orm import Session


def _seed_judgment(
    session: Session,
    *,
    doc_id: str,
    chunk_id: str,
    citation: str,
    parties: tuple[str, str],
    text: str,
    court: str = "Supreme Court",
) -> tuple[LegalDocument, DocumentChunk]:
    document = LegalDocument(
        doc_id=doc_id,
        doc_type=LegalDocumentType.JUDGMENT,
        court=court,
        citation=citation,
        parties={"appellant": parties[0], "respondent": parties[1]},
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        practice_areas=["criminal"],
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
        court=court,
        citation=citation,
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        practice_area=["criminal"],
    )
    session.add(document)
    session.add(chunk)
    return document, chunk


def _resolved_placeholder(
    *,
    token: str,
    doc_id: str,
    chunk_id: str,
    rendered_value: str,
    citation: str,
) -> ResolvedPlaceholder:
    return ResolvedPlaceholder(
        placeholder=token,
        kind=PlaceholderKind.CITE,
        status=CitationResolutionStatus.VERIFIED,
        rendered_value=rendered_value,
        citation=citation,
        doc_id=doc_id,
        chunk_id=chunk_id,
        confidence=1.0,
        message="Resolved directly from retrieved corpus context.",
    )


def test_appeal_validator_redirects_reversed_judgment_to_final_authority(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'appeal_validator_reversed.db'}")
    Base.metadata.create_all(engine)
    validator = AppealValidator()

    with Session(engine) as session:
        trial_document, trial_chunk = _seed_judgment(
            session,
            doc_id="doc-trial-1",
            chunk_id="chunk-trial-1",
            citation="2024 SCC OnLine Trial 10",
            parties=("State", "Accused"),
            text="The trial court convicted the accused.",
            court="District Court",
        )
        supreme_document, _ = _seed_judgment(
            session,
            doc_id="doc-sc-1",
            chunk_id="chunk-sc-1",
            citation="(2025) 3 SCC 500",
            parties=("State", "Accused"),
            text="The Supreme Court reversed the trial judgment and acquitted the accused.",
        )
        trial_document.appeal_history.append(
            AppealNode(
                id="appeal-node-reversed",
                court_level=4,
                court_name="Supreme Court",
                judgment_date=date(2025, 2, 1),
                citation=supreme_document.citation,
                outcome=AppealOutcome.REVERSED,
                is_final_authority=True,
                modifies_ratio=False,
                parent_doc_id=trial_document.doc_id,
                child_doc_id=supreme_document.doc_id,
            )
        )
        trial_document.current_validity = ValidityStatus.REVERSED_ON_APPEAL
        session.commit()

        result = validator.validate(
            session,
            resolution=_resolved_placeholder(
                token="[CITE: binding court authority on the queried issue]",
                doc_id=trial_document.doc_id,
                chunk_id=trial_chunk.chunk_id,
                rendered_value="State v Accused, 2024 SCC OnLine Trial 10",
                citation="2024 SCC OnLine Trial 10",
            ),
        )

    assert result.status is AppealValidationStatus.REDIRECTED
    assert result.severity is AppealSeverity.CRITICAL
    assert result.show_reversal_banner is True
    assert result.effective_resolution.doc_id == "doc-sc-1"
    assert result.effective_resolution.rendered_value == "State v Accused, (2025) 3 SCC 500"
    assert result.warning is not None


def test_appeal_validator_warns_when_appeal_is_pending(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'appeal_validator_pending.db'}")
    Base.metadata.create_all(engine)
    validator = AppealValidator()

    with Session(engine) as session:
        document, chunk = _seed_judgment(
            session,
            doc_id="doc-hc-pending",
            chunk_id="chunk-hc-pending",
            citation="AIR 2025 Bom 10",
            parties=("State", "Accused"),
            text="The High Court granted relief to the accused.",
            court="Bombay High Court",
        )
        document.appeal_history.append(
            AppealNode(
                id="appeal-node-pending",
                court_level=4,
                court_name="Supreme Court",
                judgment_date=date(2026, 1, 5),
                citation=None,
                outcome=AppealOutcome.UPHELD,
                is_final_authority=False,
                modifies_ratio=False,
                parent_doc_id=document.doc_id,
                child_doc_id=None,
            )
        )
        session.commit()

        result = validator.validate(
            session,
            resolution=_resolved_placeholder(
                token="[CITE: binding High Court authority on the queried issue]",
                doc_id=document.doc_id,
                chunk_id=chunk.chunk_id,
                rendered_value="State v Accused, AIR 2025 Bom 10",
                citation="AIR 2025 Bom 10",
            ),
        )

    assert result.status is AppealValidationStatus.PENDING
    assert result.severity is AppealSeverity.WARNING
    assert result.effective_resolution.doc_id == document.doc_id
    assert result.warning == "Appeal pending — this may not be the final judgment."


def test_appeal_validator_surfaces_modified_authority_note(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'appeal_validator_modified.db'}")
    Base.metadata.create_all(engine)
    validator = AppealValidator()

    with Session(engine) as session:
        high_court_document, high_court_chunk = _seed_judgment(
            session,
            doc_id="doc-hc-modified",
            chunk_id="chunk-hc-modified",
            citation="AIR 2024 Bom 55",
            parties=("State", "Accused"),
            text="The High Court partly allowed the appeal.",
            court="Bombay High Court",
        )
        supreme_document, _ = _seed_judgment(
            session,
            doc_id="doc-sc-modified",
            chunk_id="chunk-sc-modified",
            citation="(2025) 4 SCC 700",
            parties=("State", "Accused"),
            text="The Supreme Court modified the operative directions.",
        )
        high_court_document.appeal_history.append(
            AppealNode(
                id="appeal-node-modified",
                court_level=4,
                court_name="Supreme Court",
                judgment_date=date(2025, 3, 1),
                citation=supreme_document.citation,
                outcome=AppealOutcome.MODIFIED,
                is_final_authority=True,
                modifies_ratio=True,
                parent_doc_id=high_court_document.doc_id,
                child_doc_id=supreme_document.doc_id,
            )
        )
        session.commit()

        result = validator.validate(
            session,
            resolution=_resolved_placeholder(
                token="[CITE: binding authority on the queried issue]",
                doc_id=high_court_document.doc_id,
                chunk_id=high_court_chunk.chunk_id,
                rendered_value="State v Accused, AIR 2024 Bom 55",
                citation="AIR 2024 Bom 55",
            ),
        )

    assert result.status is AppealValidationStatus.MODIFIED
    assert result.severity is AppealSeverity.WARNING
    assert result.show_reversal_banner is False
    assert result.effective_resolution.doc_id == "doc-sc-modified"
    assert result.supplementary_doc_id == "doc-sc-modified"
    assert result.warning is not None
    assert "modified on appeal" in result.warning.lower()
