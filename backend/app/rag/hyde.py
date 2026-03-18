from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as date_value

from sqlalchemy.orm import Session

from app.models import LegalDocumentType
from app.rag.crag import CRAGResult, CRAGValidator
from app.rag.hybrid import (
    AuthorityRanker,
    DenseRetriever,
    DeterministicLegalCrossEncoder,
    HybridCandidate,
    HybridRAGPipeline,
    HybridSearchResult,
    ReciprocalRankFusion,
)
from app.rag.lexical import LegalTokenizer, LexicalCorpusBuilder, LexicalRetriever
from app.rag.router import QueryRouter
from app.schemas import PracticeArea, QueryAnalysis


@dataclass(slots=True)
class HypotheticalDraft:
    text: str
    quality_score: float
    anchors: list[str]
    strategy: str


@dataclass(slots=True)
class HyDEResult:
    hypothetical: HypotheticalDraft | None
    used_hypothetical: bool
    fallback_reason: str | None
    crag_result: CRAGResult


class HypotheticalGenerator(ABC):
    @abstractmethod
    def generate(
        self,
        query: str,
        analysis: QueryAnalysis,
    ) -> HypotheticalDraft: ...


class DeterministicHypotheticalGenerator(HypotheticalGenerator):
    def generate(
        self,
        query: str,
        analysis: QueryAnalysis,
    ) -> HypotheticalDraft:
        lowered = query.lower()

        if self._is_landlord_dispossession_query(lowered, analysis):
            return HypotheticalDraft(
                text=(
                    "Where a tenant or person in settled possession is dispossessed "
                    "otherwise than in due course of law, Section 6 of the Specific "
                    "Relief Act, 1963 permits recovery of possession. Courts treat "
                    "lock-outs, forcible eviction, and self-help dispossession by a "
                    "landlord as illegal. The proper remedy includes restoration of "
                    "possession, mandatory injunction, and proceedings grounded in due "
                    "process rather than unilateral eviction."
                ),
                quality_score=0.94,
                anchors=[
                    "Section 6 Specific Relief Act",
                    "illegal dispossession",
                    "restoration of possession",
                    "mandatory injunction",
                ],
                strategy="property_dispossession",
            )

        if self._is_bail_query(lowered, analysis):
            return HypotheticalDraft(
                text=(
                    "In considering bail for a non-bailable offence, the Court must "
                    "weigh liberty, flight risk, tampering with evidence, and the "
                    "gravity of the accusation. BNSS 480 and BNSS 482 govern regular "
                    "and anticipatory bail. Indian courts have repeatedly held that "
                    "bail is the rule and jail is the exception, subject to the facts "
                    "of the accusation and the stage of investigation."
                ),
                quality_score=0.89,
                anchors=[
                    "BNSS 480",
                    "BNSS 482",
                    "bail is the rule",
                    "non-bailable offence",
                ],
                strategy="criminal_bail",
            )

        if self._is_labour_termination_query(lowered, analysis):
            return HypotheticalDraft(
                text=(
                    "Termination of service without domestic enquiry, notice, or "
                    "compliance with principles of natural justice may be set aside. "
                    "Courts examine whether the employee was a workman, whether "
                    "Industrial Disputes Act safeguards were followed, and whether "
                    "back wages, reinstatement, or compensation are appropriate on the "
                    "facts of the dismissal."
                ),
                quality_score=0.83,
                anchors=[
                    "Industrial Disputes Act",
                    "domestic enquiry",
                    "natural justice",
                    "reinstatement",
                ],
                strategy="labour_termination",
            )

        generic_anchor = analysis.practice_area.value.replace("_", " ")
        return HypotheticalDraft(
            text=(
                "The Court considered the dispute in light of the applicable Indian "
                f"{generic_anchor} principles, but the fact pattern lacks enough legal "
                "anchors to safely synthesize a focused hypothetical judgment."
            ),
            quality_score=0.38,
            anchors=[],
            strategy="generic_low_confidence",
        )

    def _is_landlord_dispossession_query(
        self,
        lowered: str,
        analysis: QueryAnalysis,
    ) -> bool:
        property_signals = ("landlord", "tenant", "rent", "locks", "locked", "evict", "possession")
        return analysis.practice_area is PracticeArea.PROPERTY and any(
            signal in lowered for signal in property_signals
        )

    def _is_bail_query(
        self,
        lowered: str,
        analysis: QueryAnalysis,
    ) -> bool:
        bail_signals = ("bail", "anticipatory", "arrest", "fir", "charge sheet")
        return analysis.practice_area is PracticeArea.CRIMINAL and any(
            signal in lowered for signal in bail_signals
        )

    def _is_labour_termination_query(
        self,
        lowered: str,
        analysis: QueryAnalysis,
    ) -> bool:
        labour_signals = ("dismiss", "termination", "salary", "workman", "suspension")
        return analysis.practice_area is PracticeArea.LABOUR and any(
            signal in lowered for signal in labour_signals
        )


