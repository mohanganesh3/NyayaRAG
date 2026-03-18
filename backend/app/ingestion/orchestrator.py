from __future__ import annotations

from sqlalchemy.orm import Session

from app.ingestion.appeal_chain import AppealChainBuilder
from app.ingestion.citation_graph import CitationGraphProjector
from app.ingestion.contracts import BaseIngestionAdapter, IngestionJobContext
from app.ingestion.embeddings import EmbeddingPipeline
from app.ingestion.persistence import CanonicalIngestionPersister, PersistedIngestionResult
from app.ingestion.pipeline import IngestionPipelineRunner


class IngestionOrchestrator:
    def __init__(
        self,
        runner: IngestionPipelineRunner | None = None,
        persister: CanonicalIngestionPersister | None = None,
        embedding_pipeline: EmbeddingPipeline | None = None,
        graph_projector: CitationGraphProjector | None = None,
        appeal_chain_builder: AppealChainBuilder | None = None,
    ) -> None:
        self.runner = runner or IngestionPipelineRunner()
        self.persister = persister or CanonicalIngestionPersister()
        self.embedding_pipeline = embedding_pipeline or EmbeddingPipeline()
        self.graph_projector = graph_projector or CitationGraphProjector()
        self.appeal_chain_builder = appeal_chain_builder or AppealChainBuilder()

    def ingest(
        self,
        session: Session,
        adapter: BaseIngestionAdapter,
        context: IngestionJobContext,
    ) -> PersistedIngestionResult:
        execution = self.runner.run(adapter, context)
        persisted = self.persister.persist(session, execution, context)
        self.embedding_pipeline.project(session, execution=execution, doc_id=persisted.doc_id)
        self.graph_projector.project(session, execution, persisted.doc_id)
        self.appeal_chain_builder.persist(session, execution, persisted.doc_id)
        session.commit()
        return persisted
