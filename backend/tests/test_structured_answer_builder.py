from __future__ import annotations

from app.rag import (
    CitationBadgeStatus,
    CitationResolutionStatus,
    GeneratedAnswerDraft,
    GeneratedPlaceholder,
    GeneratedSection,
    PlaceholderKind,
    ResolvedAnswerDraft,
    ResolvedPlaceholder,
    SelfRAGClaimResult,
    SelfRAGClaimStatus,
    SelfRAGVerificationResult,
    StructuredAnswerBuilder,
    StructuredAnswerSectionKind,
)


def _resolved_draft() -> ResolvedAnswerDraft:
    privacy_token = "[CITE: constitutional privacy authority]"
    article_token = "[STATUTE: Constitution of India, Article 21]"
    remedy_token = "[CITE: unusual remedy authority]"

    draft = GeneratedAnswerDraft(
        query="What is the current legal position?",
        sections=(
            GeneratedSection(
                title="Legal Position",
                paragraphs=(
                    "Privacy is a fundamental right under Article 21 "
                    f"{privacy_token}.",
                ),
            ),
            GeneratedSection(
                title="Applicable Law",
                paragraphs=(
                    f"The governing constitutional provision is {article_token}.",
                ),
            ),
            GeneratedSection(
                title="Key Authorities",
                paragraphs=(
                    f"The claimed extraordinary remedy depends on {remedy_token}.",
                ),
            ),
        ),
        placeholders=(
            GeneratedPlaceholder(
                token=privacy_token,
                kind=PlaceholderKind.CITE,
                description="constitutional privacy authority",
                doc_id="doc-puttaswamy",
                chunk_id="chunk-puttaswamy",
            ),
            GeneratedPlaceholder(
                token=article_token,
                kind=PlaceholderKind.STATUTE,
                description="Constitution of India, Article 21",
                doc_id="doc-article-21",
                chunk_id="chunk-article-21",
            ),
            GeneratedPlaceholder(
                token=remedy_token,
                kind=PlaceholderKind.CITE,
                description="unusual remedy authority",
                doc_id=None,
                chunk_id=None,
            ),
        ),
    )
    return ResolvedAnswerDraft(
        draft=draft,
        rendered_text="rendered",
        resolutions=(
            ResolvedPlaceholder(
                placeholder=privacy_token,
                kind=PlaceholderKind.CITE,
                status=CitationResolutionStatus.VERIFIED,
                rendered_value="Justice K.S. Puttaswamy v Union of India, (2017) 10 SCC 1",
                citation="(2017) 10 SCC 1",
                doc_id="doc-puttaswamy",
                chunk_id="chunk-puttaswamy",
                confidence=0.98,
                message="Resolved directly from retrieved corpus context.",
            ),
            ResolvedPlaceholder(
                placeholder=article_token,
                kind=PlaceholderKind.STATUTE,
                status=CitationResolutionStatus.VERIFIED,
                rendered_value="Constitution of India, Section 21",
                citation="Constitution of India, Section 21",
                doc_id="doc-article-21",
                chunk_id="chunk-article-21",
                confidence=1.0,
                message="Resolved directly from retrieved corpus context.",
            ),
            ResolvedPlaceholder(
                placeholder=remedy_token,
                kind=PlaceholderKind.CITE,
                status=CitationResolutionStatus.UNVERIFIED,
                rendered_value="[UNVERIFIED: unusual remedy authority]",
                citation=None,
                doc_id=None,
                chunk_id=None,
                confidence=0.0,
                message="Specific primary authority could not be located in the corpus.",
            ),
        ),
    )


