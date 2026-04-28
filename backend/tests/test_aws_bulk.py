from __future__ import annotations

from datetime import date

from app.ingestion.aws_bulk import (
    _extract_case_number,
    _extract_parties,
    _normalize_neutral_citation,
    _parse_date,
    _practice_areas_for_court,
)


def test_parse_date_handles_common_formats() -> None:
    assert _parse_date("02-01-2025") == date(2025, 1, 2)
    assert _parse_date("2025-01-02") == date(2025, 1, 2)


def test_normalize_neutral_citation_normalizes_spacing() -> None:
    assert _normalize_neutral_citation("2025INSC24") == "2025 INSC 24"


def test_extract_parties_prefers_structured_petitioner_and_respondent() -> None:
    row = {"petitioner": "A", "respondent": "B"}
    assert _extract_parties(row, "ignored") == {"petitioner": "A", "respondent": "B"}


def test_extract_case_number_falls_back_to_title() -> None:
    row = {"title": "WP/28236/2016 of ZUARI CEMENT LIMITED Vs STATE OF ANDHRA PRADESH"}
    assert _extract_case_number(row, "", "ignored.pdf") == "WP/28236/2016"


def test_practice_areas_detect_tax_signal() -> None:
    areas = _practice_areas_for_court("Supreme Court of India", "The assessment order raises a tax dispute.")
    assert "tax" in areas
