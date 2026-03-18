from __future__ import annotations

import re
from itertools import count

from app.ingestion.contracts import (
    ChunkDraft,
    ExtractedMetadata,
    IngestionJobContext,
    ParsedDocument,
)
from app.models import LegalDocumentType

_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
_SUBSECTION_SPLIT_PATTERN = re.compile(r"(?=(?:\(\d+\)|\([A-Za-z]\)))")


class LegalAwareChunker:
    def __init__(
        self,
        *,
        judgment_target_words: int = 140,
        statute_target_words: int = 220,
        report_target_words: int = 220,
    ) -> None:
        self.judgment_target_words = judgment_target_words
        self.statute_target_words = statute_target_words
        self.report_target_words = report_target_words

    def chunk(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[ChunkDraft]:
        if metadata.doc_type is LegalDocumentType.STATUTE:
            chunks = self._chunk_statute(parsed)
        elif metadata.doc_type is LegalDocumentType.CONSTITUTION:
            chunks = self._chunk_constitution(parsed)
        elif metadata.doc_type is LegalDocumentType.LC_REPORT:
            chunks = self._chunk_law_commission_report(parsed)
        elif metadata.doc_type in {LegalDocumentType.JUDGMENT, LegalDocumentType.ORDER}:
            chunks = self._chunk_judgment_like(parsed)
        else:
            chunks = self._chunk_judgment_like(parsed)
        return self._finalize_indices(chunks)

    def _chunk_judgment_like(self, parsed: ParsedDocument) -> list[ChunkDraft]:
        chunks: list[ChunkDraft] = []
        source_ref = parsed.source_document_ref or "document"
        key_counter = count()

        headnotes = self._string_list(parsed.attributes.get("headnotes"))
        for headnote in headnotes:
            chunks.append(
                ChunkDraft(
                    chunk_key=f"{source_ref}-headnote-{next(key_counter)}",
                    text=headnote,
                    section_header="Headnote",
                    chunk_index=0,
                    total_chunks=0,
                    attributes={"chunk_type": "headnote"},
                )
            )

        ratio_decidendi = self._optional_str(parsed.attributes.get("ratio_decidendi"))
        if ratio_decidendi is not None:
            for part_index, fragment in enumerate(
                self._split_sentence_aware(
                    ratio_decidendi,
                    max_words=self.judgment_target_words,
                ),
                start=1,
            ):
                chunks.append(
                    ChunkDraft(
                        chunk_key=f"{source_ref}-ratio-{part_index}",
                        text=fragment,
                        section_header="Ratio Decidendi",
                        chunk_index=0,
                        total_chunks=0,
                        attributes={
                            "chunk_type": "ratio_decidendi",
                            "part_index": part_index,
                        },
                    )
                )

        obiter_dicta = self._string_list(parsed.attributes.get("obiter_dicta"))
        for obiter_index, obiter_text in enumerate(obiter_dicta, start=1):
            for part_index, fragment in enumerate(
                self._split_sentence_aware(
                    obiter_text,
                    max_words=self.judgment_target_words,
                ),
                start=1,
            ):
                chunks.append(
                    ChunkDraft(
                        chunk_key=f"{source_ref}-obiter-{obiter_index}-{part_index}",
                        text=fragment,
                        section_header="Obiter Dicta",
                        chunk_index=0,
                        total_chunks=0,
                        attributes={
                            "chunk_type": "obiter_dictum",
                            "obiter_index": obiter_index,
                            "part_index": part_index,
                        },
                    )
                )

        if chunks:
            return chunks

        paragraphs = [paragraph.strip() for paragraph in parsed.paragraphs if paragraph.strip()]
        if not paragraphs and parsed.body_text.strip():
            paragraphs = [parsed.body_text.strip()]

        for paragraph_index, paragraph in enumerate(paragraphs):
            section_header = None
            if parsed.section_headers:
                header_index = min(paragraph_index, len(parsed.section_headers) - 1)
                section_header = parsed.section_headers[header_index]

            chunk_type = self._infer_judgment_chunk_type(section_header, paragraph)
            for part_index, fragment in enumerate(
                self._split_sentence_aware(paragraph, max_words=self.judgment_target_words),
                start=1,
            ):
                attributes: dict[str, object] = {
                    "chunk_type": chunk_type,
                    "paragraph_index": paragraph_index + 1,
                }
                if part_index > 1:
                    attributes["part_index"] = part_index
                chunks.append(
                    ChunkDraft(
                        chunk_key=f"{source_ref}-chunk-{next(key_counter)}",
                        text=fragment,
                        section_header=section_header,
                        chunk_index=0,
                        total_chunks=0,
                        attributes=attributes,
                    )
                )

        return chunks

    def _chunk_statute(self, parsed: ParsedDocument) -> list[ChunkDraft]:
        statute_document = self._object_dict(parsed.attributes.get("statute_document"))
        sections = self._object_dict_list(statute_document.get("sections"))
        act_name = self._optional_str(statute_document.get("act_name")) or parsed.title
        source_ref = parsed.source_document_ref or "statute"

        chunks: list[ChunkDraft] = []
        for section in sections:
            section_number = self._optional_str(section.get("section_number")) or "unknown"
            heading = self._optional_str(section.get("heading"))
            text = self._optional_str(section.get("text")) or ""
            if not text:
                continue
            section_header = (
                f"Section {section_number} - {heading}"
                if heading
                else f"Section {section_number}"
            )
            section_parts = self._split_statute_section(text)
            for part_index, fragment in enumerate(section_parts, start=1):
                attributes: dict[str, object] = {
                    "chunk_type": "statute_section",
                    "act_name": act_name,
                    "section_number": section_number,
                    "is_in_force": bool(section.get("is_in_force", True)),
                }
                amendment_date = self._optional_str(section.get("amendment_date"))
                if amendment_date is not None:
                    attributes["amendment_date"] = amendment_date
                if len(section_parts) > 1:
                    attributes["section_part"] = part_index
                    chunk_key = f"{source_ref}-section-{section_number}-part-{part_index}"
                else:
                    chunk_key = f"{source_ref}-section-{section_number}"
                chunks.append(
                    ChunkDraft(
                        chunk_key=chunk_key,
                        text=fragment,
                        section_header=section_header,
                        chunk_index=0,
                        total_chunks=0,
                        attributes=attributes,
                    )
                )

        return chunks

    def _chunk_constitution(self, parsed: ParsedDocument) -> list[ChunkDraft]:
        source_ref = parsed.source_document_ref or "constitution"
        act_name = parsed.title
        chunks: list[ChunkDraft] = []

        for article in self._object_dict_list(parsed.attributes.get("articles")):
            article_number = self._optional_str(article.get("article_number")) or "unknown"
            heading = self._optional_str(article.get("heading"))
            text = self._optional_str(article.get("text")) or ""
            if not text:
                continue
            section_header = (
                f"Article {article_number} - {heading}"
                if heading
                else f"Article {article_number}"
            )
            chunks.append(
                ChunkDraft(
                    chunk_key=f"{source_ref}-article-{article_number}",
                    text=text,
                    section_header=section_header,
                    chunk_index=0,
                    total_chunks=0,
                    attributes={
                        "chunk_type": "constitutional_article",
                        "act_name": act_name,
                        "section_number": article_number,
                        "is_in_force": True,
                    },
                )
            )

        return chunks

    def _chunk_law_commission_report(self, parsed: ParsedDocument) -> list[ChunkDraft]:
        paragraphs = [paragraph.strip() for paragraph in parsed.paragraphs if paragraph.strip()]
        if not paragraphs and parsed.body_text.strip():
            paragraphs = [parsed.body_text.strip()]

        source_ref = parsed.source_document_ref or "law-commission-report"
        chunks: list[ChunkDraft] = []
        start = 0
        part_index = 1

        while start < len(paragraphs):
            end = start
            word_total = 0
            while end < len(paragraphs):
                paragraph_word_count = len(paragraphs[end].split())
                if word_total and word_total + paragraph_word_count > self.report_target_words:
                    break
                word_total += paragraph_word_count
                end += 1

            if end == start:
                end += 1

            header = None
            if parsed.section_headers:
                header_index = min(start, len(parsed.section_headers) - 1)
                header = parsed.section_headers[header_index]

            chunks.append(
                ChunkDraft(
                    chunk_key=f"{source_ref}-report-{part_index}",
                    text="\n\n".join(paragraphs[start:end]),
                    section_header=header,
                    chunk_index=0,
                    total_chunks=0,
                    attributes={
                        "chunk_type": "lc_report_paragraphs",
                        "paragraph_start": start + 1,
                        "paragraph_end": end,
                    },
                )
            )

            if end >= len(paragraphs):
                break

            start = max(start + 1, end - 1)
            part_index += 1

        return chunks

    def _split_sentence_aware(self, text: str, *, max_words: int) -> list[str]:
        normalized = " ".join(text.split())
        if not normalized:
            return []

        sentences = [
            segment.strip()
            for segment in _SENTENCE_SPLIT_PATTERN.split(normalized)
            if segment.strip()
        ]
        if len(sentences) <= 1:
            return [normalized]

        chunks: list[str] = []
        current: list[str] = []
        current_words = 0
        for sentence in sentences:
            sentence_words = len(sentence.split())
            if current and current_words + sentence_words > max_words:
                chunks.append(" ".join(current).strip())
                current = [sentence]
                current_words = sentence_words
                continue
            current.append(sentence)
            current_words += sentence_words

        if current:
            chunks.append(" ".join(current).strip())

        return chunks or [normalized]

    def _split_statute_section(self, text: str) -> list[str]:
        normalized = " ".join(text.split())
        if not normalized:
            return []

        raw_parts = [
            part.strip()
            for part in _SUBSECTION_SPLIT_PATTERN.split(normalized)
            if part.strip()
        ]
        if len(raw_parts) <= 1:
            return self._split_sentence_aware(normalized, max_words=self.statute_target_words)

        if not raw_parts[0].startswith("("):
            preamble = raw_parts[0]
            scoped_parts = [
                f"{preamble} {part}".strip()
                for part in raw_parts[1:]
            ]
        else:
            scoped_parts = raw_parts

        split_parts: list[str] = []
        for part in scoped_parts:
            split_parts.extend(
                self._split_sentence_aware(part, max_words=self.statute_target_words)
            )
        return split_parts or [normalized]

    def _infer_judgment_chunk_type(self, section_header: str | None, text: str) -> str:
        haystack = f"{section_header or ''} {text}".lower()
        if "headnote" in haystack or "issue" in haystack or "summary" in haystack:
            return "headnote"
        if "obiter" in haystack or "observation" in haystack or "dicta" in haystack:
            return "obiter_dictum"
        if "holding" in haystack or "ratio" in haystack or "decision" in haystack:
            return "ratio_decidendi"
        return "judgment_paragraph"

    def _finalize_indices(self, chunks: list[ChunkDraft]) -> list[ChunkDraft]:
        total_chunks = len(chunks)
        for index, chunk in enumerate(chunks):
            chunk.chunk_index = index
            chunk.total_chunks = total_chunks
        return chunks

    def _optional_str(self, value: object) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
        return None

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    result.append(stripped)
        return result

    def _object_dict(self, value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return {str(key): item for key, item in value.items()}
        return {}

    def _object_dict_list(self, value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, object]] = []
        for item in value:
            if isinstance(item, dict):
                result.append({str(key): nested for key, nested in item.items()})
        return result
