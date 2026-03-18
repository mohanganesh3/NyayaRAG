from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256

from app.db.base import Base
from app.db.session import build_engine
from app.ingestion import (
    AppealChainBuilder,
    AppealLinkCandidate,
    BaseIngestionAdapter,
    ChunkDraft,
    EmbeddingTask,
    ExtractedMetadata,
    FetchedPayload,
    IngestionJobContext,
    IngestionOrchestrator,
    NormalizedPayload,
    ParsedDocument,
    ProjectionPlan,
    ProjectionTarget,
)
from app.models import (
    AppealOutcome,
    ApprovalStatus,
    LegalDocument,
    LegalDocumentType,
    ValidityStatus,
)
from sqlalchemy.orm import Session


class StaticAppealJudgmentAdapter(BaseIngestionAdapter):
    def __init__(
        self,
        *,
        title: str,
        citation: str,
        court: str,
        decision_date: str,
        external_id: str,
        appeal_links: list[AppealLinkCandidate],
    ) -> None:
        self._title = title
        self._citation = citation
        self._court = court
        self._decision_date = decision_date
        self._external_id = external_id
        self._appeal_links = appeal_links

    @property
    def adapter_name(self) -> str:
        return "static-appeal-judgment-adapter"

    def fetch(self, context: IngestionJobContext) -> FetchedPayload:
        raw_content = context.inline_payload or self._title
        return FetchedPayload(
            source_key=context.source_key,
            source_url=context.source_url,
            external_id=context.external_id,
            raw_content=raw_content,
            content_type="text/plain",
            fetched_at=datetime.now(UTC),
            checksum=sha256(raw_content.encode("utf-8")).hexdigest(),
        )

    def normalize(
        self,
        fetched: FetchedPayload,
        context: IngestionJobContext,
    ) -> NormalizedPayload:
        return NormalizedPayload(
            source_key=fetched.source_key,
            source_url=fetched.source_url,
            raw_content=fetched.raw_content,
            clean_text=fetched.raw_content,
            lines=[fetched.raw_content],
            checksum=fetched.checksum,
        )

    def parse(
        self,
        normalized: NormalizedPayload,
        context: IngestionJobContext,
    ) -> ParsedDocument:
        return ParsedDocument(
            title=self._title,
            body_text=self._title,
            paragraphs=[self._title],
            section_headers=["Holding"],
            source_document_ref=self._external_id,
        )

    def extract_metadata(
        self,
        parsed: ParsedDocument,
        context: IngestionJobContext,
    ) -> ExtractedMetadata:
        appellant, respondent = self._title.split(" v ", maxsplit=1)
        return ExtractedMetadata(
            doc_type=LegalDocumentType.JUDGMENT,
            court=self._court,
            date_text=self._decision_date,
            citation=self._citation,
            neutral_citation=None,
            bench=["Justice A", "Justice B"],
            parties={"appellant": appellant, "respondent": respondent},
            language="en",
            source_document_ref=self._external_id,
            attributes={"jurisdiction_binding": ["All India"]},
        )

    def extract_citations(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list:
        return []

    def resolve_appeal_links(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        citations: list,
        context: IngestionJobContext,
    ) -> list[AppealLinkCandidate]:
        return self._appeal_links

    def chunk(
        self,
        parsed: ParsedDocument,
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[ChunkDraft]:
        return [
            ChunkDraft(
                chunk_key=f"{self._external_id}-chunk-0",
                text=self._title,
                section_header="Holding",
                chunk_index=0,
                total_chunks=1,
            )
        ]

    def embed(
        self,
        chunks: list[ChunkDraft],
        metadata: ExtractedMetadata,
        context: IngestionJobContext,
    ) -> list[EmbeddingTask]:
        return [
            EmbeddingTask(
                chunk_key=chunks[0].chunk_key,
                text=chunks[0].text,
                embedding_model="BGE-M3-v1.5",
            )
        ]

    def project(
        self,
        metadata: ExtractedMetadata,
        citations: list,
        appeal_links: list[AppealLinkCandidate],
        chunks: list[ChunkDraft],
        embedding_tasks: list[EmbeddingTask],
        context: IngestionJobContext,
    ) -> list[ProjectionPlan]:
        return [
            ProjectionPlan(
                target=ProjectionTarget.CANONICAL_DB,
                payload={
                    "parser_version": context.parser_version,
                    "document": {
                        "court": metadata.court,
                        "citation": metadata.citation,
                        "jurisdiction_binding": ["All India"],
                        "full_text": chunks[0].text,
                    },
                },
            ),
            ProjectionPlan(
                target=ProjectionTarget.VECTOR_STORE,
                payload={"chunks": [chunk.chunk_key for chunk in chunks]},
            ),
            ProjectionPlan(
                target=ProjectionTarget.GRAPH_STORE,
                payload={"appeal_links": [link.relation for link in appeal_links]},
            ),
        ]


def _seed_trial_document(session: Session) -> None:
    session.add(
        LegalDocument(
            doc_id="doc-trial-2023",
            doc_type=LegalDocumentType.JUDGMENT,
            court="District Court",
            bench=["Trial Judge"],
            coram=1,
            date=date(2023, 6, 1),
            citation="2023 SCC OnLine Trial 10",
            parties={"appellant": "State", "respondent": "Accused"},
            jurisdiction_binding=["District Court"],
            jurisdiction_persuasive=[],
            current_validity=ValidityStatus.GOOD_LAW,
            distinguished_by=[],
            followed_by=[],
            statutes_interpreted=[],
            statutes_applied=[],
            citations_made=[],
            headnotes=[],
            obiter_dicta=[],
            practice_areas=["criminal"],
            language="en",
            full_text="Trial judgment text.",
            source_system="district-court",
            parser_version="seed-v1",
            approval_status=ApprovalStatus.APPROVED,
        )
    )


def test_multi_level_appeal_chain_resolves_final_authority(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'appeal_chain.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)

    builder = AppealChainBuilder()
    orchestrator = IngestionOrchestrator(appeal_chain_builder=builder)

    with Session(engine) as session:
        _seed_trial_document(session)
        session.commit()

        high_court_adapter = StaticAppealJudgmentAdapter(
            title="State v Accused",
            citation="AIR 2024 Bom 50",
            court="Bombay High Court",
            decision_date="2024-09-05",
            external_id="bombay-hc-2024-50",
            appeal_links=[
                AppealLinkCandidate(
                    source_reference="AIR 2024 Bom 50",
                    target_reference="2023 SCC OnLine Trial 10",
                    relation="reversed",
                    court_name="Bombay High Court",
                    court_level=3,
                    judgment_date="2024-09-05",
                )
            ],
        )
        high_court_result = orchestrator.ingest(
            session,
            high_court_adapter,
            IngestionJobContext(
                source_key="bombay_high_court",
                source_url="https://bombayhighcourt.nic.in/judgment/2024-50",
                parser_version="static-appeal-v1",
                external_id="bombay-hc-2024-50",
                inline_payload="State v Accused",
            ),
        )

        supreme_court_adapter = StaticAppealJudgmentAdapter(
            title="State v Accused",
            citation="(2025) 3 SCC 500",
            court="Supreme Court",
            decision_date="2025-02-01",
            external_id="sc-2025-3-scc-500",
            appeal_links=[
                AppealLinkCandidate(
                    source_reference="(2025) 3 SCC 500",
                    target_reference="AIR 2024 Bom 50",
                    relation="upheld",
                    court_name="Supreme Court",
                    court_level=4,
                    judgment_date="2025-02-01",
                )
            ],
        )
        supreme_court_result = orchestrator.ingest(
            session,
            supreme_court_adapter,
            IngestionJobContext(
                source_key="supreme_court",
                source_url="https://www.sci.gov.in/judgment/2025-3-scc-500",
                parser_version="static-appeal-v1",
                external_id="sc-2025-3-scc-500",
                inline_payload="State v Accused",
            ),
        )

        trial_resolution = builder.resolve_final_authority(session, "doc-trial-2023")
        hc_resolution = builder.resolve_final_authority(session, high_court_result.doc_id)
        sc_resolution = builder.resolve_final_authority(session, supreme_court_result.doc_id)

        assert trial_resolution.use_doc_id == supreme_court_result.doc_id
        assert trial_resolution.effective_outcome is AppealOutcome.REVERSED
        assert trial_resolution.warning is not None
        assert trial_resolution.path_doc_ids == [
            "doc-trial-2023",
            high_court_result.doc_id,
            supreme_court_result.doc_id,
        ]

        assert hc_resolution.use_doc_id == supreme_court_result.doc_id
        assert hc_resolution.effective_outcome is AppealOutcome.UPHELD
        assert hc_resolution.warning is None

        assert sc_resolution.use_doc_id == supreme_court_result.doc_id
        assert sc_resolution.is_final_authority is True

        trial_document = session.get(LegalDocument, "doc-trial-2023")
        assert trial_document is not None
        assert trial_document.current_validity is ValidityStatus.REVERSED_ON_APPEAL
        assert any(
            node.child_doc_id == supreme_court_result.doc_id
            for node in trial_document.appeal_history
        )
        assert sum(1 for node in trial_document.appeal_history if node.is_final_authority) == 1

        high_court_document = session.get(LegalDocument, high_court_result.doc_id)
        assert high_court_document is not None
        assert any(
            node.child_doc_id == supreme_court_result.doc_id
            for node in high_court_document.appeal_history
        )

        cypher = builder.build_neo4j_projection(session, "doc-trial-2023")
        assert any("APPEALED_TO" in statement for statement in cypher)

    engine.dispose()


def test_modified_appeal_resolution_surfaces_warning(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'appeal_chain_modified.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)

    builder = AppealChainBuilder()
    orchestrator = IngestionOrchestrator(appeal_chain_builder=builder)

    with Session(engine) as session:
        _seed_trial_document(session)
        session.commit()

        supreme_court_adapter = StaticAppealJudgmentAdapter(
            title="State v Accused",
            citation="(2025) 4 SCC 700",
            court="Supreme Court",
            decision_date="2025-03-01",
            external_id="sc-2025-4-scc-700",
            appeal_links=[
                AppealLinkCandidate(
                    source_reference="(2025) 4 SCC 700",
                    target_reference="2023 SCC OnLine Trial 10",
                    relation="modified",
                    court_name="Supreme Court",
                    court_level=4,
                    judgment_date="2025-03-01",
                    modifies_ratio=True,
                )
            ],
        )
        result = orchestrator.ingest(
            session,
            supreme_court_adapter,
            IngestionJobContext(
                source_key="supreme_court",
                source_url="https://www.sci.gov.in/judgment/2025-4-scc-700",
                parser_version="static-appeal-v1",
                external_id="sc-2025-4-scc-700",
                inline_payload="State v Accused",
            ),
        )

        resolution = builder.resolve_final_authority(session, "doc-trial-2023")

        assert resolution.use_doc_id == result.doc_id
        assert resolution.effective_outcome is AppealOutcome.MODIFIED
        assert (
            resolution.warning
            == f"This judgment was modified on appeal. Use final authority: {result.doc_id}."
        )

    engine.dispose()
