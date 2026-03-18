from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.embeddings import DeterministicBgeM3EmbeddingService
from app.models import DocumentChunk
from app.rag.lexical import LegalTokenizer
from app.rag.resolution import CitationResolutionStatus, ResolvedPlaceholder

_NEGATION_TOKENS = {"cannot", "denied", "fails", "never", "no", "none", "not", "without"}
_CONTENT_STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "as",
    "at",
    "by",
    "for",
    "from",
    "held",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "under",
    "was",
    "were",
}


class EntailmentLabel(StrEnum):
    ENTAILMENT = "ENTAILMENT"
    NEUTRAL = "NEUTRAL"
    CONTRADICTION = "CONTRADICTION"


class MisgroundingStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNCERTAIN = "UNCERTAIN"
    MISGROUNDED = "MISGROUNDED"


class MisgroundingAction(StrEnum):
    KEEP = "KEEP"
    SHOW_SOURCE_TO_USER = "SHOW_SOURCE_TO_USER"
    REMOVE_AND_RERETRIEVE = "REMOVE_AND_RERETRIEVE"


@dataclass(slots=True, frozen=True)
class PassageCandidate:
    chunk_id: str
    text: str
    score: float


@dataclass(slots=True, frozen=True)
class MisgroundingResult:
    claim: str
    status: MisgroundingStatus
    confidence: float
    similarity: float
    entailment_label: EntailmentLabel
    action: MisgroundingAction
    source_passage: str | None
    doc_id: str | None
    chunk_id: str | None
    citation: str | None
    message: str


class DeterministicEntailmentClassifier:
    def __init__(self, *, tokenizer: LegalTokenizer | None = None) -> None:
        self.tokenizer = tokenizer or LegalTokenizer()

    def classify(self, *, premise: str, hypothesis: str) -> EntailmentLabel:
        claim_tokens = self._content_tokens(hypothesis)
        passage_tokens = self._content_tokens(premise)
        shared = claim_tokens & passage_tokens

        if self._has_negation_mismatch(hypothesis, premise, shared):
            return EntailmentLabel.CONTRADICTION

        overlap = len(shared) / max(len(claim_tokens), 1)
        if overlap >= 0.65:
            return EntailmentLabel.ENTAILMENT
        if overlap >= 0.35:
            return EntailmentLabel.NEUTRAL
        return EntailmentLabel.CONTRADICTION

    def _content_tokens(self, text: str) -> set[str]:
        return {
            token
            for token in self.tokenizer.tokenize(text.lower())
            if token not in _CONTENT_STOPWORDS
        }

    def _has_negation_mismatch(
        self,
        hypothesis: str,
        premise: str,
        shared_tokens: set[str],
    ) -> bool:
        if len(shared_tokens) < 2:
            return False
        claim_has_negation = self._has_negation(hypothesis)
        premise_has_negation = self._has_negation(premise)
        return claim_has_negation != premise_has_negation

    def _has_negation(self, text: str) -> bool:
        return any(token in _NEGATION_TOKENS for token in self.tokenizer.tokenize(text.lower()))


