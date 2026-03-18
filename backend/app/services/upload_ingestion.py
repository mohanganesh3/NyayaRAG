from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree
from zipfile import ZipFile

from app.services.ocr_cleanup import LegalTextNormalizer, NormalizedPartyCluster
from pypdf import PdfReader


class UploadedFileKind(StrEnum):
    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"


class UploadPageClassification(StrEnum):
    TYPED_PDF = "typed_pdf"
    SCANNED_PDF = "scanned_pdf"
    IMAGE_OCR = "image_ocr"
    DOCX_TEXT = "docx_text"


class UploadDocumentMode(StrEnum):
    TYPED_PDF = "typed_pdf"
    SCANNED_PDF = "scanned_pdf"
    MIXED_PDF = "mixed_pdf"
    IMAGE_OCR = "image_ocr"
    DOCX_TEXT = "docx_text"


@dataclass(slots=True)
class OcrExtraction:
    text: str
    confidence: float
    engine_name: str


class OcrEngine(Protocol):
    def extract(
        self,
        *,
        content: bytes,
        file_name: str,
        media_type: str,
        page_number: int | None = None,
    ) -> OcrExtraction: ...


@dataclass(slots=True)
class ProcessedUploadPage:
    page_number: int
    classification: UploadPageClassification
    extraction_method: str
    raw_text: str
    text: str
    confidence: float
    character_count: int
    normalized_citations: list[str]
    normalized_sections: list[str]
    normalized_parties: list[NormalizedPartyCluster]
    corrections_applied: list[str]


@dataclass(slots=True)
class ProcessedUploadDocument:
    file_name: str
    media_type: str
    file_kind: UploadedFileKind
    document_mode: UploadDocumentMode
    extraction_method: str
    page_count: int
    pages: list[ProcessedUploadPage]
    raw_extracted_text: str
    extracted_text: str
    confidence: float
    normalized_citations: list[str]
    normalized_sections: list[str]
    normalized_parties: list[NormalizedPartyCluster]


class NullOcrEngine:
    def extract(
        self,
        *,
        content: bytes,
        file_name: str,
        media_type: str,
        page_number: int | None = None,
    ) -> OcrExtraction:
        return OcrExtraction(text="", confidence=0.0, engine_name="null-ocr")


