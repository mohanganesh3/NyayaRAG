from __future__ import annotations

from app.services.ocr_cleanup import LegalTextNormalizer


def test_ocr_cleanup_normalizes_terms_citations_and_sections() -> None:
    normalizer = LegalTextNormalizer()

    result = normalizer.normalize(
        "The petltloner relied on A1R 1978 SC 597 and (2017) 1O SCC 1 "
        "while seeking u/s 438 crpc relief."
    )

    assert "petitioner" in result.normalized_text
    assert "AIR 1978 SC 597" in result.normalized_text
    assert "(2017) 10 SCC 1" in result.normalized_text
    assert "Section 438 CrPC" in result.normalized_text
    assert result.normalized_citations == ("AIR 1978 SC 597", "(2017) 10 SCC 1")
    assert result.normalized_sections == ("Section 438 CrPC",)
    assert "air_reporter" in result.corrections_applied


def test_ocr_cleanup_deduplicates_party_variants() -> None:
    normalizer = LegalTextNormalizer()

    result = normalizer.normalize(
        "Buckeye Trvst vs PCIT-1 Bangalore. "
        "Petitioner: Buckeye Trust Pvt Ltd. "
        "Respondent: PCIT 1 Bangalore."
    )

    canonical_names = {cluster.canonical_name for cluster in result.normalized_parties}
    assert "Buckeye Trust Pvt Ltd" in canonical_names
    assert any(
        cluster.canonical_name == "Buckeye Trust Pvt Ltd"
        and "Buckeye Trvst" in cluster.aliases
        for cluster in result.normalized_parties
    )
    assert any(
        cluster.canonical_name in {"PCIT-1 Bangalore", "PCIT 1 Bangalore"}
        for cluster in result.normalized_parties
    )