class MisgroundingChecker:
    def __init__(
        self,
        *,
        tokenizer: LegalTokenizer | None = None,
        embedding_service: DeterministicBgeM3EmbeddingService | None = None,
        entailment_classifier: DeterministicEntailmentClassifier | None = None,
        verified_threshold: float = 0.82,
        uncertain_threshold: float = 0.55,
    ) -> None:
        self.tokenizer = tokenizer or LegalTokenizer()
        self.embedding_service = embedding_service or DeterministicBgeM3EmbeddingService()
        self.entailment_classifier = entailment_classifier or DeterministicEntailmentClassifier(
            tokenizer=self.tokenizer
        )
        self.verified_threshold = verified_threshold
        self.uncertain_threshold = uncertain_threshold

    def check_claim(
        self,
        session: Session,
        *,
        claim: str,
        resolution: ResolvedPlaceholder,
        top_k: int = 3,
    ) -> MisgroundingResult:
        if resolution.status is not CitationResolutionStatus.VERIFIED or resolution.doc_id is None:
            return MisgroundingResult(
                claim=claim,
                status=MisgroundingStatus.UNCERTAIN,
                confidence=0.0,
                similarity=0.0,
                entailment_label=EntailmentLabel.NEUTRAL,
                action=MisgroundingAction.SHOW_SOURCE_TO_USER,
                source_passage=None,
                doc_id=resolution.doc_id,
                chunk_id=resolution.chunk_id,
                citation=resolution.citation,
                message="Citation is unresolved, so the claim cannot yet be grounded.",
            )

        passages = self.retrieve_within_doc(
            session,
            claim=claim,
            doc_id=resolution.doc_id,
            preferred_chunk_id=resolution.chunk_id,
            top_k=top_k,
        )
        if not passages:
            return MisgroundingResult(
                claim=claim,
                status=MisgroundingStatus.MISGROUNDED,
                confidence=0.0,
                similarity=0.0,
                entailment_label=EntailmentLabel.CONTRADICTION,
                action=MisgroundingAction.REMOVE_AND_RERETRIEVE,
                source_passage=None,
                doc_id=resolution.doc_id,
                chunk_id=resolution.chunk_id,
                citation=resolution.citation,
                message="No source passage could be located within the cited authority.",
            )

        best_passage = passages[0]
        similarity = self._semantic_similarity(claim, best_passage.text)
        entailment = self.entailment_classifier.classify(
            premise=best_passage.text,
            hypothesis=claim,
        )

        if entailment is EntailmentLabel.CONTRADICTION:
            return MisgroundingResult(
                claim=claim,
                status=MisgroundingStatus.MISGROUNDED,
                confidence=similarity,
                similarity=similarity,
                entailment_label=entailment,
                action=MisgroundingAction.REMOVE_AND_RERETRIEVE,
                source_passage=best_passage.text,
                doc_id=resolution.doc_id,
                chunk_id=best_passage.chunk_id,
                citation=resolution.citation,
                message="Cited authority contradicts the claim as stated.",
            )

        if similarity >= self.verified_threshold and entailment is EntailmentLabel.ENTAILMENT:
            return MisgroundingResult(
                claim=claim,
                status=MisgroundingStatus.VERIFIED,
                confidence=similarity,
                similarity=similarity,
                entailment_label=entailment,
                action=MisgroundingAction.KEEP,
                source_passage=best_passage.text,
                doc_id=resolution.doc_id,
                chunk_id=best_passage.chunk_id,
                citation=resolution.citation,
                message="Best source passage supports the claim.",
            )

        if similarity >= self.uncertain_threshold or entailment is EntailmentLabel.NEUTRAL:
            return MisgroundingResult(
                claim=claim,
                status=MisgroundingStatus.UNCERTAIN,
                confidence=similarity,
                similarity=similarity,
                entailment_label=entailment,
                action=MisgroundingAction.SHOW_SOURCE_TO_USER,
                source_passage=best_passage.text,
                doc_id=resolution.doc_id,
                chunk_id=best_passage.chunk_id,
                citation=resolution.citation,
                message="Source passage is related but does not fully entail the claim.",
            )

        return MisgroundingResult(
            claim=claim,
            status=MisgroundingStatus.MISGROUNDED,
            confidence=similarity,
            similarity=similarity,
            entailment_label=entailment,
            action=MisgroundingAction.REMOVE_AND_RERETRIEVE,
            source_passage=best_passage.text,
            doc_id=resolution.doc_id,
            chunk_id=best_passage.chunk_id,
            citation=resolution.citation,
            message="Cited authority does not support the claim as stated.",
        )

    def retrieve_within_doc(
        self,
        session: Session,
        *,
        claim: str,
        doc_id: str,
        preferred_chunk_id: str | None,
        top_k: int = 3,
    ) -> list[PassageCandidate]:
        chunks = session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.doc_id == doc_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
        if not chunks:
            return []

        claim_tokens = self._content_tokens(claim)
        ranked: list[PassageCandidate] = []
        for chunk in chunks:
            chunk_tokens = self._content_tokens(chunk.text)
            overlap = self._overlap(claim_tokens, chunk_tokens)
            header_overlap = self._overlap(
                claim_tokens,
                self._content_tokens(chunk.section_header or ""),
            )
            similarity = self._semantic_similarity(claim, chunk.text)
            score = 0.55 * similarity + 0.35 * overlap + 0.10 * header_overlap
            if preferred_chunk_id is not None and chunk.chunk_id == preferred_chunk_id:
                score += 0.10
            ranked.append(
                PassageCandidate(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    score=min(score, 1.0),
                )
            )

        ranked.sort(key=lambda candidate: candidate.score, reverse=True)
        return ranked[:top_k]

    def _semantic_similarity(self, claim: str, passage: str) -> float:
        claim_vector, passage_vector = self.embedding_service.embed_texts([claim, passage])
        cosine = self._cosine_similarity(claim_vector, passage_vector)
        lexical = self._overlap(self._content_tokens(claim), self._content_tokens(passage))
        return max(cosine, lexical)

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        limit = min(len(left), len(right))
        if limit == 0:
            return 0.0
        numerator = sum(left[index] * right[index] for index in range(limit))
        left_norm = math.sqrt(sum(left[index] * left[index] for index in range(limit)))
        right_norm = math.sqrt(sum(right[index] * right[index] for index in range(limit)))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        return numerator / (left_norm * right_norm)

    def _content_tokens(self, text: str) -> set[str]:
        return {
            token
            for token in self.tokenizer.tokenize(text.lower())
            if token not in _CONTENT_STOPWORDS
        }

    def _overlap(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left)
