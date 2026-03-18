from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_value
from typing import cast

from app.rag import (
    CitationResolver,
    CRAGResult,
    CRAGValidator,
    GeneratedAnswerDraft,
    GraphRAGPipeline,
    GraphSearchResult,
    HybridRAGPipeline,
    HybridSearchResult,
    HyDEPipeline,
    PlaceholderOnlyGenerator,
    QueryRouter,
    ResolvedAnswerDraft,
    SelfRAGVerificationResult,
    SelfRAGVerifier,
    StructuredAnswer,
    StructuredAnswerBuilder,
)
from app.schemas import PipelineType, QueryAnalysis
from sqlalchemy.orm import Session

RetrievedResult = HybridSearchResult | GraphSearchResult


@dataclass(slots=True, frozen=True)
class VerifiedQueryExecutionResult:
    analysis: QueryAnalysis
    crag_result: CRAGResult
    generated_draft: GeneratedAnswerDraft
    pipeline: str
    resolved_draft: ResolvedAnswerDraft
    structured_answer: StructuredAnswer
    verification_result: SelfRAGVerificationResult
    retrieval_notes: dict[str, object] = field(default_factory=dict)


class VerifiedQueryExecutionService:
    def __init__(
        self,
        *,
        router: QueryRouter | None = None,
        hybrid_pipeline: HybridRAGPipeline | None = None,
        graph_pipeline: GraphRAGPipeline | None = None,
        hyde_pipeline: HyDEPipeline | None = None,
        crag_validator: CRAGValidator | None = None,
        citation_resolver: CitationResolver | None = None,
        self_rag_verifier: SelfRAGVerifier | None = None,
        structured_answer_builder: StructuredAnswerBuilder | None = None,
    ) -> None:
        self.router = router or QueryRouter()
        self.hybrid_pipeline = hybrid_pipeline or HybridRAGPipeline(router=self.router)
        self.graph_pipeline = graph_pipeline or GraphRAGPipeline(
            router=self.router,
            hybrid_fallback=self.hybrid_pipeline,
        )
        self.hyde_pipeline = hyde_pipeline or HyDEPipeline(
            router=self.router,
            hybrid_pipeline=self.hybrid_pipeline,
        )
        self.crag_validator = crag_validator or CRAGValidator(router=self.router)
        self.placeholder_generator = PlaceholderOnlyGenerator()
        self.citation_resolver = citation_resolver or CitationResolver()
        self.self_rag_verifier = self_rag_verifier or SelfRAGVerifier()
        self.structured_answer_builder = (
            structured_answer_builder or StructuredAnswerBuilder()
        )

    def execute(
        self,
        session: Session,
        *,
        query: str,
        reference_date: date_value | None = None,
    ) -> VerifiedQueryExecutionResult:
        analysis = self.router.analyze(
            query,
            session=session,
            reference_date=reference_date,
        )
        retrieval_result = self._retrieve(session, query=query, analysis=analysis)
        generated_draft = self.placeholder_generator.generate(
            query,
            analysis,
            retrieval_result.crag_result.results,
        )
        resolved_draft = self.citation_resolver.resolve(session, generated_draft)
        verification_result = self.self_rag_verifier.verify(
            session,
            resolved_draft=resolved_draft,
        )
        structured_answer = self.structured_answer_builder.build(
            resolved_draft=resolved_draft,
            verification_result=verification_result,
        )
        return VerifiedQueryExecutionResult(
            analysis=analysis,
            pipeline=analysis.selected_pipeline.value,
            crag_result=retrieval_result.crag_result,
            generated_draft=generated_draft,
            resolved_draft=resolved_draft,
            verification_result=verification_result,
            structured_answer=structured_answer,
            retrieval_notes=retrieval_result.notes,
        )

    def _retrieve(
        self,
        session: Session,
        *,
        query: str,
        analysis: QueryAnalysis,
    ) -> _RetrievedBundle:
        if analysis.selected_pipeline is PipelineType.HYDE_HYBRID:
            hyde_result = self.hyde_pipeline.retrieve(
                session,
                query,
                analysis=analysis,
            )
            notes: dict[str, object] = {
                "used_hypothetical": hyde_result.used_hypothetical,
            }
            if hyde_result.fallback_reason is not None:
                notes["fallback_reason"] = hyde_result.fallback_reason
            if hyde_result.hypothetical is not None:
                notes["hypothetical_strategy"] = hyde_result.hypothetical.strategy
            return _RetrievedBundle(
                results=[
                    cast(RetrievedResult, result)
                    for result in hyde_result.crag_result.results
                ],
                crag_result=hyde_result.crag_result,
                notes=notes,
            )

        if analysis.selected_pipeline in {
            PipelineType.GRAPH_RAG,
            PipelineType.GRAPH_HYBRID,
        }:
            graph_results = self.graph_pipeline.retrieve(
                session,
                query,
                analysis=analysis,
            )
            def refine_with(
                refined_query: str,
                refined_analysis: QueryAnalysis,
            ) -> list[RetrievedResult]:
                if analysis.selected_pipeline is PipelineType.GRAPH_HYBRID:
                    return list(
                        self.hybrid_pipeline.retrieve(
                            session,
                            refined_query,
                            analysis=refined_analysis,
                        )
                    )
                return list(
                    self.graph_pipeline.retrieve(
                        session,
                        refined_query,
                        analysis=refined_analysis,
                    )
                )

            crag_result = self.crag_validator.validate(
                session,
                query,
                graph_results,
                analysis=analysis,
                refine_with=refine_with,
            )
            return _RetrievedBundle(
                results=[cast(RetrievedResult, result) for result in crag_result.results],
                crag_result=crag_result,
                notes={"graph_result_count": len(graph_results)},
            )

        hybrid_results = self.hybrid_pipeline.retrieve(
            session,
            query,
            analysis=analysis,
        )
        crag_result = self.crag_validator.validate(
            session,
            query,
            hybrid_results,
            analysis=analysis,
            refine_with=lambda refined_query, refined_analysis: list(
                self.hybrid_pipeline.retrieve(
                    session,
                    refined_query,
                    analysis=refined_analysis,
                )
            ),
        )
        return _RetrievedBundle(
            results=[cast(RetrievedResult, result) for result in crag_result.results],
            crag_result=crag_result,
            notes={"hybrid_result_count": len(hybrid_results)},
        )


@dataclass(slots=True, frozen=True)
class _RetrievedBundle:
    results: list[RetrievedResult]
    crag_result: CRAGResult
    notes: dict[str, object] = field(default_factory=dict)


verified_query_execution = VerifiedQueryExecutionService()