def test_structured_answer_builder_creates_required_sections_and_badges() -> None:
    builder = StructuredAnswerBuilder()
    resolved_draft = _resolved_draft()
    verification = SelfRAGVerificationResult(
        claims=(
            SelfRAGClaimResult(
                section_title="Legal Position",
                claim="Privacy is a fundamental right under Article 21.",
                citation="Justice K.S. Puttaswamy v Union of India, (2017) 10 SCC 1",
                status=SelfRAGClaimStatus.VERIFIED,
                reason="Best source passage supports the claim.",
                source_passage="Privacy is a fundamental right protected under Article 21.",
                appeal_warning=None,
                source_doc_id="doc-puttaswamy",
                source_chunk_id="chunk-puttaswamy",
                placeholder_tokens=("[CITE: constitutional privacy authority]",),
                reretrieved=False,
            ),
            SelfRAGClaimResult(
                section_title="Applicable Law",
                claim="The governing constitutional provision is Article 21.",
                citation="Constitution of India, Section 21",
                status=SelfRAGClaimStatus.VERIFIED,
                reason="Resolved current in-force constitutional provision.",
                source_passage="No person shall be deprived of his life or personal liberty...",
                appeal_warning=None,
                source_doc_id="doc-article-21",
                source_chunk_id="chunk-article-21",
                placeholder_tokens=("[STATUTE: Constitution of India, Article 21]",),
                reretrieved=False,
            ),
            SelfRAGClaimResult(
                section_title="Key Authorities",
                claim="The claimed extraordinary remedy depends on unusual authority.",
                citation=None,
                status=SelfRAGClaimStatus.UNSUPPORTED,
                reason="Citation could not be verified against the corpus.",
                source_passage=None,
                appeal_warning=None,
                source_doc_id=None,
                source_chunk_id=None,
                placeholder_tokens=("[CITE: unusual remedy authority]",),
                reretrieved=False,
            ),
        )
    )

    answer = builder.build(
        resolved_draft=resolved_draft,
        verification_result=verification,
    )

    assert answer.overall_status is CitationBadgeStatus.UNVERIFIED
    assert [section.title for section in answer.sections] == [
        "Legal Position",
        "Applicable Law",
        "Key Cases",
        "Verification Status",
    ]

    legal_position = answer.section(StructuredAnswerSectionKind.LEGAL_POSITION)
    applicable_law = answer.section(StructuredAnswerSectionKind.APPLICABLE_LAW)
    key_cases = answer.section(StructuredAnswerSectionKind.KEY_CASES)
    verification_status = answer.section(StructuredAnswerSectionKind.VERIFICATION_STATUS)

    assert legal_position.claims[0].citation_badges[0].status is CitationBadgeStatus.VERIFIED
    assert legal_position.claims[0].citation_badges[0].doc_id == "doc-puttaswamy"
    assert applicable_law.claims[0].citation_badges[0].chunk_id == "chunk-article-21"
    assert key_cases.claims[0].citation_badges[0].status is CitationBadgeStatus.UNVERIFIED
    assert key_cases.claims[0].citation_badges[0].label == "[UNVERIFIED: unusual remedy authority]"

    summary = {item.label: item for item in verification_status.status_items}
    assert summary["Verified Claims"].value == "2"
    assert summary["Unverified Claims"].value == "1"
    assert summary["Unresolved Citations"].status is CitationBadgeStatus.UNVERIFIED


def test_structured_answer_builder_marks_uncertain_claims_for_review() -> None:
    builder = StructuredAnswerBuilder()
    resolved_draft = _resolved_draft()
    verification = SelfRAGVerificationResult(
        claims=(
            SelfRAGClaimResult(
                section_title="Key Authorities",
                claim="The pending appeal may alter the operative position.",
                citation="Justice K.S. Puttaswamy v Union of India, (2017) 10 SCC 1",
                status=SelfRAGClaimStatus.UNCERTAIN,
                reason="Source passage is related but does not fully entail the claim.",
                source_passage="Privacy is a fundamental right protected under Article 21.",
                appeal_warning="Appeal pending — this may not be the final judgment.",
                source_doc_id="doc-puttaswamy",
                source_chunk_id="chunk-puttaswamy",
                placeholder_tokens=("[CITE: constitutional privacy authority]",),
                reretrieved=True,
            ),
        )
    )

    answer = builder.build(
        resolved_draft=resolved_draft,
        verification_result=verification,
    )

    key_cases = answer.section(StructuredAnswerSectionKind.KEY_CASES)
    claim = key_cases.claims[0]
    badge = claim.citation_badges[0]

    assert answer.overall_status is CitationBadgeStatus.UNCERTAIN
    assert claim.status is CitationBadgeStatus.UNCERTAIN
    assert claim.reretrieved is True
    assert badge.status is CitationBadgeStatus.UNCERTAIN
    assert badge.source_passage == "Privacy is a fundamental right protected under Article 21."
    assert badge.appeal_warning == "Appeal pending — this may not be the final judgment."
