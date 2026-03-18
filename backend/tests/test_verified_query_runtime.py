from __future__ import annotations

import json

from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import app
from app.models import DocumentChunk, LegalDocument, LegalDocumentType, ValidityStatus
from app.services.query_runtime import query_runtime
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


def _seed_verified_corpus(session: Session) -> None:
    statute_text = (
        "Whoever commits murder shall be punished with death or imprisonment for life."
    )
    judgment_text = (
        "The Court held that BNS 101 requires proof of intention or knowledge "
        "before the offence of murder is made out."
    )

    session.add(
        LegalDocument(
            doc_id="doc-bns-101",
            doc_type=LegalDocumentType.STATUTE,
            court="Parliament of India",
            current_validity=ValidityStatus.GOOD_LAW,
            practice_areas=["criminal"],
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            language="en",
            full_text=statute_text,
            parser_version="seed-v1",
        )
    )
    session.add(
        DocumentChunk(
            chunk_id="chunk-bns-101",
            doc_id="doc-bns-101",
            doc_type=LegalDocumentType.STATUTE,
            text=statute_text,
            text_normalized=statute_text.lower(),
            chunk_index=0,
            total_chunks=1,
            section_header="Section 101 - Murder",
            act_name="Bharatiya Nyaya Sanhita, 2023",
            section_number="101",
            court="Parliament of India",
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            current_validity=ValidityStatus.GOOD_LAW,
            practice_area=["criminal"],
            is_in_force=True,
        )
    )
    session.add(
        LegalDocument(
            doc_id="doc-sc-bns-101",
            doc_type=LegalDocumentType.JUDGMENT,
            court="Supreme Court",
            citation="(2025) 1 SCC 250",
            parties={"appellant": "State of Karnataka", "respondent": "Asha Rao"},
            current_validity=ValidityStatus.GOOD_LAW,
            practice_areas=["criminal"],
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            bench=["Justice A", "Justice B", "Justice C"],
            coram=3,
            language="en",
            full_text=judgment_text,
            parser_version="seed-v1",
        )
    )
    session.add(
        DocumentChunk(
            chunk_id="chunk-sc-bns-101",
            doc_id="doc-sc-bns-101",
            doc_type=LegalDocumentType.JUDGMENT,
            text=judgment_text,
            text_normalized=judgment_text.lower(),
            chunk_index=0,
            total_chunks=1,
            section_header="Holding",
            court="Supreme Court",
            citation="(2025) 1 SCC 250",
            jurisdiction_binding=["All India"],
            jurisdiction_persuasive=[],
            current_validity=ValidityStatus.GOOD_LAW,
            practice_area=["criminal"],
        )
    )
    session.commit()


def test_stream_query_executes_verified_hybrid_pipeline(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'verified_query_runtime.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with Session(engine) as session:
        _seed_verified_corpus(session)

    def override_get_db():
        with Session(engine) as session:
            yield session

    query_runtime.reset()
    query_runtime.set_session_factory_provider(lambda: session_factory)
    app.dependency_overrides[get_db] = override_get_db

    try:
        client = TestClient(app)
        accepted = client.post(
            "/api/query",
            json={"query": "What does BNS 101 say and how have courts interpreted it?"},
        )
        assert accepted.status_code == 202

        stream_url = accepted.json()["data"]["stream_url"]
        response = client.get(stream_url)
    finally:
        query_runtime.reset()
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    payloads = [
        json.loads(chunk.removeprefix("data: "))
        for chunk in response.text.strip().split("\n\n")
        if chunk
    ]

    assert any(payload["type"] == "CITATION_RESOLVED" for payload in payloads)
    assert any(
        payload["type"] == "CITATION_RESOLVED" and payload["status"] == "VERIFIED"
        for payload in payloads
    )
    complete_event = payloads[-1]
    assert complete_event["type"] == "COMPLETE"
    assert complete_event["metrics"]["pipeline"] == "hybrid_crag"
    assert complete_event["metrics"]["mode"] == "verified_query_execution"

    streamed_output = "".join(
        payload["token"] for payload in payloads if payload["type"] == "TOKEN"
    )
    assert "Bharatiya Nyaya Sanhita, 2023" in streamed_output
    assert "(2025) 1 SCC 250" in streamed_output
