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
        *,
        document_only: bool = False,
        skip_embeddings: bool = False,
        skip_graph_projection: bool = False,
        skip_appeal_chain: bool = False,
    ) -> None:
        self.runner = runner or IngestionPipelineRunner()
        self.persister = persister or CanonicalIngestionPersister()
        self.embedding_pipeline = embedding_pipeline or EmbeddingPipeline()
        self.graph_projector = graph_projector or CitationGraphProjector()
        self.appeal_chain_builder = appeal_chain_builder or AppealChainBuilder()
        self.document_only = document_only
        self.skip_embeddings = skip_embeddings
        self.skip_graph_projection = skip_graph_projection
        self.skip_appeal_chain = skip_appeal_chain

    def ingest(
        self,
        session: Session,
        adapter: BaseIngestionAdapter,
        context: IngestionJobContext,
    ) -> PersistedIngestionResult:
        execution = self.runner.run(
            adapter,
            context,
            skip_chunking=self.document_only,
            skip_embedding=self.document_only or self.skip_embeddings,
        )
        persisted = self.persister.persist(session, execution, context)

        if not (self.document_only or self.skip_embeddings):
            self.embedding_pipeline.project(session, execution=execution, doc_id=persisted.doc_id)
        if not (self.document_only or self.skip_graph_projection):
            self.graph_projector.project(session, execution, persisted.doc_id)
        if not (self.document_only or self.skip_appeal_chain):
            self.appeal_chain_builder.persist(session, execution, persisted.doc_id)
        session.commit()
        return persisted