class UploadIngestionService:
    def __init__(
        self,
        *,
        ocr_engine: OcrEngine | None = None,
        text_normalizer: LegalTextNormalizer | None = None,
        typed_pdf_text_threshold: int = 24,
    ) -> None:
        self._ocr_engine = ocr_engine or NullOcrEngine()
        self._text_normalizer = text_normalizer or LegalTextNormalizer()
        self._typed_pdf_text_threshold = typed_pdf_text_threshold

    def process_upload(
        self,
        *,
        file_name: str,
        content: bytes,
        media_type: str | None = None,
    ) -> ProcessedUploadDocument:
        resolved_media_type = media_type or self._default_media_type(file_name)
        file_kind = self._infer_file_kind(file_name, resolved_media_type)

        if file_kind is UploadedFileKind.PDF:
            return self._process_pdf(
                file_name=file_name,
                content=content,
                media_type=resolved_media_type,
            )
        if file_kind is UploadedFileKind.IMAGE:
            return self._process_image(
                file_name=file_name,
                content=content,
                media_type=resolved_media_type,
            )
        if file_kind is UploadedFileKind.DOCX:
            return self._process_docx(
                file_name=file_name,
                content=content,
                media_type=resolved_media_type,
            )
        raise ValueError(f"Unsupported upload type for '{file_name}'.")

    def _process_pdf(
        self,
        *,
        file_name: str,
        content: bytes,
        media_type: str,
    ) -> ProcessedUploadDocument:
        reader = PdfReader(BytesIO(content))
        pages: list[ProcessedUploadPage] = []

        for page_number, page in enumerate(reader.pages, start=1):
            extracted_text = self._normalize_text(page.extract_text() or "")
            if len(extracted_text) >= self._typed_pdf_text_threshold:
                confidence = self._text_confidence(extracted_text, baseline=0.72)
                pages.append(
                    self._build_page(
                        page_number=page_number,
                        classification=UploadPageClassification.TYPED_PDF,
                        extraction_method="pdf_text",
                        raw_text=extracted_text,
                        confidence=confidence,
                    )
                )
                continue

            ocr_result = self._ocr_engine.extract(
                content=content,
                file_name=file_name,
                media_type=media_type,
                page_number=page_number,
            )
            ocr_text = self._normalize_text(ocr_result.text)
            pages.append(
                self._build_page(
                    page_number=page_number,
                    classification=UploadPageClassification.SCANNED_PDF,
                    extraction_method=f"ocr:{ocr_result.engine_name}",
                    raw_text=ocr_text,
                    confidence=self._ocr_confidence(ocr_result.confidence, ocr_text),
                )
            )

        extracted_text = "\n".join(page.text for page in pages if page.text)
        raw_extracted_text = "\n".join(page.raw_text for page in pages if page.raw_text)
        confidence = round(sum(page.confidence for page in pages) / max(len(pages), 1), 3)
        document_mode = self._classify_pdf_document_mode(pages)
        extraction_method = {
            UploadDocumentMode.TYPED_PDF: "pdf_text",
            UploadDocumentMode.SCANNED_PDF: "ocr_pdf",
            UploadDocumentMode.MIXED_PDF: "hybrid_pdf",
        }[document_mode]

        return ProcessedUploadDocument(
            file_name=file_name,
            media_type=media_type,
            file_kind=UploadedFileKind.PDF,
            document_mode=document_mode,
            extraction_method=extraction_method,
            page_count=len(pages),
            pages=pages,
            raw_extracted_text=raw_extracted_text,
            extracted_text=extracted_text,
            confidence=confidence,
            normalized_citations=self._merge_page_list(pages, "normalized_citations"),
            normalized_sections=self._merge_page_list(pages, "normalized_sections"),
            normalized_parties=self._merge_parties(pages),
        )

    def _process_image(
        self,
        *,
        file_name: str,
        content: bytes,
        media_type: str,
    ) -> ProcessedUploadDocument:
        ocr_result = self._ocr_engine.extract(
            content=content,
            file_name=file_name,
            media_type=media_type,
            page_number=1,
        )
        text = self._normalize_text(ocr_result.text)
        page = self._build_page(
            page_number=1,
            classification=UploadPageClassification.IMAGE_OCR,
            extraction_method=f"ocr:{ocr_result.engine_name}",
            raw_text=text,
            confidence=self._ocr_confidence(ocr_result.confidence, text),
        )
        return ProcessedUploadDocument(
            file_name=file_name,
            media_type=media_type,
            file_kind=UploadedFileKind.IMAGE,
            document_mode=UploadDocumentMode.IMAGE_OCR,
            extraction_method=page.extraction_method,
            page_count=1,
            pages=[page],
            raw_extracted_text=page.raw_text,
            extracted_text=page.text,
            confidence=page.confidence,
            normalized_citations=page.normalized_citations,
            normalized_sections=page.normalized_sections,
            normalized_parties=page.normalized_parties,
        )

    def _process_docx(
        self,
        *,
        file_name: str,
        content: bytes,
        media_type: str,
    ) -> ProcessedUploadDocument:
        text = self._normalize_text(self._extract_docx_text(content))
        confidence = self._text_confidence(text, baseline=0.75)
        page = self._build_page(
            page_number=1,
            classification=UploadPageClassification.DOCX_TEXT,
            extraction_method="docx_xml",
            raw_text=text,
            confidence=confidence,
        )
        return ProcessedUploadDocument(
            file_name=file_name,
            media_type=media_type,
            file_kind=UploadedFileKind.DOCX,
            document_mode=UploadDocumentMode.DOCX_TEXT,
            extraction_method=page.extraction_method,
            page_count=1,
            pages=[page],
            raw_extracted_text=page.raw_text,
            extracted_text=page.text,
            confidence=confidence,
            normalized_citations=page.normalized_citations,
            normalized_sections=page.normalized_sections,
            normalized_parties=page.normalized_parties,
        )

    def _infer_file_kind(self, file_name: str, media_type: str) -> UploadedFileKind:
        suffix = Path(file_name).suffix.lower()
        if suffix == ".pdf" or media_type == "application/pdf":
            return UploadedFileKind.PDF
        if suffix == ".docx" or media_type.endswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            return UploadedFileKind.DOCX
        if media_type.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
            return UploadedFileKind.IMAGE
        raise ValueError(f"Unsupported upload media type '{media_type}' for '{file_name}'.")

    def _default_media_type(self, file_name: str) -> str:
        suffix = Path(file_name).suffix.lower()
        if suffix == ".pdf":
            return "application/pdf"
        if suffix == ".docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if suffix == ".png":
            return "image/png"
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix in {".tif", ".tiff"}:
            return "image/tiff"
        return "application/octet-stream"

    def _classify_pdf_document_mode(
        self, pages: list[ProcessedUploadPage]
    ) -> UploadDocumentMode:
        classifications = {page.classification for page in pages}
        if classifications == {UploadPageClassification.TYPED_PDF}:
            return UploadDocumentMode.TYPED_PDF
        if classifications == {UploadPageClassification.SCANNED_PDF}:
            return UploadDocumentMode.SCANNED_PDF
        return UploadDocumentMode.MIXED_PDF

    def _extract_docx_text(self, content: bytes) -> str:
        with ZipFile(BytesIO(content)) as archive:
            try:
                document_xml = archive.read("word/document.xml")
            except KeyError as exc:
                raise ValueError("DOCX archive is missing word/document.xml.") from exc

        root = ElementTree.fromstring(document_xml)
        fragments = [
            node.text.strip()
            for node in root.iter()
            if node.tag.endswith("}t") and node.text and node.text.strip()
        ]
        return " ".join(fragments)

    def _normalize_text(self, text: str) -> str:
        return " ".join(text.split())

    def _build_page(
        self,
        *,
        page_number: int,
        classification: UploadPageClassification,
        extraction_method: str,
        raw_text: str,
        confidence: float,
    ) -> ProcessedUploadPage:
        normalized = self._text_normalizer.normalize(raw_text)
        return ProcessedUploadPage(
            page_number=page_number,
            classification=classification,
            extraction_method=extraction_method,
            raw_text=normalized.raw_text,
            text=normalized.normalized_text,
            confidence=confidence,
            character_count=len(normalized.normalized_text),
            normalized_citations=list(normalized.normalized_citations),
            normalized_sections=list(normalized.normalized_sections),
            normalized_parties=list(normalized.normalized_parties),
            corrections_applied=list(normalized.corrections_applied),
        )

    def _merge_page_list(self, pages: list[ProcessedUploadPage], field_name: str) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for page in pages:
            for value in getattr(page, field_name):
                if value not in seen:
                    seen.add(value)
                    values.append(value)
        return values

    def _merge_parties(self, pages: list[ProcessedUploadPage]) -> list[NormalizedPartyCluster]:
        clusters: list[NormalizedPartyCluster] = []
        seen: set[str] = set()
        for page in pages:
            for cluster in page.normalized_parties:
                if cluster.canonical_name not in seen:
                    seen.add(cluster.canonical_name)
                    clusters.append(cluster)
        return clusters

    def _text_confidence(self, text: str, *, baseline: float) -> float:
        if not text:
            return 0.0
        length_bonus = min(len(text), 500) / 2000
        return round(min(0.99, baseline + length_bonus), 3)

    def _ocr_confidence(self, base_confidence: float, text: str) -> float:
        if not text:
            return round(max(0.0, min(base_confidence, 0.2)), 3)
        density_bonus = min(len(text), 300) / 1500
        return round(min(0.98, max(base_confidence, 0.45) + density_bonus), 3)
