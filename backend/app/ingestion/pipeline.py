from __future__ import annotations

from app.ingestion.contracts import (
    BaseIngestionAdapter,
    IngestionExecutionResult,
    IngestionJobContext,
)


class IngestionPipelineRunner:
    def run(
        self,
        adapter: BaseIngestionAdapter,
        context: IngestionJobContext,
    ) -> IngestionExecutionResult:
        stage_trace: list[str] = []

        fetched = adapter.fetch(context)
        stage_trace.append("fetch")

        normalized = adapter.normalize(fetched, context)
        stage_trace.append("normalize")

        parsed = adapter.parse(normalized, context)
        stage_trace.append("parse")

        metadata = adapter.extract_metadata(parsed, context)
        stage_trace.append("extract_metadata")

        citations = adapter.extract_citations(parsed, metadata, context)
        stage_trace.append("extract_citations")

        appeal_links = adapter.resolve_appeal_links(parsed, metadata, citations, context)
        stage_trace.append("resolve_appeal_links")

        chunks = adapter.chunk(parsed, metadata, context)
        stage_trace.append("chunk")

        embedding_tasks = adapter.embed(chunks, metadata, context)
        stage_trace.append("embed")

        projections = adapter.project(
            metadata,
            citations,
            appeal_links,
            chunks,
            embedding_tasks,
            context,
        )
        stage_trace.append("project")

        return IngestionExecutionResult(
            adapter_name=adapter.adapter_name,
            stage_trace=stage_trace,
            fetched=fetched,
            normalized=normalized,
            parsed=parsed,
            metadata=metadata,
            citations=citations,
            appeal_links=appeal_links,
            chunks=chunks,
            embedding_tasks=embedding_tasks,
            projections=projections,
        )
