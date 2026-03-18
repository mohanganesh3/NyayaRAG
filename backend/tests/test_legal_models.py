from __future__ import annotations

from datetime import date
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db.base import Base
from app.db.session import build_engine
from app.models import (
    AppealNode,
    AppealOutcome,
    ApprovalStatus,
    CaseContext,
    CaseStage,
    CaseType,
    CitationEdge,
    DocumentChunk,
    LegalDocument,
    LegalDocumentType,
    StatuteAmendment,
    StatuteDocument,
    StatuteSection,
    ValidityStatus,
    VectorStoreCollection,
    VectorStorePoint,
)
from app.schemas import CaseContextRead, LegalDocumentRead, StatuteDocumentRead
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, selectinload


def _make_alembic_config(database_url: str) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_core_legal_model_imports_are_stable() -> None:
    assert LegalDocument.__tablename__ == "legal_documents"
    assert AppealNode.__tablename__ == "appeal_nodes"
    assert StatuteDocument.__tablename__ == "statute_documents"
    assert StatuteSection.__tablename__ == "statute_sections"
    assert StatuteAmendment.__tablename__ == "statute_amendments"
    assert DocumentChunk.__tablename__ == "document_chunks"
    assert CitationEdge.__tablename__ == "citation_edges"
    assert CaseContext.__tablename__ == "case_contexts"
    assert VectorStoreCollection.__tablename__ == "vector_store_collections"
    assert VectorStorePoint.__tablename__ == "vector_store_points"


