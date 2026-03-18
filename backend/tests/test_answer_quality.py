from __future__ import annotations

import pytest
from app.evaluation import AnswerQualityCase, AnswerQualitySuite


def test_answer_quality_suite_scores_exact_supported_answer_at_ceiling() -> None:
    suite = AnswerQualitySuite()
    run = suite.run(
        (
            AnswerQualityCase(
                case_id="privacy_exact",
                query="Is privacy a fundamental right under Article 21?",
                answer="Privacy is a fundamental right under Article 21.",
                reference_answer="Privacy is a fundamental right under Article 21.",
                contexts=("Privacy is a fundamental right under Article 21.",),
                reference_entities=("privacy", "article 21"),
            ),
        )
    )

    metrics = run.cases[0].metrics
    assert metrics.bert_score_f1 == pytest.approx(1.0)
    assert metrics.rouge_l == pytest.approx(1.0)
    assert metrics.meteor == pytest.approx(1.0)
    assert metrics.faithfulness == pytest.approx(1.0)
    assert metrics.context_precision == pytest.approx(1.0)
    assert metrics.context_recall == pytest.approx(1.0)
    assert metrics.context_entity_recall == pytest.approx(1.0)
    assert metrics.hallucination_score == pytest.approx(0.0)
    assert metrics.contextual_precision == pytest.approx(1.0)
    assert metrics.contextual_recall == pytest.approx(1.0)
    assert metrics.g_eval_legal_accuracy == pytest.approx(1.0)
    assert metrics.noise_robustness == pytest.approx(1.0)


def test_answer_quality_suite_penalizes_partial_hallucination_and_summarizes() -> None:
    suite = AnswerQualitySuite()
    cases = (
        AnswerQualityCase(
            case_id="privacy_exact",
            query="Is privacy a fundamental right under Article 21?",
            answer="Privacy is a fundamental right under Article 21.",
            reference_answer="Privacy is a fundamental right under Article 21.",
            contexts=("Privacy is a fundamental right under Article 21.",),
            reference_entities=("privacy", "article 21"),
        ),
        AnswerQualityCase(
            case_id="privacy_partial_hallucination",
            query="What is the rule on privacy under Article 21?",
            answer=(
                "Privacy is a fundamental right under Article 21. "
                "It abolishes preventive detention entirely."
            ),
            reference_answer="Privacy is a fundamental right under Article 21.",
            contexts=("Privacy is a fundamental right under Article 21.",),
            noisy_contexts=("A tax tribunal discussed depreciation on plant and machinery.",),
            reference_entities=("privacy", "article 21"),
        ),
    )

    run = suite.run(cases)
    exact_metrics = run.cases[0].metrics
    partial_metrics = run.cases[1].metrics

    assert partial_metrics.bert_score_f1 < exact_metrics.bert_score_f1
    assert partial_metrics.rouge_l < exact_metrics.rouge_l
    assert partial_metrics.meteor < exact_metrics.meteor
    assert partial_metrics.faithfulness == pytest.approx(0.5)
    assert partial_metrics.hallucination_score == pytest.approx(0.5)
    assert partial_metrics.context_recall == pytest.approx(1.0)
    assert partial_metrics.noise_robustness < 1.0

    assert run.summary.faithfulness == pytest.approx(0.75)
    assert run.summary.hallucination_score == pytest.approx(0.25)
