from __future__ import annotations

from datetime import date as date_value

from app.db.base import Base
from app.db.session import build_engine
from app.models import CriminalCode, CriminalCodeMappingStatus, ValidityStatus
from app.rag import LegalLexicalDocument, LexicalRetriever
from app.services.criminal_code_mappings import CriminalCodeMappingResolver
from sqlalchemy.orm import Session


def test_lexical_retriever_expands_bns_mapping_for_post_cutover_section_query(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'lexical_section.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    resolver = CriminalCodeMappingResolver()

    with Session(engine) as session:
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
        session.commit()

        documents = [
            LegalLexicalDocument(
                doc_id="doc-bns-101",
                chunk_id="chunk-bns-101",
                text=(
                    "Whoever commits murder shall be punished with death or imprisonment "
                    "for life."
                ),
                act_name="Bharatiya Nyaya Sanhita, 2023",
                section_number="101",
                section_header="Section 101 - Murder",
                current_validity=ValidityStatus.GOOD_LAW.value,
            ),
            LegalLexicalDocument(
                doc_id="doc-bns-318",
                chunk_id="chunk-bns-318",
                text="Cheating and dishonestly inducing delivery of property.",
                act_name="Bharatiya Nyaya Sanhita, 2023",
                section_number="318",
                section_header="Section 318 - Cheating",
                current_validity=ValidityStatus.GOOD_LAW.value,
            ),
        ]

        results = LexicalRetriever(documents).search(
            "What does Section 302 IPC say?",
            top_k=2,
            session=session,
            reference_date=date_value(2024, 7, 1),
        )

        assert results
        assert results[0].doc_id == "doc-bns-101"
        assert results[0].document.section_number == "101"


def test_lexical_retriever_matches_exact_case_name_from_metadata() -> None:
    documents = [
        LegalLexicalDocument(
            doc_id="doc-puttaswamy",
            chunk_id="chunk-puttaswamy",
            text="The Court held that privacy is a fundamental right under Article 21.",
            citation="(2017) 10 SCC 1",
            court="Supreme Court",
            parties={
                "appellant": "Justice K.S. Puttaswamy",
                "respondent": "Union of India",
            },
            current_validity=ValidityStatus.GOOD_LAW.value,
        ),
        LegalLexicalDocument(
            doc_id="doc-maneka",
            chunk_id="chunk-maneka",
            text="Procedure established by law must be just, fair and reasonable.",
            citation="AIR 1978 SC 597",
            court="Supreme Court",
            parties={
                "appellant": "Maneka Gandhi",
                "respondent": "Union of India",
            },
            current_validity=ValidityStatus.GOOD_LAW.value,
        ),
    ]

    results = LexicalRetriever(documents).search(
        "Justice K.S. Puttaswamy v Union of India",
        top_k=1,
    )

    assert results
    assert results[0].doc_id == "doc-puttaswamy"
    assert "puttaswamy" in results[0].matched_terms
