from __future__ import annotations

from dataclasses import dataclass

from app.models import ApprovalStatus, SourceType


@dataclass(frozen=True, slots=True)
class SourceCatalogEntry:
    source_key: str
    display_name: str
    source_type: SourceType
    base_url: str
    canonical_hostname: str
    jurisdiction_scope: list[str]
    update_frequency: str
    access_method: str
    default_parser_version: str
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED
    notes: str | None = None


SOURCE_CATALOG: dict[str, SourceCatalogEntry] = {
    "constitution_of_india": SourceCatalogEntry(
        source_key="constitution_of_india",
        display_name="Constitution of India Corpus",
        source_type=SourceType.STATUTE_PORTAL,
        base_url="https://www.indiacode.nic.in",
        canonical_hostname="www.indiacode.nic.in",
        jurisdiction_scope=["All India"],
        update_frequency="ad hoc",
        access_method="structured_text",
        default_parser_version="constitution-text-v1",
        notes="Canonical constitutional text and amendments.",
    ),
    "india_code": SourceCatalogEntry(
        source_key="india_code",
        display_name="India Code Central Acts",
        source_type=SourceType.STATUTE_PORTAL,
        base_url="https://www.indiacode.nic.in",
        canonical_hostname="www.indiacode.nic.in",
        jurisdiction_scope=["All India"],
        update_frequency="daily",
        access_method="structured_text",
        default_parser_version="indiacode-text-v1",
        notes="Central bare acts and section text.",
    ),
    "bns_bundle": SourceCatalogEntry(
        source_key="bns_bundle",
        display_name="BNS / BNSS / BSA Corpus",
        source_type=SourceType.STATUTE_PORTAL,
        base_url="https://www.indiacode.nic.in",
        canonical_hostname="www.indiacode.nic.in",
        jurisdiction_scope=["All India"],
        update_frequency="ad hoc",
        access_method="structured_text",
        default_parser_version="criminal-code-text-v1",
        notes="New criminal codes effective July 1, 2024.",
    ),
    "supreme_court": SourceCatalogEntry(
        source_key="supreme_court",
        display_name="Supreme Court of India",
        source_type=SourceType.COURT_PORTAL,
        base_url="https://www.sci.gov.in",
        canonical_hostname="www.sci.gov.in",
        jurisdiction_scope=["All India"],
        update_frequency="daily",
        access_method="html_parser",
        default_parser_version="supreme-court-html-v1",
    ),
    "bombay_high_court": SourceCatalogEntry(
        source_key="bombay_high_court",
        display_name="Bombay High Court",
        source_type=SourceType.COURT_PORTAL,
        base_url="https://bombayhighcourt.nic.in",
        canonical_hostname="bombayhighcourt.nic.in",
        jurisdiction_scope=["Maharashtra", "Goa"],
        update_frequency="daily",
        access_method="html_parser",
        default_parser_version="high-court-html-v1",
    ),
    "nclt": SourceCatalogEntry(
        source_key="nclt",
        display_name="National Company Law Tribunal",
        source_type=SourceType.TRIBUNAL_PORTAL,
        base_url="https://nclt.gov.in",
        canonical_hostname="nclt.gov.in",
        jurisdiction_scope=["All India"],
        update_frequency="weekly",
        access_method="html_parser",
        default_parser_version="tribunal-html-v1",
    ),
}
