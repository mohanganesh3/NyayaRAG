from __future__ import annotations

import math
from dataclasses import dataclass

import pytest
from app.evaluation import RetrievalBenchmarkCase, RetrievalBenchmarkSuite


@dataclass(slots=True, frozen=True)
class _Result:
    doc_id: str
    chunk_id: str


def test_retrieval_benchmark_suite_computes_macro_ir_metrics() -> None:
    suite = RetrievalBenchmarkSuite(ks=(1, 3))
    cases = (
        RetrievalBenchmarkCase(
            case_id="privacy",
            query="How has privacy developed in India?",
            relevant_chunk_ids=("chunk-a", "chunk-c"),
        ),
        RetrievalBenchmarkCase(
            case_id="bail",
            query="What is the rule for bail?",
            relevant_chunk_ids=("chunk-y",),
        ),
    )
    ranked_results = {
        "privacy": (
            _Result(doc_id="doc-a", chunk_id="chunk-a"),
            _Result(doc_id="doc-b", chunk_id="chunk-b"),
            _Result(doc_id="doc-c", chunk_id="chunk-c"),
        ),
        "bail": (
            _Result(doc_id="doc-x", chunk_id="chunk-x"),
            _Result(doc_id="doc-y", chunk_id="chunk-y"),
            _Result(doc_id="doc-z", chunk_id="chunk-z"),
        ),
    }

    run = suite.run(
        cases,
        retrieve=lambda case: ranked_results[case.case_id],
    )

    assert run.summary.precision_at[1] == pytest.approx(0.5)
    assert run.summary.recall_at[1] == pytest.approx(0.25)
    assert run.summary.precision_at[3] == pytest.approx(0.5)
    assert run.summary.recall_at[3] == pytest.approx(1.0)
    assert run.summary.mrr == pytest.approx(0.75)
    assert run.summary.map_score == pytest.approx(2 / 3)
    assert run.summary.ndcg_at[3] == pytest.approx(0.7753252713598225)


def test_retrieval_benchmark_suite_uses_graded_relevance_and_dedupes_rankings() -> None:
    suite = RetrievalBenchmarkSuite(ks=(1, 3))
    case = RetrievalBenchmarkCase(
        case_id="graded",
        query="What are the most authoritative privacy cases?",
        relevant_chunk_ids=("chunk-a", "chunk-b", "chunk-c"),
        graded_relevance={"chunk-a": 3, "chunk-b": 2, "chunk-c": 1},
    )
    retrieved = (
        _Result(doc_id="doc-b", chunk_id="chunk-b"),
        _Result(doc_id="doc-b", chunk_id="chunk-b"),
        _Result(doc_id="doc-a", chunk_id="chunk-a"),
        _Result(doc_id="doc-d", chunk_id="chunk-d"),
        _Result(doc_id="doc-c", chunk_id="chunk-c"),
    )

    run = suite.run((case,), retrieve=lambda _case: retrieved)
    case_result = run.cases[0]

    assert case_result.ranked_chunk_ids == ("chunk-b", "chunk-a", "chunk-d", "chunk-c")
    assert case_result.metrics.precision_at[1] == pytest.approx(1.0)
    assert case_result.metrics.recall_at[3] == pytest.approx(2 / 3)
    assert case_result.metrics.reciprocal_rank == pytest.approx(1.0)
    assert case_result.metrics.average_precision == pytest.approx((1.0 + 1.0 + 0.75) / 3)

    expected_dcg = ((2**2 - 1) / math.log2(2)) + ((2**3 - 1) / math.log2(3))
    expected_idcg = (
        ((2**3 - 1) / math.log2(2))
        + ((2**2 - 1) / math.log2(3))
        + ((2**1 - 1) / math.log2(4))
    )
    assert case_result.metrics.ndcg_at[3] == pytest.approx(expected_dcg / expected_idcg)
