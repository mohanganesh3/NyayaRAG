from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as date_value

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.embeddings import DeterministicBgeM3EmbeddingService
from app.ingestion.qdrant_collections import QdrantCollectionManager
from app.models import (
    DocumentChunk,
    LegalDocument,
    LegalDocumentType,
    ValidityStatus,
    VectorStoreCollection,
    VectorStorePoint,
)
from app.rag.lexical import (
    LegalSearchResult,
    LegalTokenizer,
    LexicalCorpusBuilder,
    LexicalRetriever,
)
from app.rag.router import QueryRouter
from app.schemas import PracticeArea, QueryAnalysis, QueryEntityType, QueryType


@dataclass(slots=True)
class DenseSearchResult:
    doc_id: str
    chunk_id: str
    score: float
    point: VectorStorePoint
    chunk: DocumentChunk
    document: LegalDocument


@dataclass(slots=True)
class HybridCandidate:
    doc_id: str
    chunk_id: str
    chunk: DocumentChunk
    document: LegalDocument
    lexical_score: float
    dense_score: float
    fused_score: float
    rerank_score: float = 0.0
    matched_terms: list[str] | None = None


@dataclass(slots=True)
class HybridSearchResult:
    doc_id: str
    chunk_id: str
    chunk: DocumentChunk
    document: LegalDocument
    lexical_score: float
    dense_score: float
    fused_score: float
    rerank_score: float
    authority_tier: int
    authority_class: str
    authority_label: str
    authority_reason: str
    matched_terms: list[str]


class DenseRetriever:
    def __init__(
        self,
        *,
        collection_manager: QdrantCollectionManager | None = None,
        embedding_service: DeterministicBgeM3EmbeddingService | None = None,
    ) -> None:
        self.collection_manager = collection_manager or QdrantCollectionManager()
        self.embedding_service = embedding_service or DeterministicBgeM3EmbeddingService()

    def search(
        self,
        session: Session,
        *,
        query: str,
        analysis: QueryAnalysis,
        top_k: int = 20,
    ) -> list[DenseSearchResult]:
        results: list[DenseSearchResult] = []
        for collection in self._target_collections(analysis):
            if session.get(VectorStoreCollection, collection) is None:
                continue

            query_filter = self._filter_for_collection(collection, analysis)
            points = self.collection_manager.filter_points(
                session,
                collection,
                query_filter,
            )
            if not points:
                continue

            query_vector = self.embedding_service.embed_texts([query])[0]
            rows = session.execute(
                select(VectorStorePoint, DocumentChunk, LegalDocument)
                .join(DocumentChunk, VectorStorePoint.chunk_id == DocumentChunk.chunk_id)
                .join(LegalDocument, VectorStorePoint.doc_id == LegalDocument.doc_id)
                .where(VectorStorePoint.point_id.in_([point.point_id for point in points]))
            ).all()
            for point, chunk, document in rows:
                score = self._cosine_similarity(query_vector, point.vector)
                results.append(
                    DenseSearchResult(
                        doc_id=document.doc_id,
                        chunk_id=chunk.chunk_id,
                        score=score,
                        point=point,
                        chunk=chunk,
                        document=document,
                    )
                )

        deduped = self._dedupe(results)
        return sorted(deduped, key=lambda item: item.score, reverse=True)[:top_k]

    def _target_collections(self, analysis: QueryAnalysis) -> list[str]:
        if analysis.query_type is QueryType.STATUTORY_LOOKUP:
            return [
                "statutes",
                "constitution",
                "sc_judgments",
                "hc_judgments",
                "tribunal_orders",
            ]
        if analysis.query_type is QueryType.CASE_SPECIFIC:
            return ["sc_judgments", "hc_judgments", "tribunal_orders"]
        return [
            "sc_judgments",
            "hc_judgments",
            "statutes",
            "constitution",
            "tribunal_orders",
            "lc_reports",
        ]

    def _filter_for_collection(
        self,
        collection: str,
        analysis: QueryAnalysis,
    ) -> dict[str, object]:
        must: list[dict[str, object]] = []
        should: list[dict[str, object]] = []

        if collection in {
            "sc_judgments",
            "hc_judgments",
            "statutes",
            "constitution",
            "tribunal_orders",
            "doctrine_clusters",
        }:
            must.append({"key": "current_validity", "match": {"value": "GOOD_LAW"}})

        if collection == "statutes":
            must.append({"key": "is_in_force", "match": {"value": True}})
            section_values = self._section_values(analysis)
            if section_values:
                should.append(
                    {"key": "section_number", "match": {"any": section_values}}
                )
        elif collection in {"sc_judgments", "hc_judgments", "tribunal_orders"}:
            if analysis.time_sensitive:
                must.append(
                    {
                        "key": "date",
                        "range": {"lte": analysis.reference_date.isoformat()},
                    }
                )
            should.append(
                {
                    "key": "jurisdiction_binding",
                    "match": {
                        "any": self._jurisdiction_values(analysis),
                    },
                }
            )

        if (
            analysis.practice_area is not PracticeArea.GENERAL
            and collection
            in {
                "sc_judgments",
                "hc_judgments",
                "tribunal_orders",
                "constitution",
                "lc_reports",
                "doctrine_clusters",
            }
        ):
            must.append(
                {
                    "key": "practice_area",
                    "match": {"any": [analysis.practice_area.value]},
                }
            )

        return {"must": must, "should": should}

    def _section_values(self, analysis: QueryAnalysis) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for reference in [*analysis.sections_mentioned, *analysis.bnss_equivalents]:
            parts = reference.split(" ")
            if len(parts) < 2:
                continue
            value = parts[-1].upper()
            if value not in seen:
                seen.add(value)
                values.append(value)
        return values

    def _jurisdiction_values(self, analysis: QueryAnalysis) -> list[str]:
        values = [analysis.jurisdiction_court, *analysis.jurisdiction_binding]
        if "All India" not in values:
            values.append("All India")
        return list(dict.fromkeys(values))

    def _dedupe(self, results: Sequence[DenseSearchResult]) -> list[DenseSearchResult]:
        deduped: dict[str, DenseSearchResult] = {}
        for result in results:
            existing = deduped.get(result.chunk_id)
            if existing is None or result.score > existing.score:
                deduped[result.chunk_id] = result
        return list(deduped.values())

    def _cosine_similarity(self, left: Sequence[float], right: Sequence[float]) -> float:
        limit = min(len(left), len(right))
        if limit == 0:
            return 0.0
        numerator = sum(left[index] * right[index] for index in range(limit))
        left_norm = math.sqrt(sum(left[index] * left[index] for index in range(limit)))
        right_norm = math.sqrt(sum(right[index] * right[index] for index in range(limit)))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        return numerator / (left_norm * right_norm)


