from __future__ import annotations

from app.ingestion.chunker import LegalAwareChunker
from app.ingestion.contracts import ExtractedMetadata, IngestionJobContext, ParsedDocument
from app.models import LegalDocumentType


def _metadata(doc_type: LegalDocumentType) -> ExtractedMetadata:
    return ExtractedMetadata(
        doc_type=doc_type,
        court="Supreme Court",
        date_text="2026-03-17",
        citation="Sample Citation",
        neutral_citation=None,
        bench=[],
        parties={},
        language="en",
        source_document_ref="sample-doc",
        attributes={},
    )


def _context() -> IngestionJobContext:
    return IngestionJobContext(
        source_key="test-source",
        source_url="https://example.test/source",
        parser_version="test-parser-v1",
        external_id="sample-doc",
    )


def test_judgment_chunker_preserves_headnotes_ratio_and_obiter_boundaries() -> None:
    chunker = LegalAwareChunker(judgment_target_words=18)
    parsed = ParsedDocument(
        title="Privacy Case",
        body_text="Background text that should not be used when structured segments exist.",
        paragraphs=[],
        section_headers=[],
        source_document_ref="privacy-case",
        attributes={
            "headnotes": [
                "Privacy is a protected constitutional value.",
                "Article 21 includes dignity and autonomy.",
            ],
            "ratio_decidendi": (
                "The Court held that privacy is a fundamental right. "
                "It flows from dignity, liberty, and decisional autonomy."
            ),
            "obiter_dicta": [
                "Comparative law may assist constitutional interpretation."
            ],
        },
    )

    chunks = chunker.chunk(parsed, _metadata(LegalDocumentType.JUDGMENT), _context())

    assert [chunk.attributes["chunk_type"] for chunk in chunks[:2]] == ["headnote", "headnote"]
    assert chunks[0].text == "Privacy is a protected constitutional value."
    assert chunks[1].text == "Article 21 includes dignity and autonomy."
    assert any(chunk.attributes["chunk_type"] == "ratio_decidendi" for chunk in chunks)
    assert any(chunk.attributes["chunk_type"] == "obiter_dictum" for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert {chunk.total_chunks for chunk in chunks} == {len(chunks)}


def test_statute_chunker_preserves_section_identity_for_long_sections() -> None:
    chunker = LegalAwareChunker(statute_target_words=14)
    parsed = ParsedDocument(
        title="Indian Penal Code, 1860",
        body_text="",
        paragraphs=[],
        section_headers=[],
        source_document_ref="ipc-1860",
        attributes={
            "statute_document": {
                "act_name": "Indian Penal Code, 1860",
                "sections": [
                    {
                        "section_number": "498A",
                        "heading": "Cruelty by husband or relatives",
                        "text": (
                            "Whoever subjects a woman to cruelty commits an offence. "
                            "(1) Wilful conduct likely to drive her to suicide. "
                            "(2) Harassment to coerce unlawful demands."
                        ),
                        "is_in_force": True,
                    }
                ],
            }
        },
    )

    chunks = chunker.chunk(parsed, _metadata(LegalDocumentType.STATUTE), _context())

    assert len(chunks) >= 2
    assert {chunk.attributes["section_number"] for chunk in chunks} == {"498A"}
    assert all(
        chunk.section_header == "Section 498A - Cruelty by husband or relatives"
        for chunk in chunks
    )
    assert any("(1)" in chunk.text for chunk in chunks)
    assert any("(2)" in chunk.text for chunk in chunks)
    assert all(chunk.attributes["chunk_type"] == "statute_section" for chunk in chunks)


def test_constitution_chunker_keeps_one_article_per_chunk() -> None:
    chunker = LegalAwareChunker()
    parsed = ParsedDocument(
        title="Constitution of India",
        body_text="",
        paragraphs=[],
        section_headers=[],
        source_document_ref="constitution-of-india",
        attributes={
            "articles": [
                {
                    "article_number": "14",
                    "heading": "Equality before law",
                    "text": "The State shall not deny equality before the law.",
                },
                {
                    "article_number": "21",
                    "heading": "Protection of life and personal liberty",
                    "text": (
                        "No person shall be deprived of life or personal liberty except "
                        "according to procedure established by law."
                    ),
                },
            ]
        },
    )

    chunks = chunker.chunk(parsed, _metadata(LegalDocumentType.CONSTITUTION), _context())

    assert len(chunks) == 2
    assert [chunk.attributes["section_number"] for chunk in chunks] == ["14", "21"]
    assert all(chunk.attributes["chunk_type"] == "constitutional_article" for chunk in chunks)


def test_law_commission_report_chunker_uses_paragraph_overlap() -> None:
    chunker = LegalAwareChunker(report_target_words=16)
    parsed = ParsedDocument(
        title="Law Commission Report No. 280",
        body_text="",
        paragraphs=[
            "Paragraph one introduces the recommendation and issue.",
            "Paragraph two explains the statutory gap in detail.",
            "Paragraph three proposes a reform pathway clearly.",
            "Paragraph four records the implementation warning.",
        ],
        section_headers=["Recommendations"],
        source_document_ref="lc-report-280",
        attributes={},
    )

    chunks = chunker.chunk(parsed, _metadata(LegalDocumentType.LC_REPORT), _context())

    assert len(chunks) >= 2
    first = chunks[0]
    second = chunks[1]
    assert first.attributes["paragraph_start"] == 1
    assert first.attributes["paragraph_end"] == 2
    assert second.attributes["paragraph_start"] == 2
    assert "Paragraph two explains the statutory gap in detail." in first.text
    assert "Paragraph two explains the statutory gap in detail." in second.text
