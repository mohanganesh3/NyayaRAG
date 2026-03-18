from __future__ import annotations

from app.models import DocumentChunk, LegalDocument, LegalDocumentType, ValidityStatus
from app.rag import (
    GeneratedAnswerDraft,
    GraphSearchResult,
    HybridSearchResult,
    PlaceholderKind,
    PlaceholderOnlyGenerator,
    QueryRouter,
)


def _make_document(
    *,
    doc_id: str,
    doc_type: LegalDocumentType,
    court: str | None = None,
    citation: str | None = None,
    parties: dict[str, str] | None = None,
    practice_areas: list[str] | None = None,
    coram: int | None = None,
) -> LegalDocument:
    return LegalDocument(
        doc_id=doc_id,
        doc_type=doc_type,
        court=court,
        citation=citation,
        parties=parties or {},
        current_validity=ValidityStatus.GOOD_LAW,
        practice_areas=practice_areas or [],
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        bench=["Justice A"] * (coram or 0),
        coram=coram,
        language="en",
    )


def _make_chunk(
    *,
    doc_id: str,
    chunk_id: str,
    doc_type: LegalDocumentType,
    text: str,
    section_header: str | None = None,
    act_name: str | None = None,
    section_number: str | None = None,
    court: str | None = None,
    citation: str | None = None,
    practice_area: list[str] | None = None,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        doc_type=doc_type,
        text=text,
        text_normalized=text.lower(),
        chunk_index=0,
        total_chunks=1,
        section_header=section_header,
        act_name=act_name,
        section_number=section_number,
        court=court,
        citation=citation,
        jurisdiction_binding=["All India"],
        jurisdiction_persuasive=[],
        current_validity=ValidityStatus.GOOD_LAW,
        practice_area=practice_area or [],
    )


def _hybrid_result(
    *,
    doc_id: str,
    chunk_id: str,
    doc_type: LegalDocumentType,
    text: str,
    court: str | None = None,
    citation: str | None = None,
    parties: dict[str, str] | None = None,
    section_header: str | None = None,
    act_name: str | None = None,
    section_number: str | None = None,
    practice_areas: list[str] | None = None,
    coram: int | None = None,
    authority_class: str = "binding",
    authority_label: str = "binding",
    authority_reason: str = "binding authority",
) -> HybridSearchResult:
    document = _make_document(
        doc_id=doc_id,
        doc_type=doc_type,
        court=court,
        citation=citation,
        parties=parties,
        practice_areas=practice_areas,
        coram=coram,
    )
    chunk = _make_chunk(
        doc_id=doc_id,
        chunk_id=chunk_id,
        doc_type=doc_type,
        text=text,
        section_header=section_header,
        act_name=act_name,
        section_number=section_number,
        court=court,
        citation=citation,
        practice_area=practice_areas,
    )
    return HybridSearchResult(
        doc_id=doc_id,
        chunk_id=chunk_id,
        chunk=chunk,
        document=document,
        lexical_score=2.0,
        dense_score=0.8,
        fused_score=0.9,
        rerank_score=0.95,
        authority_tier=1,
        authority_class=authority_class,
        authority_label=authority_label,
        authority_reason=authority_reason,
        matched_terms=["section"],
    )


def _graph_result(
    *,
    doc_id: str,
    chunk_id: str,
    text: str,
    citation: str,
    parties: dict[str, str],
    timeline_phase: str,
) -> GraphSearchResult:
    document = _make_document(
        doc_id=doc_id,
        doc_type=LegalDocumentType.JUDGMENT,
        court="Supreme Court",
        citation=citation,
        parties=parties,
        practice_areas=["constitutional"],
        coram=9,
    )
    chunk = _make_chunk(
        doc_id=doc_id,
        chunk_id=chunk_id,
        doc_type=LegalDocumentType.JUDGMENT,
        text=text,
        section_header="Holding",
        court="Supreme Court",
        citation=citation,
        practice_area=["constitutional"],
    )
    return GraphSearchResult(
        doc_id=doc_id,
        chunk_id=chunk_id,
        chunk=chunk,
        document=document,
        timeline_phase=timeline_phase,
        graph_depth=1,
        relation="follows",
        is_anchor=timeline_phase == "current",
        node_score=0.91,
    )