def test_legal_models_round_trip_and_serialize(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'legal_models.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)

    statute_doc_id = "doc-statute-000000000000000000000001"
    cited_judgment_doc_id = "doc-judgment-000000000000000000000002"
    primary_judgment_doc_id = "doc-judgment-000000000000000000000003"

    with Session(engine) as session:
        statute_document = LegalDocument(
            doc_id=statute_doc_id,
            doc_type=LegalDocumentType.STATUTE,
            court="Parliament of India",
            bench=[],
            date=date(2023, 12, 25),
            citation="BNS 2023",
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
            full_text="Section 101 defines murder under the Bharatiya Nyaya Sanhita.",
            source_system="indiacode.nic.in",
            parser_version="v1",
            approval_status=ApprovalStatus.APPROVED,
            statute_document=StatuteDocument(
                doc_id=statute_doc_id,
                act_name="Bharatiya Nyaya Sanhita, 2023",
                short_title="BNS",
                current_sections_in_force=["101"],
                jurisdiction="Central",
                enforcement_date=date(2024, 7, 1),
                current_validity=True,
                sections=[
                    StatuteSection(
                        id="section-0000000000000000000000000001",
                        section_number="101",
                        heading="Murder",
                        text="Whoever commits murder shall be punished...",
                        original_text="Original BNS Section 101 text.",
                        is_in_force=True,
                        corresponding_new_section="IPC 302",
                        punishment="Death or imprisonment for life.",
                        cases_interpreting=[primary_judgment_doc_id],
                        amendments=[
                            StatuteAmendment(
                                id="amendment-0000000000000000000000001",
                                amendment_label="BNS Clarification Ordinance",
                                amendment_date=date(2025, 1, 1),
                                effective_date=date(2025, 1, 26),
                                summary="Clarified explanation to Section 101.",
                                previous_text="Original BNS Section 101 text.",
                                updated_text="Updated BNS Section 101 text.",
                            )
                        ],
                    )
                ],
            ),
        )

        cited_judgment = LegalDocument(
            doc_id=cited_judgment_doc_id,
            doc_type=LegalDocumentType.JUDGMENT,
            court="Supreme Court",
            bench=["Justice A", "Justice B"],
            coram=2,
            date=date(2012, 1, 5),
            citation="(2012) 1 SCC 40",
            parties={"appellant": "Sanjay Chandra", "respondent": "CBI"},
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            current_validity=ValidityStatus.GOOD_LAW,
            distinguished_by=[],
            followed_by=[primary_judgment_doc_id],
            statutes_interpreted=[],
            statutes_applied=[],
            citations_made=[],
            headnotes=["Bail is the rule, jail is the exception."],
            ratio_decidendi="Bail jurisprudence must account for liberty.",
            obiter_dicta=[],
            practice_areas=["criminal"],
            language="en",
            full_text="The Court reiterated that bail is the rule.",
            source_system="supremecourt.gov.in",
            parser_version="v1",
            approval_status=ApprovalStatus.APPROVED,
        )

        primary_judgment = LegalDocument(
            doc_id=primary_judgment_doc_id,
            doc_type=LegalDocumentType.JUDGMENT,
            court="Supreme Court",
            bench=["Justice X", "Justice Y", "Justice Z"],
            coram=3,
            date=date(2025, 2, 27),
            citation="(2025) 4 SCC 101",
            neutral_citation="2025 INSC 101",
            parties={"appellant": "State of Maharashtra", "respondent": "A Kumar"},
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            current_validity=ValidityStatus.GOOD_LAW,
            distinguished_by=[],
            followed_by=[],
            statutes_interpreted=[{"act": "BNS", "section": "101"}],
            statutes_applied=[{"act": "BNSS", "section": "480"}],
            citations_made=[cited_judgment_doc_id],
            headnotes=["Interim liberty cannot bypass the appeal record."],
            ratio_decidendi="The final appellate authority controls the cited proposition.",
            obiter_dicta=["Trial courts must distinguish pending appeals from final law."],
            practice_areas=["criminal", "procedure"],
            language="en",
            full_text="A later bench must ensure only final authorities are cited.",
            source_system="supremecourt.gov.in",
            source_url="https://www.sci.gov.in/judgment/2025-4-scc-101",
            parser_version="v2",
            approval_status=ApprovalStatus.APPROVED,
            appeal_history=[
                AppealNode(
                    id="appeal-000000000000000000000000000001",
                    court_level=4,
                    court_name="Supreme Court of India",
                    judgment_date=date(2025, 2, 27),
                    citation="(2025) 4 SCC 101",
                    outcome=AppealOutcome.UPHELD,
                    is_final_authority=True,
                    modifies_ratio=False,
                    parent_doc_id="doc-hc-000000000000000000000000000004",
                    child_doc_id=None,
                )
            ],
            chunks=[
                DocumentChunk(
                    chunk_id="chunk-000000000000000000000000000001",
                    doc_type=LegalDocumentType.JUDGMENT,
                    text=(
                        "The Court must rely on the final appellate authority "
                        "before citing a precedent."
                    ),
                    text_normalized=(
                        "the court must rely on the final appellate authority "
                        "before citing a precedent"
                    ),
                    chunk_index=0,
                    total_chunks=1,
                    section_header="Ratio Decidendi",
                    court="Supreme Court",
                    date=date(2025, 2, 27),
                    citation="(2025) 4 SCC 101",
                    jurisdiction_binding=["All India"],
                    jurisdiction_persuasive=[],
                    current_validity=ValidityStatus.GOOD_LAW,
                    practice_area=["criminal", "procedure"],
                    embedding_id="qdrant-point-0001",
                    embedding_model="BGE-M3-v1.5",
                )
            ],
            outgoing_citation_edges=[
                CitationEdge(
                    id="edge-00000000000000000000000000000001",
                    target_doc_id=cited_judgment_doc_id,
                    citation_type="follows",
                )
            ],
        )

        workspace = CaseContext(
            case_id="case-00000000000000000000000000000001",
            appellant_petitioner="A Kumar",
            respondent_opposite_party="State of Maharashtra",
            advocates=["Adv. Meera Rao"],
            case_type=CaseType.CRIMINAL,
            court="Bombay HC",
            case_number="BA/1234/2026",
            stage=CaseStage.BAIL,
            charges_sections=["IPC 302", "BNS 101"],
            bnss_equivalents=["BNSS 480"],
            statutes_involved=["BNS", "BNSS"],
            key_facts=[{"date": "2026-01-12", "fact": "FIR registered"}],
            previous_orders=[{"court": "Sessions Court", "outcome": "Rejected"}],
            bail_history=[{"date": "2026-01-20", "status": "rejected"}],
            open_legal_issues=["Whether prolonged incarceration justifies bail."],
            uploaded_docs=[{"name": "FIR.pdf", "doc_type": "scanned_pdf"}],
            doc_extraction_confidence=0.94,
        )

        session.add_all([statute_document, cited_judgment, primary_judgment, workspace])
        session.commit()
        session.expire_all()

        loaded_judgment = session.scalar(
            select(LegalDocument)
            .where(LegalDocument.doc_id == primary_judgment_doc_id)
            .options(
                selectinload(LegalDocument.appeal_history),
                selectinload(LegalDocument.chunks),
                selectinload(LegalDocument.outgoing_citation_edges),
            )
        )
        assert loaded_judgment is not None

        loaded_statute = session.scalar(
            select(StatuteDocument)
            .where(StatuteDocument.doc_id == statute_doc_id)
            .options(
                selectinload(StatuteDocument.sections).selectinload(StatuteSection.amendments),
            )
        )
        assert loaded_statute is not None

        loaded_case_context = session.get(CaseContext, workspace.case_id)
        assert loaded_case_context is not None

        judgment_read = LegalDocumentRead.model_validate(loaded_judgment)
        statute_read = StatuteDocumentRead.model_validate(loaded_statute)
        case_context_read = CaseContextRead.model_validate(loaded_case_context)

        assert judgment_read.citation == "(2025) 4 SCC 101"
        assert judgment_read.appeal_history[0].outcome is AppealOutcome.UPHELD
        assert judgment_read.outgoing_citation_edges[0].target_doc_id == cited_judgment_doc_id
        assert judgment_read.chunks[0].embedding_model == "BGE-M3-v1.5"

        assert statute_read.act_name == "Bharatiya Nyaya Sanhita, 2023"
        assert statute_read.sections[0].section_number == "101"
        assert (
            statute_read.sections[0].amendments[0].amendment_label
            == "BNS Clarification Ordinance"
        )

        assert case_context_read.case_type is CaseType.CRIMINAL
        assert case_context_read.stage is CaseStage.BAIL
        assert case_context_read.charges_sections == ["IPC 302", "BNS 101"]

    engine.dispose()


def test_alembic_head_contains_core_legal_tables(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'legal_head.db'}"
    config = _make_alembic_config(database_url)

    command.upgrade(config, "head")
    engine = build_engine(database_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert "legal_documents" in table_names
    assert "appeal_nodes" in table_names
    assert "statute_documents" in table_names
    assert "statute_sections" in table_names
    assert "statute_amendments" in table_names
    assert "document_chunks" in table_names
    assert "citation_edges" in table_names
    assert "case_contexts" in table_names

    engine.dispose()
