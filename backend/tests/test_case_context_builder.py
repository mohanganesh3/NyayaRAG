from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import app
from app.models import CriminalCode, CriminalCodeMappingStatus
from app.rag import QueryRouter
from app.schemas import PipelineType, QueryType
from app.services.case_contexts import CaseContextBuilder
from app.services.criminal_code_mappings import CriminalCodeMappingResolver
from app.services.upload_ingestion import OcrExtraction, UploadIngestionService
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy.orm import Session


class FakeOcrEngine:
    def __init__(self, outputs: dict[tuple[str, int | None], OcrExtraction]) -> None:
        self._outputs = outputs

    def extract(
        self,
        *,
        content: bytes,
        file_name: str,
        media_type: str,
        page_number: int | None = None,
    ) -> OcrExtraction:
        return self._outputs[(file_name, page_number)]


def _make_blank_pdf() -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(buffer)
    return buffer.getvalue()


def _make_docx(paragraphs: list[str]) -> bytes:
    document_xml = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
        "<w:body>",
    ]
    for paragraph in paragraphs:
        document_xml.append(f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>")
    document_xml.extend(["</w:body>", "</w:document>"])

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "".join(document_xml))
    return buffer.getvalue()


def _seed_criminal_mappings(session: Session) -> None:
    resolver = CriminalCodeMappingResolver()
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


def _build_case_context(session: Session, *, case_id: str) -> str:
    _seed_criminal_mappings(session)

    upload_service = UploadIngestionService(
        ocr_engine=FakeOcrEngine(
            {
                ("fir-scan.pdf", 1): OcrExtraction(
                    text=(
                        "FIR No. 45/2026 dated 17 March 2026. "
                        "Petitioner: Arjun Rao. "
                        "Respondent: State of Maharashtra. "
                        "Offence registered under sectlon 302 lpc."
                    ),
                    confidence=0.9,
                    engine_name="fake-ocr",
                )
            }
        )
    )

    fir_document = upload_service.process_upload(
        file_name="fir-scan.pdf",
        content=_make_blank_pdf(),
    )
    bail_document = upload_service.process_upload(
        file_name="bail-application.docx",
        content=_make_docx(
            [
                "Bail Application BA/1234/2026 before Bombay High Court.",
                "Adv. Meera Rao for petitioner.",
                (
                    "Previous order dated 20 March 2026: Sessions Court rejected bail "
                    "under secfion 437 crpc."
                ),
            ]
        ),
    )

    builder = CaseContextBuilder()
    context = builder.build_from_uploads(
        session,
        processed_documents=[fir_document, bail_document],
        case_id=case_id,
    )
    session.commit()
    return context.case_id


def test_case_context_builder_persists_and_routes_uploaded_context(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'case_context_builder.db'}")
    Base.metadata.create_all(engine)
    router = QueryRouter()
    builder = CaseContextBuilder()

    with Session(engine) as session:
        case_id = _build_case_context(session, case_id="case-bail-001")
        session.expire_all()

        context = builder.get(session, case_id)
        assert context is not None
        assert context.appellant_petitioner == "Arjun Rao"
        assert context.respondent_opposite_party == "State of Maharashtra"
        assert context.advocates == ["Meera Rao"]
        assert context.court == "Bombay High Court"
        assert context.case_number == "BA/1234/2026"
        assert context.charges_sections == ["IPC 302", "CrPC 437"]
        assert context.bnss_equivalents == ["BNS 101", "BNSS 480"]
        assert context.statutes_involved == ["IPC", "CrPC", "BNS", "BNSS"]
        assert context.case_type is not None and context.case_type.value == "criminal"
        assert context.stage is not None and context.stage.value == "bail"
        assert context.key_facts[0]["date"] == "2026-03-17"
        assert context.previous_orders[0]["outcome"] == "rejected"
        assert context.bail_history[0]["status"] == "rejected"
        assert "Whether bail should be granted" in context.open_legal_issues[0]
        assert len(context.uploaded_docs) == 2
        assert context.doc_extraction_confidence >= 0.8

        analysis = router.analyze(
            "What are my bail arguments?",
            session=session,
            case_context=context,
        )
        assert analysis.query_type is QueryType.DOCUMENT_SPECIFIC
        assert analysis.selected_pipeline is PipelineType.AGENTIC_RAG

    engine.dispose()


def test_workspace_route_returns_persisted_case_context(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'workspace_route.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        case_id = _build_case_context(session, case_id="case-bail-002")

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(f"/api/workspace/{case_id}")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["case_id"] == case_id
    assert body["data"]["court"] == "Bombay High Court"
    assert body["data"]["bnss_equivalents"] == ["BNS 101", "BNSS 480"]


def test_workspace_route_returns_not_found_for_missing_case_context(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'workspace_missing.db'}")
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/workspace/missing-case")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "workspace_not_found"
