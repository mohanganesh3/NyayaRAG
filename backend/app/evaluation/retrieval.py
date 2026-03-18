from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from statistics import fmean
from typing import Protocol


class RetrievalResultLike(Protocol):
    doc_id: str
    chunk_id: str


RetrieverFn = Callable[["RetrievalBenchmarkCase"], Sequence[RetrievalResultLike]]


@dataclass(slots=True, frozen=True)
class RetrievalBenchmarkCase:
    case_id: str
    query: str
    relevant_chunk_ids: tuple[str, ...]
    graded_relevance: dict[str, int] = field(default_factory=dict)

    def relevance_for(self, chunk_id: str) -> int:
        if self.graded_relevance:
            return self.graded_relevance.get(chunk_id, 0)
        return 1 if chunk_id in self.relevant_chunk_ids else 0


@dataclass(slots=True, frozen=True)
class RetrievalCaseMetrics:
    precision_at: dict[int, float]
    recall_at: dict[int, float]
    reciprocal_rank: float
    ndcg_at: dict[int, float]
    average_precision: float


@dataclass(slots=True, frozen=True)
class RetrievalCaseResult:
    case: RetrievalBenchmarkCase
    ranked_chunk_ids: tuple[str, ...]
    metrics: RetrievalCaseMetrics


@dataclass(slots=True, frozen=True)
class RetrievalMetricSummary:
    precision_at: dict[int, float]
    recall_at: dict[int, float]
    mrr: float
    ndcg_at: dict[int, float]
    map_score: float


@dataclass(slots=True, frozen=True)
class RetrievalBenchmarkRun:
    cases: tuple[RetrievalCaseResult, ...]
    summary: RetrievalMetricSummary


class RetrievalBenchmarkSuite:
    def __init__(self, *, ks: Sequence[int] = (1, 3, 5, 10)) -> None:
        normalized = tuple(sorted({int(k) for k in ks if int(k) > 0}))
        if not normalized:
            raise ValueError("At least one positive K value is required.")
        self.ks = normalized

    def run(
        self,
        cases: Sequence[RetrievalBenchmarkCase],
        *,
        retrieve: RetrieverFn,
    ) -> RetrievalBenchmarkRun:
        case_results = tuple(
            self._evaluate_case(case, retrieve(case))
            for case in cases
        )
        return RetrievalBenchmarkRun(
            cases=case_results,
            summary=self._summarize(case_results),
        )

    def _evaluate_case(
        self,
        case: RetrievalBenchmarkCase,
        retrieved: Sequence[RetrievalResultLike],
    ) -> RetrievalCaseResult:
        ranked_chunk_ids = self._dedupe_ranked_chunk_ids(retrieved)
        relevant_ids = set(case.relevant_chunk_ids)

        precision_at: dict[int, float] = {}
        recall_at: dict[int, float] = {}
        ndcg_at: dict[int, float] = {}

        for k in self.ks:
            top_k = ranked_chunk_ids[:k]
            relevant_in_top_k = sum(1 for chunk_id in top_k if chunk_id in relevant_ids)
            precision_at[k] = relevant_in_top_k / k
            recall_at[k] = relevant_in_top_k / max(len(relevant_ids), 1)
            ndcg_at[k] = self._ndcg_at(case, top_k, k)

        reciprocal_rank = 0.0
        for index, chunk_id in enumerate(ranked_chunk_ids, start=1):
            if chunk_id in relevant_ids:
                reciprocal_rank = 1.0 / index
                break

        average_precision = self._average_precision(case, ranked_chunk_ids)
        metrics = RetrievalCaseMetrics(
            precision_at=precision_at,
            recall_at=recall_at,
            reciprocal_rank=reciprocal_rank,
            ndcg_at=ndcg_at,
            average_precision=average_precision,
        )
        return RetrievalCaseResult(
            case=case,
            ranked_chunk_ids=tuple(ranked_chunk_ids),
            metrics=metrics,
        )

    def _summarize(
        self,
        case_results: Sequence[RetrievalCaseResult],
    ) -> RetrievalMetricSummary:
        if not case_results:
            zeroes = {k: 0.0 for k in self.ks}
            return RetrievalMetricSummary(
                precision_at=zeroes,
                recall_at=zeroes,
                mrr=0.0,
                ndcg_at=zeroes,
                map_score=0.0,
            )

        precision_at = {
            k: fmean(result.metrics.precision_at[k] for result in case_results)
            for k in self.ks
        }
        recall_at = {
            k: fmean(result.metrics.recall_at[k] for result in case_results)
            for k in self.ks
        }
        ndcg_at = {
            k: fmean(result.metrics.ndcg_at[k] for result in case_results)
            for k in self.ks
        }
        return RetrievalMetricSummary(
            precision_at=precision_at,
            recall_at=recall_at,
            mrr=fmean(result.metrics.reciprocal_rank for result in case_results),
            ndcg_at=ndcg_at,
            map_score=fmean(result.metrics.average_precision for result in case_results),
        )

    def _dedupe_ranked_chunk_ids(
        self,
        retrieved: Sequence[RetrievalResultLike],
    ) -> list[str]:
        ranked: list[str] = []
        seen: set[str] = set()
        for result in retrieved:
            if result.chunk_id in seen:
                continue
            seen.add(result.chunk_id)
            ranked.append(result.chunk_id)
        return ranked

    def _average_precision(
        self,
        case: RetrievalBenchmarkCase,
        ranked_chunk_ids: Sequence[str],
    ) -> float:
        relevant_ids = set(case.relevant_chunk_ids)
        if not relevant_ids:
            return 0.0

        hits = 0
        cumulative_precision = 0.0
        for index, chunk_id in enumerate(ranked_chunk_ids, start=1):
            if chunk_id not in relevant_ids:
                continue
            hits += 1
            cumulative_precision += hits / index
        if hits == 0:
            return 0.0
        return cumulative_precision / len(relevant_ids)

    def _ndcg_at(
        self,
        case: RetrievalBenchmarkCase,
        top_k: Sequence[str],
        k: int,
    ) -> float:
        dcg = 0.0
        for index, chunk_id in enumerate(top_k, start=1):
            relevance = case.relevance_for(chunk_id)
            if relevance == 0:
                continue
            dcg += (2**relevance - 1) / math.log2(index + 1)

        ideal_relevances = sorted(
            (case.relevance_for(chunk_id) for chunk_id in case.relevant_chunk_ids),
            reverse=True,
        )[:k]
        if not ideal_relevances:
            return 0.0

        idcg = sum(
            (2**relevance - 1) / math.log2(index + 1)
            for index, relevance in enumerate(ideal_relevances, start=1)
        )
        if idcg == 0.0:
            return 0.0
        return dcg / idcg
