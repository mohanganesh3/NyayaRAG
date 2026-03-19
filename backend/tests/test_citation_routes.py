from __future__ import annotations

from datetime import date

from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import app
from app.models import (
    AppealNode,
    AppealOutcome,
    DocumentChunk,
    LegalDocument,
    LegalDocumentType,
    StatuteDocument,
    StatuteSection,
    ValidityStatus,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def _seed_citation_corpus(session: Session) -> None:
    high_court_text = (
        "The High Court held that privacy protection depends on statutory procedure."
    )
    supreme_court_text = (
        "The Supreme Court held that privacy is a fundamental right protected under Article 21."
    )
    statute_text = (
        "When any person accused of a non-bailable offence apprehends arrest, "
        "the High Court or Court of Session may grant anticipatory bail."
    )

    high_court = LegalDocument(
        doc_id="doc-hc-privacy",
        doc_type=LegalDocumentType.JUDGMENT,
        court="Delhi High Court",
        citation="2024 SCC OnLine Del 1200",
        parties={"petitioner": "Karan Mehta", "respondent": "State"},
        current_validity=ValidityStatus.GOOD_LAW,
        jurisdiction_binding=["Delhi High Court"],
        jurisdiction_persuasive=["All India"],
        practice_areas=["constitutional"],
        language="en",
        full_text=high_court_text,
        parser_version="seed-v1",
    )
    supreme_court = LegalDocument(
        doc_id="doc-sc-privacy",
        doc_type=LegalDocumentType.JUDGMENT,
        court="Supreme Court",
        citation="(2025) 2 SCC 500",
        parties={"petitioner": "Karan Mehta", "respondent": "Union of India"},
        current_validity=ValidityStatus.GOOD_LAW,
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        practice_areas=["constitutional"],
        language="en",
        full_text=supreme_court_text,
        parser_version="seed-v1",
    )
    statute_document = LegalDocument(
        doc_id="doc-bnss-482",
        doc_type=LegalDocumentType.STATUTE,
        court="Parliament of India",
        citation="BNSS Section 482",
        current_validity=ValidityStatus.GOOD_LAW,
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        practice_areas=["criminal"],
        language="en",
        full_text=statute_text,
        parser_version="seed-v1",
    )
    session.add_all([high_court, supreme_court, statute_document])
    session.flush()

    session.add_all(
        [
            DocumentChunk(
                chunk_id="chunk-hc-privacy",
                doc_id="doc-hc-privacy",
                doc_type=LegalDocumentType.JUDGMENT,
                text=high_court_text,
                text_normalized=high_court_text.lower(),
                chunk_index=0,
                total_chunks=1,
                section_header="Holding",
                court="Delhi High Court",
                citation="2024 SCC OnLine Del 1200",
                jurisdiction_binding=["Delhi High Court"],
                jurisdiction_persuasive=["All India"],
                current_validity=ValidityStatus.GOOD_LAW,
                practice_area=["constitutional"],
            ),
            DocumentChunk(
                chunk_id="chunk-sc-privacy",
                doc_id="doc-sc-privacy",
                doc_type=LegalDocumentType.JUDGMENT,
                text=supreme_court_text,
                text_normalized=supreme_court_text.lower(),
                chunk_index=0,
                total_chunks=1,
                section_header="Holding",
                court="Supreme Court",
                citation="(2025) 2 SCC 500",
                jurisdiction_binding=["All India"],
                jurisdiction_persuasive=[],
                current_validity=ValidityStatus.GOOD_LAW,
                practice_area=["constitutional"],
            ),
            DocumentChunk(
                chunk_id="chunk-bnss-482",
                doc_id="doc-bnss-482",
                doc_type=LegalDocumentType.STATUTE,
                text=statute_text,
                text_normalized=statute_text.lower(),
                chunk_index=0,
                total_chunks=1,
                section_header="Section 482 - Anticipatory bail",
                court="Parliament of India",
                citation="BNSS Section 482",
                jurisdiction_binding=["All India"],
                jurisdiction_persuasive=[],
                current_validity=ValidityStatus.GOOD_LAW,
                practice_area=["criminal"],
                act_name="Bharatiya Nagarik Suraksha Sanhita, 2023",
                section_number="482",
                is_in_force=True,
            ),
        ]
    )
    session.add(
        StatuteDocument(
            doc_id="doc-bnss-482",
            act_name="Bharatiya Nagarik Suraksha Sanhita, 2023",
            short_title="BNSS",
            current_sections_in_force=["482"],
            jurisdiction="All India",
            current_validity=True,
        )
    )
    session.add(
        StatuteSection(
            id="section-bnss-482",
            statute_doc_id="doc-bnss-482",
            section_number="482",
            heading="Anticipatory bail",
            text=statute_text,
            original_text=statute_text,
            is_in_force=True,
            corresponding_new_section="CrPC 438",
            punishment=None,
            cases_interpreting=["doc-sc-privacy"],
        )
    )
    session.add(
        AppealNode(
            id="appeal-hc-privacy",
            document_doc_id="doc-hc-privacy",
            court_level=4,
            court_name="Supreme Court",
            judgment_date=date(2025, 2, 1),
            citation="(2025) 2 SCC 500",
            outcome=AppealOutcome.REVERSED,
            is_final_authority=True,
            modifies_ratio=True,
            parent_doc_id="doc-hc-privacy",
            child_doc_id="doc-sc-privacy",
        )
    )
    session.commit()


def test_citation_source_route_redirects_to_final_authority(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'citation_source.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        _seed_citation_corpus(session)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/citation/doc-hc-privacy/source",
            params={"chunk_id": "chunk-hc-privacy"},
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["doc_id"] == "doc-hc-privacy"
    assert body["data"]["effective_doc_id"] == "doc-sc-privacy"
    assert body["data"]["appeal_status"] == "REDIRECTED"
    assert "reversed" in body["data"]["appeal_warning"].lower()
    assert body["data"]["source_passage"].startswith("The Supreme Court held")


def test_citation_verify_route_returns_grounding_result(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'citation_verify.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        _seed_citation_corpus(session)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/citation/doc-sc-privacy/verify",
            params={
                "chunk_id": "chunk-sc-privacy",
                "claim": "Privacy is a fundamental right protected under Article 21.",
            },
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["resolution_status"] == "VERIFIED"
    assert body["data"]["grounding_status"] == "VERIFIED"
    assert body["data"]["grounding_action"] == "KEEP"
    assert body["data"]["appeal_status"] == "VALID"


def test_citation_routes_expose_appeal_chain_judgment_and_statute_section(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'citation_supporting_routes.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        _seed_citation_corpus(session)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        appeal_response = client.get("/api/citation/doc-hc-privacy/appealchain")
        judgment_response = client.get("/api/judgment/doc-sc-privacy")
        statute_response = client.get("/api/statute/doc-bnss-482/section/482")
        missing_response = client.get("/api/citation/missing/source")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert appeal_response.status_code == 200
    assert appeal_response.json()["data"]["use_doc_id"] == "doc-sc-privacy"
    assert appeal_response.json()["data"]["path_doc_ids"] == [
        "doc-hc-privacy",
        "doc-sc-privacy",
    ]

    assert judgment_response.status_code == 200
    assert judgment_response.json()["data"]["doc_id"] == "doc-sc-privacy"
    assert judgment_response.json()["data"]["doc_type"] == "judgment"

    assert statute_response.status_code == 200
    assert statute_response.json()["data"]["act_name"] == (
        "Bharatiya Nagarik Suraksha Sanhita, 2023"
    )
    assert statute_response.json()["data"]["section"]["section_number"] == "482"

    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "citation_not_found"