class ReciprocalRankFusion:
    def fuse(
        self,
        lexical_results: Sequence[LegalSearchResult],
        dense_results: Sequence[DenseSearchResult],
        *,
        k: int = 60,
        top_k: int = 30,
    ) -> list[HybridCandidate]:
        scores: dict[str, float] = {}
        lexical_lookup = {result.chunk_id: result for result in lexical_results}
        dense_lookup = {result.chunk_id: result for result in dense_results}

        for rank, result in enumerate(lexical_results):
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / (k + rank + 1)

        for rank, dense_result in enumerate(dense_results):
            scores[dense_result.chunk_id] = (
                scores.get(dense_result.chunk_id, 0.0) + 1.0 / (k + rank + 1)
            )

        candidates: list[HybridCandidate] = []
        for chunk_id, fused_score in sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:top_k]:
            if chunk_id in dense_lookup:
                dense = dense_lookup[chunk_id]
                lexical = lexical_lookup.get(chunk_id)
                candidates.append(
                    HybridCandidate(
                        doc_id=dense.doc_id,
                        chunk_id=chunk_id,
                        chunk=dense.chunk,
                        document=dense.document,
                        lexical_score=lexical.score if lexical is not None else 0.0,
                        dense_score=dense.score,
                        fused_score=fused_score,
                        matched_terms=lexical.matched_terms if lexical is not None else [],
                    )
                )
                continue

            lexical = lexical_lookup[chunk_id]
            lexical_doc_type = self._lexical_doc_type(lexical)
            candidates.append(
                HybridCandidate(
                    doc_id=lexical.doc_id,
                    chunk_id=chunk_id,
                    chunk=DocumentChunk(
                        chunk_id=lexical.chunk_id,
                        doc_id=lexical.doc_id,
                        doc_type=lexical_doc_type,
                        text=lexical.document.text,
                        chunk_index=0,
                        total_chunks=1,
                        section_header=lexical.document.section_header,
                        court=lexical.document.court,
                        citation=lexical.document.citation,
                        jurisdiction_binding=[],
                        jurisdiction_persuasive=[],
                        practice_area=lexical.document.practice_areas,
                    ),
                    document=LegalDocument(
                        doc_id=lexical.doc_id,
                        doc_type=lexical_doc_type,
                        court=lexical.document.court,
                        bench=[],
                        parties=lexical.document.parties,
                        jurisdiction_binding=[],
                        jurisdiction_persuasive=[],
                        current_validity=ValidityStatus.GOOD_LAW,
                        practice_areas=lexical.document.practice_areas,
                        language="en",
                    ),
                    lexical_score=lexical.score,
                    dense_score=0.0,
                    fused_score=fused_score,
                    matched_terms=lexical.matched_terms,
                )
            )
        return candidates

    def _lexical_doc_type(self, lexical_result: LegalSearchResult) -> LegalDocumentType:
        raw_doc_type = lexical_result.document.attributes.get("doc_type", "judgment")
        if isinstance(raw_doc_type, str):
            return LegalDocumentType(raw_doc_type)
        return LegalDocumentType.JUDGMENT


