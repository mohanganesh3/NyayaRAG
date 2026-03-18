from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.upload_ingestion import (
    OcrExtraction,
    UploadDocumentMode,
    UploadIngestionService,
    UploadPageClassification,
)
from pypdf import PdfWriter


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


def _make_text_pdf(text: str) -> bytes:
    escaped_text = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .encode("latin-1", errors="replace")
    )
    stream = b"BT\n/F1 12 Tf\n72 720 Td\n(" + escaped_text + b") Tj\nET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
    ]

    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode())
        payload.extend(obj)
        payload.extend(b"\nendobj\n")

    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode()
    )
    return bytes(payload)


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


def test_upload_ingestion_processes_typed_pdf() -> None:
    service = UploadIngestionService()

    result = service.process_upload(
        file_name="bail-order.pdf",
        content=_make_text_pdf("Section 437 CrPC governs bail in non-bailable offences."),
    )

    assert result.file_name == "bail-order.pdf"
    assert result.document_mode is UploadDocumentMode.TYPED_PDF
    assert result.extraction_method == "pdf_text"
    assert result.page_count == 1
    assert result.pages[0].classification is UploadPageClassification.TYPED_PDF
    assert "Section 437 CrPC" in result.extracted_text
    assert result.confidence >= 0.72


def test_upload_ingestion_processes_scanned_pdf_via_ocr() -> None:
    service = UploadIngestionService(
        ocr_engine=FakeOcrEngine(
            {
                ("fir-scan.pdf", 1): OcrExtraction(
                    text=(
                        "FIR dated 17 March 2026 under A1R 1978 SC 597. "
                        "The petltloner sought u/s 438 crpc relief."
                    ),
                    confidence=0.88,
                    engine_name="fake-ocr",
                )
            }
        )
    )

    result = service.process_upload(
        file_name="fir-scan.pdf",
        content=_make_blank_pdf(),
    )

    assert result.document_mode is UploadDocumentMode.SCANNED_PDF
    assert result.extraction_method == "ocr_pdf"
    assert result.pages[0].classification is UploadPageClassification.SCANNED_PDF
    assert result.raw_extracted_text.startswith("FIR dated 17 March 2026 under A1R")
    assert "AIR 1978 SC 597" in result.extracted_text
    assert "Section 438 CrPC" in result.extracted_text
    assert result.confidence >= 0.88
    assert result.normalized_citations == ["AIR 1978 SC 597"]
    assert result.normalized_sections == ["Section 438 CrPC"]


def test_upload_ingestion_processes_image_via_ocr() -> None:
    service = UploadIngestionService(
        ocr_engine=FakeOcrEngine(
            {
                ("notice.png", 1): OcrExtraction(
                    text="Eviction notice dated 10 March 2026.",
                    confidence=0.81,
                    engine_name="fake-ocr",
                )
            }
        )
    )

    result = service.process_upload(
        file_name="notice.png",
        content=b"fake-image-content",
        media_type="image/png",
    )

    assert result.document_mode is UploadDocumentMode.IMAGE_OCR
    assert result.pages[0].classification is UploadPageClassification.IMAGE_OCR
    assert result.extracted_text == "Eviction notice dated 10 March 2026."
    assert result.confidence >= 0.81


def test_upload_ingestion_processes_docx() -> None:
    service = UploadIngestionService()

    result = service.process_upload(
        file_name="bail-application.docx",
        content=_make_docx(
            [
                "The applicant seeks regular bail.",
                "Section 480 BNSS is invoked for bail in non-bailable offences.",
            ]
        ),
    )

    assert result.document_mode is UploadDocumentMode.DOCX_TEXT
    assert result.extraction_method == "docx_xml"
    assert result.pages[0].classification is UploadPageClassification.DOCX_TEXT
    assert "Section 480 BNSS" in result.extracted_text
    assert result.confidence >= 0.75
