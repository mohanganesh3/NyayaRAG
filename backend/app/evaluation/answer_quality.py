from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from app.ingestion.embeddings import DeterministicBgeM3EmbeddingService

_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "with",
}


@dataclass(slots=True, frozen=True)
class AnswerQualityCase:
    case_id: str
    query: str
    answer: str
    reference_answer: str
    contexts: tuple[str, ...]
    noisy_contexts: tuple[str, ...] = ()
    reference_entities: tuple[str, ...] = ()
    reference_contexts: tuple[str, ...] = ()

    @property
    def retrieved_contexts(self) -> tuple[str, ...]:
        return self.contexts

    @property
    def expected_entities(self) -> tuple[str, ...]:
        return self.reference_entities


def AnswerQualityBenchmarkCase(
    *,
    case_id: str,
    query: str,
    answer: str,
    reference_answer: str,
    retrieved_contexts: tuple[str, ...],
    reference_contexts: tuple[str, ...] = (),
    expected_entities: tuple[str, ...] = (),
    noisy_contexts: tuple[str, ...] = (),
) -> AnswerQualityCase:
    return AnswerQualityCase(
        case_id=case_id,
        query=query,
        answer=answer,
        reference_answer=reference_answer,
        contexts=retrieved_contexts,
        noisy_contexts=noisy_contexts,
        reference_entities=expected_entities,
        reference_contexts=reference_contexts,
    )


@dataclass(slots=True, frozen=True)
class AnswerQualityMetrics:
    bert_score_f1: float
    rouge_l: float
    meteor: float
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float
    context_entity_recall: float
    hallucination_score: float
    contextual_precision: float
    contextual_recall: float
    g_eval_legal_accuracy: float
    noise_robustness: float

    @property
    def rouge_l_f1(self) -> float:
        return self.rouge_l

    @property
    def geval_legal_accuracy(self) -> float:
        return self.g_eval_legal_accuracy


@dataclass(slots=True, frozen=True)
class AnswerQualityCaseResult:
    case: AnswerQualityCase
    metrics: AnswerQualityMetrics


@dataclass(slots=True, frozen=True)
class AnswerQualitySummary:
    bert_score_f1: float
    rouge_l: float
    meteor: float
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float
    context_entity_recall: float
    hallucination_score: float
    contextual_precision: float
    contextual_recall: float
    g_eval_legal_accuracy: float
    noise_robustness: float

    @property
    def rouge_l_f1(self) -> float:
        return self.rouge_l

    @property
    def geval_legal_accuracy(self) -> float:
        return self.g_eval_legal_accuracy


@dataclass(slots=True, frozen=True)
class AnswerQualityRun:
    cases: tuple[AnswerQualityCaseResult, ...]
    summary: AnswerQualitySummary