def test_placeholder_generator_emits_placeholders_only_for_supported_statutory_answer() -> None:
    router = QueryRouter()
    generator = PlaceholderOnlyGenerator()
    analysis = router.analyze("What does BNS 101 say and how have courts interpreted it?")

    results = [
        _hybrid_result(
            doc_id="doc-bns-101",
            chunk_id="chunk-bns-101",
            doc_type=LegalDocumentType.STATUTE,
            text="Whoever commits murder shall be punished with death or life imprisonment.",
            section_header="Section 101 - Murder",
            act_name="Bharatiya Nyaya Sanhita",
            section_number="101",
            practice_areas=["criminal"],
        ),
        _hybrid_result(
            doc_id="doc-sc-murder",
            chunk_id="chunk-sc-murder",
            doc_type=LegalDocumentType.JUDGMENT,
            text=(
                "The Court interpreted the murder provision and clarified the "
                "governing mens rea test."
            ),
            court="Supreme Court",
            citation="(2024) 2 SCC 500",
            parties={"appellant": "State of Maharashtra", "respondent": "Arjun Rao"},
            section_header="Holding",
            practice_areas=["criminal"],
            coram=3,
        ),
    ]

    draft = generator.generate(analysis.raw_query, analysis, results)
    rendered = draft.rendered_text()

    assert "[STATUTE: Bharatiya Nyaya Sanhita, Section 101]" in rendered
    assert "[CITE:" in rendered
    assert "(2024) 2 SCC 500" not in rendered
    assert "State of Maharashtra" not in rendered
    assert "Arjun Rao" not in rendered
    assert all(
        token.startswith("[") and token.endswith("]")
        for token in draft.placeholder_tokens()
    )


def test_placeholder_generator_keeps_graph_outputs_placeholder_only() -> None:
    router = QueryRouter()
    generator = PlaceholderOnlyGenerator()
    analysis = router.analyze("How has the right to privacy developed in India?")

    draft = generator.generate(
        analysis.raw_query,
        analysis,
        [
            _graph_result(
                doc_id="doc-maneka-1978",
                chunk_id="chunk-maneka-1978",
                text="The Court expanded Article 21 and rejected a narrow due process approach.",
                citation="AIR 1978 SC 597",
                parties={"appellant": "Maneka Gandhi", "respondent": "Union of India"},
                timeline_phase="foundational",
            ),
            _graph_result(
                doc_id="doc-puttaswamy-2017",
                chunk_id="chunk-puttaswamy-2017",
                text="The Court held that privacy is a fundamental right protected by Article 21.",
                citation="(2017) 10 SCC 1",
                parties={
                    "appellant": "Justice K.S. Puttaswamy",
                    "respondent": "Union of India",
                },
                timeline_phase="current",
            ),
        ],
    )
    rendered = draft.rendered_text()

    assert "[CITE:" in rendered
    assert "AIR 1978 SC 597" not in rendered
    assert "(2017) 10 SCC 1" not in rendered
    assert "Maneka Gandhi" not in rendered
    assert "Justice K.S. Puttaswamy" not in rendered


def test_placeholder_generator_marks_unsupported_when_no_authorities_exist() -> None:
    router = QueryRouter()
    generator = PlaceholderOnlyGenerator()
    analysis = router.analyze("What is the legal position on this unusual remedy?")

    draft = generator.generate(analysis.raw_query, analysis, [])
    rendered = draft.rendered_text()

    assert isinstance(draft, GeneratedAnswerDraft)
    assert "[UNSUPPORTED:" in rendered
    assert draft.placeholders[0].kind is PlaceholderKind.UNSUPPORTED


def test_placeholder_generator_exposes_prompt_contract_for_strict_generation_rules() -> None:
    contract = PlaceholderOnlyGenerator().build_prompt_contract()

    assert "never write an actual case name or reporter citation" in contract.system_prompt
    assert any("[CITE: brief description]" in rule for rule in contract.rules)
    assert any("[STATUTE: Act name, Section]" in rule for rule in contract.rules)
    assert any("[UNSUPPORTED: proposition text]" in rule for rule in contract.rules)
