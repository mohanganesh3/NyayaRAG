from __future__ import annotations

from datetime import date

from app.db.base import Base
from app.db.session import build_engine
from app.ingestion import (
    DailyValidityEngine,
    JudgmentValidityUpdate,
    StatuteSectionUpdate,
    StatuteValidityUpdate,
)
from app.models import (
    ApprovalStatus,
    BackgroundTaskRun,
    CitationEdge,
    DocumentChunk,
    LegalDocument,
    LegalDocumentType,
    StatuteDocument,
    StatuteSection,
    ValidityStatus,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


def _seed_statute_fixture(session: Session) -> tuple[str, str]:
    statute_doc_id = "doc-ipc-302"
    interpreting_judgment_doc_id = "doc-interpret-302"

    statute = LegalDocument(
        doc_id=statute_doc_id,
        doc_type=LegalDocumentType.STATUTE,
        court="Parliament of India",
        bench=[],
        date=date(1860, 10, 6),
        citation="IPC 302",
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
        full_text="Section 302 of the IPC.",
        source_system="indiacode.nic.in",
        parser_version="seed-v1",
        approval_status=ApprovalStatus.APPROVED,
        chunks=[
            DocumentChunk(
                chunk_id="chunk-ipc-302",
                doc_type=LegalDocumentType.STATUTE,
                text="Section 302: Whoever commits murder...",
                text_normalized="section 302 whoever commits murder",
                chunk_index=0,
                total_chunks=1,
                section_header="Section 302",
                court="Parliament of India",
                date=date(1860, 10, 6),
                citation="IPC 302",
                jurisdiction_binding=["All India"],
                jurisdiction_persuasive=[],
                current_validity=ValidityStatus.GOOD_LAW,
                practice_area=["criminal"],
                act_name="IPC",
                section_number="302",
                is_in_force=True,
                embedding_id="embed-ipc-302",
                embedding_model="BGE-M3-v1.5",
            )
        ],
        statute_document=StatuteDocument(
            doc_id=statute_doc_id,
            act_name="Indian Penal Code, 1860",
            short_title="IPC",
            current_sections_in_force=["302"],
            jurisdiction="Central",
            enforcement_date=date(1860, 10, 6),
            current_validity=True,
            sections=[
                StatuteSection(
                    id="section-ipc-302",
                    section_number="302",
                    heading="Punishment for murder",
                    text=(
                        "Whoever commits murder shall be punished with death "
                        "or imprisonment for life."
                    ),
                    original_text="Original Section 302 text.",
                    is_in_force=True,
                    corresponding_new_section="BNS 101",
                    punishment="Death or imprisonment for life.",
                    cases_interpreting=[interpreting_judgment_doc_id],
                )
            ],
        ),
    )

    interpreting_judgment = LegalDocument(
        doc_id=interpreting_judgment_doc_id,
        doc_type=LegalDocumentType.JUDGMENT,
        court="Supreme Court",
        bench=["Justice A", "Justice B"],
        coram=2,
        date=date(2010, 1, 1),
        citation="(2010) 1 SCC 1",
        parties={"appellant": "State", "respondent": "Accused"},
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        distinguished_by=[],
        followed_by=[],
        statutes_interpreted=[{"act": "IPC", "section": "302"}],
        statutes_applied=[],
        citations_made=[],
        headnotes=[],
        obiter_dicta=[],
        practice_areas=["criminal"],
        language="en",
        full_text="Interpretation of Section 302 IPC.",
        source_system="supremecourt.gov.in",
        parser_version="seed-v1",
        approval_status=ApprovalStatus.APPROVED,
        chunks=[
            DocumentChunk(
                chunk_id="chunk-interpret-302",
                doc_type=LegalDocumentType.JUDGMENT,
                text="The Court interpreted Section 302 IPC.",
                text_normalized="the court interpreted section 302 ipc",
                chunk_index=0,
                total_chunks=1,
                section_header="Holding",
                court="Supreme Court",
                date=date(2010, 1, 1),
                citation="(2010) 1 SCC 1",
                jurisdiction_binding=["All India"],
                jurisdiction_persuasive=[],
                current_validity=ValidityStatus.GOOD_LAW,
                practice_area=["criminal"],
                embedding_id="embed-interpret-302",
                embedding_model="BGE-M3-v1.5",
            )
        ],
    )

    session.add(statute)
    session.add(interpreting_judgment)
    session.flush()
    return statute_doc_id, interpreting_judgment_doc_id


def _seed_overrule_fixture(session: Session) -> tuple[str, str, str]:
    target_doc_id = "doc-overruled-judgment"
    citing_doc_id = "doc-citing-judgment"
    authority_doc_id = "doc-overruling-judgment"

    target = LegalDocument(
        doc_id=target_doc_id,
        doc_type=LegalDocumentType.JUDGMENT,
        court="Supreme Court",
        bench=["Justice X", "Justice Y"],
        coram=2,
        date=date(2005, 5, 5),
        citation="(2005) 5 SCC 55",
        parties={"appellant": "A", "respondent": "B"},
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
        practice_areas=["constitutional"],
        language="en",
        full_text="Original constitutional position.",
        source_system="supremecourt.gov.in",
        parser_version="seed-v1",
        approval_status=ApprovalStatus.APPROVED,
        chunks=[
            DocumentChunk(
                chunk_id="chunk-overruled",
                doc_type=LegalDocumentType.JUDGMENT,
                text="Original constitutional position.",
                text_normalized="original constitutional position",
                chunk_index=0,
                total_chunks=1,
                section_header="Holding",
                court="Supreme Court",
                date=date(2005, 5, 5),
                citation="(2005) 5 SCC 55",
                jurisdiction_binding=["All India"],
                jurisdiction_persuasive=[],
                current_validity=ValidityStatus.GOOD_LAW,
                practice_area=["constitutional"],
                embedding_id="embed-overruled",
                embedding_model="BGE-M3-v1.5",
            )
        ],
    )

    citing = LegalDocument(
        doc_id=citing_doc_id,
        doc_type=LegalDocumentType.JUDGMENT,
        court="High Court",
        bench=["Justice M"],
        coram=1,
        date=date(2015, 3, 3),
        citation="AIR 2015 HC 10",
        parties={"appellant": "C", "respondent": "D"},
        jurisdiction_binding=["High Court"],
        jurisdiction_persuasive=["All India"],
        current_validity=ValidityStatus.GOOD_LAW,
        distinguished_by=[],
        followed_by=[],
        statutes_interpreted=[],
        statutes_applied=[],
        citations_made=[target_doc_id],
        headnotes=[],
        obiter_dicta=[],
        practice_areas=["constitutional"],
        language="en",
        full_text="Relied on the 2005 Supreme Court judgment.",
        source_system="highcourt.nic.in",
        parser_version="seed-v1",
        approval_status=ApprovalStatus.APPROVED,
        chunks=[
            DocumentChunk(
                chunk_id="chunk-citing",
                doc_type=LegalDocumentType.JUDGMENT,
                text="Relied on the 2005 Supreme Court judgment.",
                text_normalized="relied on the 2005 supreme court judgment",
                chunk_index=0,
                total_chunks=1,
                section_header="Holding",
                court="High Court",
                date=date(2015, 3, 3),
                citation="AIR 2015 HC 10",
                jurisdiction_binding=["High Court"],
                jurisdiction_persuasive=["All India"],
                current_validity=ValidityStatus.GOOD_LAW,
                practice_area=["constitutional"],
                embedding_id="embed-citing",
                embedding_model="BGE-M3-v1.5",
            )
        ],
    )

    authority = LegalDocument(
        doc_id=authority_doc_id,
        doc_type=LegalDocumentType.JUDGMENT,
        court="Supreme Court",
        bench=["Justice Z"],
        coram=1,
        date=date(2026, 1, 1),
        citation="(2026) 1 SCC 500",
        parties={"appellant": "E", "respondent": "F"},
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
        practice_areas=["constitutional"],
        language="en",
        full_text="Overruling judgment.",
        source_system="supremecourt.gov.in",
        parser_version="seed-v1",
        approval_status=ApprovalStatus.APPROVED,
    )

    session.add_all([target, citing, authority])
    session.flush()
    session.add(
        CitationEdge(
            id="edge-citing-overruled",
            source_doc_id=citing_doc_id,
            target_doc_id=target_doc_id,
            citation_type="follows",
        )
    )
    session.flush()
    return target_doc_id, citing_doc_id, authority_doc_id


def test_statute_amendment_propagates_reembedding_and_stale_flags(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'validity_amendment.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        statute_doc_id, interpreting_doc_id = _seed_statute_fixture(session)
        engine_service = DailyValidityEngine()

        report = engine_service.run(
            session,
            statute_updates=[
                StatuteValidityUpdate(
                    doc_id=statute_doc_id,
                    current_validity=True,
                    sections=[
                        StatuteSectionUpdate(
                            section_number="302",
                            updated_text=(
                                "Whoever commits murder shall be punished "
                                "under the amended text."
                            ),
                            amendment_label="Criminal Law Amendment 2025",
                            amendment_date=date(2025, 1, 1),
                            effective_date=date(2025, 1, 26),
                            summary="Updated Section 302 text.",
                            corresponding_new_section="BNS 101",
                        )
                    ],
                )
            ],
        )
        session.commit()

        statute = session.get(LegalDocument, statute_doc_id)
        assert statute is not None
        assert statute.current_validity is ValidityStatus.AMENDED
        assert statute.projection_stale is True
        assert statute.validity_checked_at is not None
        assert statute.statute_document is not None
        section = statute.statute_document.sections[0]
        assert section.text == "Whoever commits murder shall be punished under the amended text."
        assert len(section.amendments) == 1
        assert statute.chunks[0].needs_reembedding is True
        assert statute.chunks[0].projection_stale is True

        interpreting_document = session.get(LegalDocument, interpreting_doc_id)
        assert interpreting_document is not None
        assert interpreting_document.projection_stale is True
        assert interpreting_document.chunks[0].needs_reembedding is True

        task_run = session.scalar(select(BackgroundTaskRun))
        assert task_run is not None
        assert task_run.status == "succeeded"
        assert report.statute_updates_applied == 1
        assert report.judgment_updates_applied == 0

    engine.dispose()


def test_repeal_and_overrule_updates_invalidate_dependent_projections(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'validity_repeal_overrule.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        statute_doc_id, _ = _seed_statute_fixture(session)
        target_doc_id, citing_doc_id, authority_doc_id = _seed_overrule_fixture(session)
        engine_service = DailyValidityEngine()

        report = engine_service.run(
            session,
            statute_updates=[
                StatuteValidityUpdate(
                    doc_id=statute_doc_id,
                    current_validity=False,
                    replaced_by="Bharatiya Nyaya Sanhita, 2023",
                    replaced_on=date(2024, 7, 1),
                )
            ],
            judgment_updates=[
                JudgmentValidityUpdate(
                    target_doc_id=target_doc_id,
                    new_validity=ValidityStatus.OVERRULED,
                    authority_doc_id=authority_doc_id,
                    authority_date=date(2026, 1, 1),
                    note="Overruled by later constitution bench.",
                )
            ],
        )
        session.commit()

        statute = session.get(LegalDocument, statute_doc_id)
        assert statute is not None
        assert statute.current_validity is ValidityStatus.REPEALED
        assert statute.projection_stale is True
        assert statute.chunks[0].projection_stale is True
        assert statute.chunks[0].needs_reembedding is False

        target = session.get(LegalDocument, target_doc_id)
        assert target is not None
        assert target.current_validity is ValidityStatus.OVERRULED
        assert target.overruled_by == authority_doc_id
        assert target.chunks[0].projection_stale is True

        citing = session.get(LegalDocument, citing_doc_id)
        assert citing is not None
        assert citing.projection_stale is True
        assert citing.chunks[0].projection_stale is True
        assert citing.chunks[0].needs_reembedding is False

        assert report.statute_updates_applied == 1
        assert report.judgment_updates_applied == 1
        assert target_doc_id in report.stale_document_ids
        assert citing_doc_id in report.stale_document_ids

    engine.dispose()