class DeterministicLegalCrossEncoder:
    def __init__(self, *, tokenizer: LegalTokenizer | None = None) -> None:
        self.tokenizer = tokenizer or LegalTokenizer()

    def rerank(
        self,
        query: str,
        analysis: QueryAnalysis,
        candidates: Sequence[HybridCandidate],
        *,
        top_k: int = 8,
    ) -> list[HybridCandidate]:
        query_tokens = set(self.tokenizer.tokenize(query))
        query_case_names = [
            entity.text.lower()
            for entity in analysis.entities
            if entity.entity_type is QueryEntityType.CASE_NAME
        ]
        section_targets = self._section_targets(analysis)

        reranked: list[HybridCandidate] = []
        for candidate in candidates:
            candidate_tokens = set(self.tokenizer.tokenize(candidate.chunk.text))
            overlap = len(query_tokens & candidate_tokens) / max(len(query_tokens), 1)
            dense_component = (candidate.dense_score + 1.0) / 2.0 if candidate.dense_score else 0.0
            lexical_component = (
                min(candidate.lexical_score / 6.0, 1.0) if candidate.lexical_score else 0.0
            )
            exact_case_bonus = self._case_bonus(candidate, query_case_names)
            section_bonus = self._section_bonus(candidate, section_targets)
            document_type_bonus = self._document_type_bonus(candidate, analysis)
            practice_bonus = self._practice_bonus(candidate, analysis)
            score = (
                0.35 * overlap
                + 0.30 * dense_component
                + 0.20 * lexical_component
                + exact_case_bonus
                + section_bonus
                + document_type_bonus
                + practice_bonus
            )
            candidate.rerank_score = min(score, 1.0)
            reranked.append(candidate)

        reranked.sort(key=lambda item: item.rerank_score, reverse=True)
        return reranked[:top_k]

    def _section_targets(self, analysis: QueryAnalysis) -> set[str]:
        targets: set[str] = set()
        for reference in [*analysis.sections_mentioned, *analysis.bnss_equivalents]:
            parts = reference.split(" ")
            if len(parts) >= 2:
                targets.add(parts[-1].upper())
        return targets

    def _case_bonus(self, candidate: HybridCandidate, query_case_names: list[str]) -> float:
        if not query_case_names:
            return 0.0
        parties = candidate.document.parties
        title = " ".join(
            part for part in [parties.get("appellant"), "v", parties.get("respondent")] if part
        ).lower()
        if any(case_name in title for case_name in query_case_names):
            return 0.12
        return 0.0

    def _section_bonus(self, candidate: HybridCandidate, section_targets: set[str]) -> float:
        if not section_targets or candidate.chunk.section_number is None:
            return 0.0
        if candidate.chunk.section_number.upper() in section_targets:
            return 0.22
        return 0.0

    def _document_type_bonus(
        self,
        candidate: HybridCandidate,
        analysis: QueryAnalysis,
    ) -> float:
        if (
            analysis.query_type is QueryType.STATUTORY_LOOKUP
            and candidate.document.doc_type
            in {LegalDocumentType.STATUTE, LegalDocumentType.CONSTITUTION}
        ):
            return 0.18
        return 0.0

    def _practice_bonus(self, candidate: HybridCandidate, analysis: QueryAnalysis) -> float:
        if analysis.practice_area is PracticeArea.GENERAL:
            return 0.0
        if analysis.practice_area.value in candidate.chunk.practice_area:
            return 0.05
        if analysis.practice_area.value in candidate.document.practice_areas:
            return 0.05
        return 0.0