class HyDEPipeline:
    def __init__(
        self,
        *,
        generator: HypotheticalGenerator | None = None,
        hybrid_pipeline: HybridRAGPipeline | None = None,
        corpus_builder: LexicalCorpusBuilder | None = None,
        dense_retriever: DenseRetriever | None = None,
        fuser: ReciprocalRankFusion | None = None,
        reranker: DeterministicLegalCrossEncoder | None = None,
        authority_ranker: AuthorityRanker | None = None,
        crag_validator: CRAGValidator | None = None,
        router: QueryRouter | None = None,
        tokenizer: LegalTokenizer | None = None,
        minimum_quality_score: float = 0.6,
    ) -> None:
        self.generator = generator or DeterministicHypotheticalGenerator()
        self.hybrid_pipeline = hybrid_pipeline or HybridRAGPipeline()
        self.corpus_builder = corpus_builder or self.hybrid_pipeline.corpus_builder
        self.dense_retriever = dense_retriever or self.hybrid_pipeline.dense_retriever
        self.fuser = fuser or self.hybrid_pipeline.fuser
        self.reranker = reranker or self.hybrid_pipeline.reranker
        self.authority_ranker = authority_ranker or self.hybrid_pipeline.authority_ranker
        self.router = router or self.hybrid_pipeline.router or QueryRouter()
        self.crag_validator = crag_validator or CRAGValidator(router=self.router)
        self.tokenizer = tokenizer or LegalTokenizer()
        self.minimum_quality_score = minimum_quality_score

    def retrieve(
        self,
        session: Session,
        query: str,
        *,
        analysis: QueryAnalysis | None = None,
        reference_date: date_value | None = None,
    ) -> HyDEResult:
        active_analysis = analysis or self.router.analyze(
            query,
            session=session,
            reference_date=reference_date,
        )
        hypothetical = self.generator.generate(query, active_analysis)
        if hypothetical.quality_score < self.minimum_quality_score:
            return self._fallback(
                session,
                query,
                active_analysis,
                hypothetical=hypothetical,
                reason="HyDE fallback - low hypothetical confidence",
            )

        lexical_documents = self.corpus_builder.build_from_session(session)
        lexical_results = LexicalRetriever(lexical_documents).search(
            query,
            top_k=10,
            session=session,
            reference_date=active_analysis.reference_date,
        )
        dense_results = self.dense_retriever.search(
            session,
            query=hypothetical.text,
            analysis=active_analysis,
            top_k=20,
        )
        if not dense_results:
            return self._fallback(
                session,
                query,
                active_analysis,
                hypothetical=hypothetical,
                reason="HyDE fallback - no dense candidates from hypothetical anchor",
            )

        fused = self.fuser.fuse(
            lexical_results,
            dense_results,
            top_k=30,
        )
        reranked = self.reranker.rerank(
            query,
            active_analysis,
            fused,
            top_k=8,
        )
        boosted = self._apply_hypothetical_anchor_boost(reranked, hypothetical)
        ranked = self.authority_ranker.rank(boosted, active_analysis)
        crag_result = self.crag_validator.validate(
            session,
            query,
            ranked,
            analysis=active_analysis,
            refine_with=lambda refined_query, refined_analysis: self.hybrid_pipeline.retrieve(
                session,
                refined_query,
                analysis=refined_analysis,
            ),
        )
        return HyDEResult(
            hypothetical=hypothetical,
            used_hypothetical=True,
            fallback_reason=None,
            crag_result=crag_result,
        )

    def _fallback(
        self,
        session: Session,
        query: str,
        analysis: QueryAnalysis,
        *,
        hypothetical: HypotheticalDraft,
        reason: str,
    ) -> HyDEResult:
        baseline_results = self.hybrid_pipeline.retrieve(
            session,
            query,
            analysis=analysis,
        )
        crag_result = self.crag_validator.validate(
            session,
            query,
            baseline_results,
            analysis=analysis,
            refine_with=lambda refined_query, refined_analysis: self.hybrid_pipeline.retrieve(
                session,
                refined_query,
                analysis=refined_analysis,
            ),
        )
        return HyDEResult(
            hypothetical=hypothetical,
            used_hypothetical=False,
            fallback_reason=reason,
            crag_result=crag_result,
        )

    def baseline_retrieve(
        self,
        session: Session,
        query: str,
        *,
        analysis: QueryAnalysis | None = None,
        reference_date: date_value | None = None,
    ) -> list[HybridSearchResult]:
        return self.hybrid_pipeline.retrieve(
            session,
            query,
            analysis=analysis,
            reference_date=reference_date,
        )

    def _apply_hypothetical_anchor_boost(
        self,
        candidates: Sequence[HybridCandidate],
        hypothetical: HypotheticalDraft,
    ) -> list[HybridCandidate]:
        anchor_tokens: set[str] = set()
        for anchor in [hypothetical.text, *hypothetical.anchors]:
            anchor_tokens.update(self.tokenizer.tokenize(anchor))

        boosted: list[HybridCandidate] = []
        for candidate in candidates:
            candidate_tokens = set(self.tokenizer.tokenize(candidate.chunk.text))
            overlap = len(anchor_tokens & candidate_tokens) / max(len(anchor_tokens), 1)
            phrase_bonus = 0.0
            lowered_text = candidate.chunk.text.lower()
            for anchor in hypothetical.anchors:
                normalized_anchor = anchor.lower()
                if normalized_anchor in lowered_text:
                    phrase_bonus += 0.06
            if candidate.document.doc_type in {
                LegalDocumentType.STATUTE,
                LegalDocumentType.CONSTITUTION,
            }:
                phrase_bonus += 0.04

            candidate.rerank_score = min(
                candidate.rerank_score + (0.8 * overlap) + phrase_bonus,
                1.0,
            )
            boosted.append(candidate)

        boosted.sort(key=lambda item: item.rerank_score, reverse=True)
        return boosted