class AnswerQualitySuite:
    def __init__(
        self,
        *,
        embedding_service: DeterministicBgeM3EmbeddingService | None = None,
        support_threshold: float = 0.72,
        context_relevance_threshold: float = 0.55,
    ) -> None:
        self.embedding_service = embedding_service or DeterministicBgeM3EmbeddingService()
        self.support_threshold = support_threshold
        self.context_relevance_threshold = context_relevance_threshold

    def run(
        self,
        cases: Sequence[AnswerQualityCase],
    ) -> AnswerQualityRun:
        case_results = tuple(self._evaluate_case(case) for case in cases)
        return AnswerQualityRun(
            cases=case_results,
            summary=self._summarize(case_results),
        )

    def _evaluate_case(
        self,
        case: AnswerQualityCase,
    ) -> AnswerQualityCaseResult:
        bert_score_f1 = self._semantic_similarity(case.answer, case.reference_answer)
        rouge_l = self._rouge_l(case.answer, case.reference_answer)
        meteor = self._meteor(case.answer, case.reference_answer)
        faithfulness = self._faithfulness(case.answer, case.contexts)
        answer_relevancy = self._semantic_similarity(case.query, case.answer)
        context_precision = self._context_precision(case.answer, case.contexts)
        context_recall = self._context_recall(
            case.reference_answer,
            case.contexts,
            case.reference_contexts,
        )
        context_entity_recall = self._context_entity_recall(case)
        hallucination_score = 1.0 - faithfulness
        contextual_precision = context_precision
        contextual_recall = context_recall
        g_eval_legal_accuracy = self._g_eval_legal_accuracy(case, bert_score_f1)
        noise_robustness = self._noise_robustness(case, context_precision)

        return AnswerQualityCaseResult(
                case=case,
                metrics=AnswerQualityMetrics(
                    bert_score_f1=bert_score_f1,
                    rouge_l=rouge_l,
                    meteor=meteor,
                    faithfulness=faithfulness,
                    answer_relevancy=answer_relevancy,
                    context_precision=context_precision,
                    context_recall=context_recall,
                    context_entity_recall=context_entity_recall,
                    hallucination_score=hallucination_score,
                    contextual_precision=contextual_precision,
                    contextual_recall=contextual_recall,
                    g_eval_legal_accuracy=g_eval_legal_accuracy,
                    noise_robustness=noise_robustness,
                ),
            )

    def _summarize(
        self,
        case_results: Sequence[AnswerQualityCaseResult],
    ) -> AnswerQualitySummary:
        if not case_results:
            return AnswerQualitySummary(
                bert_score_f1=0.0,
                rouge_l=0.0,
                meteor=0.0,
                faithfulness=0.0,
                answer_relevancy=0.0,
                context_precision=0.0,
                context_recall=0.0,
                context_entity_recall=0.0,
                hallucination_score=0.0,
                contextual_precision=0.0,
                contextual_recall=0.0,
                g_eval_legal_accuracy=0.0,
                noise_robustness=0.0,
            )

        return AnswerQualitySummary(
            bert_score_f1=fmean(item.metrics.bert_score_f1 for item in case_results),
            rouge_l=fmean(item.metrics.rouge_l for item in case_results),
            meteor=fmean(item.metrics.meteor for item in case_results),
            faithfulness=fmean(item.metrics.faithfulness for item in case_results),
            answer_relevancy=fmean(item.metrics.answer_relevancy for item in case_results),
            context_precision=fmean(item.metrics.context_precision for item in case_results),
            context_recall=fmean(item.metrics.context_recall for item in case_results),
            context_entity_recall=fmean(
                item.metrics.context_entity_recall for item in case_results
            ),
            hallucination_score=fmean(item.metrics.hallucination_score for item in case_results),
            contextual_precision=fmean(
                item.metrics.contextual_precision for item in case_results
            ),
            contextual_recall=fmean(item.metrics.contextual_recall for item in case_results),
            g_eval_legal_accuracy=fmean(
                item.metrics.g_eval_legal_accuracy for item in case_results
            ),
            noise_robustness=fmean(item.metrics.noise_robustness for item in case_results),
        )

    def _semantic_similarity(self, left: str, right: str) -> float:
        left_vector, right_vector = self.embedding_service.embed_texts([left, right])
        return self._cosine_similarity(left_vector, right_vector)

    def _rouge_l(self, answer: str, reference: str) -> float:
        answer_tokens = self._tokens(answer)
        reference_tokens = self._tokens(reference)
        if not answer_tokens or not reference_tokens:
            return 0.0

        lcs = self._lcs_length(answer_tokens, reference_tokens)
        precision = lcs / len(answer_tokens)
        recall = lcs / len(reference_tokens)
        if precision == 0.0 or recall == 0.0:
            return 0.0
        return (2 * precision * recall) / (precision + recall)

    def _meteor(self, answer: str, reference: str) -> float:
        answer_tokens = [self._stem(token) for token in self._tokens(answer)]
        reference_tokens = [self._stem(token) for token in self._tokens(reference)]
        if not answer_tokens or not reference_tokens:
            return 0.0
        if answer_tokens == reference_tokens:
            return 1.0

        answer_positions: list[int] = []
        reference_positions: list[int] = []
        used_reference_indexes: set[int] = set()
        for answer_index, token in enumerate(answer_tokens):
            for reference_index, reference_token in enumerate(reference_tokens):
                if reference_index in used_reference_indexes:
                    continue
                if token != reference_token:
                    continue
                answer_positions.append(answer_index)
                reference_positions.append(reference_index)
                used_reference_indexes.add(reference_index)
                break

        matches = len(answer_positions)
        if matches == 0:
            return 0.0

        precision = matches / len(answer_tokens)
        recall = matches / len(reference_tokens)
        weighted_fmean = (10 * precision * recall) / max(recall + 9 * precision, 1e-9)

        chunks = 1
        for index in range(1, matches):
            contiguous = (
                answer_positions[index] == answer_positions[index - 1] + 1
                and reference_positions[index] == reference_positions[index - 1] + 1
            )
            if not contiguous:
                chunks += 1

        penalty = 0.5 * (chunks / matches) ** 3
        return weighted_fmean * (1.0 - penalty)

    def _faithfulness(self, answer: str, contexts: Sequence[str]) -> float:
        claims = self._sentences(answer)
        if not claims:
            return 0.0
        if not contexts:
            return 0.0

        context_sentences = [
            sentence
            for context in contexts
            for sentence in self._sentences(context)
        ]
        if not context_sentences:
            return 0.0

        supported = 0
        for claim in claims:
            best = max(
                self._semantic_similarity(claim, sentence)
                for sentence in context_sentences
            )
            if best >= self.support_threshold:
                supported += 1
        return supported / len(claims)

    def _context_precision(self, answer: str, contexts: Sequence[str]) -> float:
        if not contexts:
            return 0.0
        helpful = sum(
            1
            for context in contexts
            if self._semantic_similarity(answer, context) >= self.context_relevance_threshold
        )
        return helpful / len(contexts)

    def _context_recall(
        self,
        reference_answer: str,
        contexts: Sequence[str],
        reference_contexts: Sequence[str],
    ) -> float:
        reference_sentences = list(reference_contexts) or self._sentences(reference_answer)
        if not reference_sentences or not contexts:
            return 0.0

        context_sentences = [
            sentence
            for context in contexts
            for sentence in self._sentences(context)
        ]
        if not context_sentences:
            return 0.0

        covered = 0
        for reference_sentence in reference_sentences:
            best = max(
                self._semantic_similarity(reference_sentence, sentence)
                for sentence in context_sentences
            )
            if best >= self.support_threshold:
                covered += 1
        return covered / len(reference_sentences)

    def _context_entity_recall(self, case: AnswerQualityCase) -> float:
        entities = case.reference_entities or tuple(self._extract_entities(case.reference_answer))
        if not entities:
            return 0.0
        context_text = " ".join(case.contexts).lower()
        found = sum(1 for entity in entities if entity.lower() in context_text)
        return found / len(entities)

    def _g_eval_legal_accuracy(
        self,
        case: AnswerQualityCase,
        bert_score_f1: float,
    ) -> float:
        answer_text = case.answer.lower()
        reference_entities = tuple(
            case.reference_entities or tuple(self._extract_entities(case.reference_answer))
        )
        if not reference_entities:
            entity_overlap = 1.0
        else:
            matched = sum(1 for entity in reference_entities if entity.lower() in answer_text)
            entity_overlap = matched / len(reference_entities)
        return 0.6 * bert_score_f1 + 0.4 * entity_overlap

    def _noise_robustness(
        self,
        case: AnswerQualityCase,
        context_precision: float,
    ) -> float:
        if not case.noisy_contexts:
            return 1.0
        noisy_precision = self._context_precision(
            case.answer,
            (*case.contexts, *case.noisy_contexts),
        )
        return max(0.0, 1.0 - abs(context_precision - noisy_precision))

    def _tokens(self, text: str) -> list[str]:
        return _WORD_PATTERN.findall(text.lower())

    def _sentences(self, text: str) -> list[str]:
        sentences = [
            sentence.strip()
            for sentence in _SENTENCE_SPLIT_PATTERN.split(" ".join(text.split()))
            if sentence.strip()
        ]
        return sentences or ([text.strip()] if text.strip() else [])

    def _extract_entities(self, text: str) -> list[str]:
        entities: list[str] = []
        seen: set[str] = set()
        for token in self._tokens(text):
            if token in _STOPWORDS or len(token) <= 2:
                continue
            if token.isdigit():
                continue
            if token not in seen:
                seen.add(token)
                entities.append(token)
        return entities

    def _stem(self, token: str) -> str:
        for suffix in ("ingly", "edly", "ing", "edly", "edly", "ed", "ly", "es", "s"):
            if token.endswith(suffix) and len(token) - len(suffix) >= 3:
                return token[: -len(suffix)]
        return token

    def _lcs_length(self, left: Sequence[str], right: Sequence[str]) -> int:
        previous = [0] * (len(right) + 1)
        for left_token in left:
            current = [0]
            for index, right_token in enumerate(right, start=1):
                if left_token == right_token:
                    current.append(previous[index - 1] + 1)
                else:
                    current.append(max(current[-1], previous[index]))
            previous = current
        return previous[-1]

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