class AuthorityRanker:
    def rank(
        self,
        candidates: Sequence[HybridCandidate],
        analysis: QueryAnalysis,
        *,
        top_binding: int = 5,
        top_persuasive: int = 3,
    ) -> list[HybridSearchResult]:
        results = [
            self._to_result(candidate, analysis)
            for candidate in candidates
            if candidate.document.current_validity is ValidityStatus.GOOD_LAW
        ]
        results.sort(key=self._sort_key)

        binding = [result for result in results if result.authority_class == "binding"][
            :top_binding
        ]
        persuasive = [
            result for result in results if result.authority_class == "persuasive"
        ][:top_persuasive]

        ordered = binding + persuasive
        if len(ordered) < min(len(results), top_binding + top_persuasive):
            chosen = {result.chunk_id for result in ordered}
            for result in results:
                if result.chunk_id in chosen:
                    continue
                ordered.append(result)
                chosen.add(result.chunk_id)
        return ordered

    def _sort_key(self, result: HybridSearchResult) -> tuple[int, int, float]:
        tier_bucket = -int(result.rerank_score / 0.05)
        return (tier_bucket, result.authority_tier, -result.rerank_score)

    def _to_result(
        self,
        candidate: HybridCandidate,
        analysis: QueryAnalysis,
    ) -> HybridSearchResult:
        authority_tier, authority_class, authority_label, authority_reason = (
            self._authority_metadata(candidate, analysis)
        )
        return HybridSearchResult(
            doc_id=candidate.doc_id,
            chunk_id=candidate.chunk_id,
            chunk=candidate.chunk,
            document=candidate.document,
            lexical_score=candidate.lexical_score,
            dense_score=candidate.dense_score,
            fused_score=candidate.fused_score,
            rerank_score=candidate.rerank_score,
            authority_tier=authority_tier,
            authority_class=authority_class,
            authority_label=authority_label,
            authority_reason=authority_reason,
            matched_terms=candidate.matched_terms or [],
        )

    def _authority_metadata(
        self,
        candidate: HybridCandidate,
        analysis: QueryAnalysis,
    ) -> tuple[int, str, str, str]:
        if candidate.document.doc_type in {
            LegalDocumentType.STATUTE,
            LegalDocumentType.CONSTITUTION,
        }:
            return (0, "binding", "binding", "Current statutory or constitutional text.")

        court = (candidate.document.court or "").strip()
        normalized_court = court.lower()
        bench_size = candidate.document.coram or len(candidate.document.bench)

        if normalized_court in {"supreme court", "supreme court of india"}:
            if bench_size >= 9:
                return (1, "binding", "binding", "Supreme Court 9-judge bench.")
            if bench_size >= 5:
                return (2, "binding", "binding", "Supreme Court Constitution Bench.")
            if bench_size >= 3:
                return (3, "binding", "binding", "Supreme Court 3-judge bench.")
            if bench_size >= 2:
                return (4, "binding", "binding", "Supreme Court Division Bench.")
            return (5, "binding", "binding", "Supreme Court single-judge authority.")

        if court == analysis.jurisdiction_court:
            if bench_size >= 3:
                return (6, "binding", "binding", f"{court} larger bench authority.")
            if bench_size >= 2:
                return (7, "binding", "binding", f"{court} Division Bench authority.")
            return (8, "binding", "binding", f"{court} single-judge authority.")

        if "high court" in normalized_court:
            return (9, "persuasive", "persuasive", f"{court} persuasive in this jurisdiction.")

        return (10, "persuasive", "persuasive", "Tribunal or other persuasive authority.")


class HybridRAGPipeline:
    def __init__(
        self,
        *,
        corpus_builder: LexicalCorpusBuilder | None = None,
        dense_retriever: DenseRetriever | None = None,
        fuser: ReciprocalRankFusion | None = None,
        reranker: DeterministicLegalCrossEncoder | None = None,
        authority_ranker: AuthorityRanker | None = None,
        router: QueryRouter | None = None,
    ) -> None:
        self.corpus_builder = corpus_builder or LexicalCorpusBuilder()
        self.dense_retriever = dense_retriever or DenseRetriever()
        self.fuser = fuser or ReciprocalRankFusion()
        self.reranker = reranker or DeterministicLegalCrossEncoder()
        self.authority_ranker = authority_ranker or AuthorityRanker()
        self.router = router or QueryRouter()

    def retrieve(
        self,
        session: Session,
        query: str,
        *,
        analysis: QueryAnalysis | None = None,
        reference_date: date_value | None = None,
    ) -> list[HybridSearchResult]:
        active_analysis = analysis or self.router.analyze(
            query,
            session=session,
            reference_date=reference_date,
        )
        lexical_documents = self.corpus_builder.build_from_session(session)
        lexical_retriever = LexicalRetriever(lexical_documents)
        lexical_results = lexical_retriever.search(
            query,
            top_k=20,
            session=session,
            reference_date=active_analysis.reference_date,
        )
        dense_results = self.dense_retriever.search(
            session,
            query=query,
            analysis=active_analysis,
            top_k=20,
        )
        fused = self.fuser.fuse(lexical_results, dense_results, top_k=30)
        reranked = self.reranker.rerank(
            query,
            active_analysis,
            fused,
            top_k=8,
        )
        return self.authority_ranker.rank(reranked, active_analysis)
