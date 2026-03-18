from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CitationEdge, DocumentChunk, LegalDocument, LegalDocumentType, ValidityStatus
from app.rag.hybrid import HybridRAGPipeline
from app.rag.lexical import LegalTokenizer, LexicalCorpusBuilder, LexicalRetriever
from app.rag.router import QueryRouter
from app.schemas import QueryAnalysis, QueryEntityType

_FORWARD_EDGE_TYPES = {"follows", "approves", "affirms", "explains", "overrules"}
_BACKWARD_EDGE_TYPES = {"follows", "approves", "affirms", "explains", "overrules"}


@dataclass(slots=True)
class GraphAnchor:
    doc_id: str
    score: float
    reason: str


@dataclass(slots=True)
class TraversedNode:
    doc_id: str
    document: LegalDocument
    depth: int
    score: float
    relation: str | None
    direction: str | None
    is_anchor: bool = False


@dataclass(slots=True)
class GraphSearchResult:
    doc_id: str
    chunk_id: str
    chunk: DocumentChunk
    document: LegalDocument
    timeline_phase: str
    graph_depth: int
    relation: str | None
    is_anchor: bool
    node_score: float


class ConceptAnchorFinder:
    def __init__(self, *, corpus_builder: LexicalCorpusBuilder | None = None) -> None:
        self.corpus_builder = corpus_builder or LexicalCorpusBuilder()

    def find(
        self,
        session: Session,
        *,
        query: str,
        analysis: QueryAnalysis,
        top_k: int = 3,
    ) -> list[GraphAnchor]:
        exact_case_anchors = self._exact_case_anchors(session, analysis)
        if exact_case_anchors:
            return exact_case_anchors[:top_k]

        lexical_docs = [
            document
            for document in self.corpus_builder.build_from_session(session)
            if document.attributes.get("doc_type") == LegalDocumentType.JUDGMENT.value
        ]
        if not lexical_docs:
            return []

        retriever = LexicalRetriever(lexical_docs)
        lexical_results = retriever.search(query, top_k=12)

        anchors_by_doc: dict[str, GraphAnchor] = {}
        for result in lexical_results:
            document = session.get(LegalDocument, result.doc_id)
            if document is None or document.current_validity is not ValidityStatus.GOOD_LAW:
                continue
            score = result.score + self._authority_bonus(document) + self._graph_bonus(document)
            existing = anchors_by_doc.get(result.doc_id)
            if existing is None or score > existing.score:
                anchors_by_doc[result.doc_id] = GraphAnchor(
                    doc_id=result.doc_id,
                    score=score,
                    reason="lexical_landmark",
                )

        ranked = sorted(anchors_by_doc.values(), key=lambda item: item.score, reverse=True)
        return ranked[:top_k]

    def _exact_case_anchors(
        self,
        session: Session,
        analysis: QueryAnalysis,
    ) -> list[GraphAnchor]:
        case_entities = [
            entity.text
            for entity in analysis.entities
            if entity.entity_type is QueryEntityType.CASE_NAME
        ]
        anchors: list[GraphAnchor] = []
        for case_name in case_entities:
            normalized = self._normalize_case_name(case_name)
            for document in session.scalars(
                select(LegalDocument).where(LegalDocument.doc_type == LegalDocumentType.JUDGMENT)
            ).all():
                rendered = self._document_case_name(document)
                if rendered is None:
                    continue
                if self._normalize_case_name(rendered) == normalized:
                    anchors.append(
                        GraphAnchor(
                            doc_id=document.doc_id,
                            score=2.0 + self._authority_bonus(document),
                            reason="exact_case_match",
                        )
                    )
        anchors.sort(key=lambda item: item.score, reverse=True)
        return anchors

    def _authority_bonus(self, document: LegalDocument) -> float:
        court = (document.court or "").lower()
        bench_size = document.coram or len(document.bench)
        if court in {"supreme court", "supreme court of india"}:
            return 0.5 + min(bench_size, 9) * 0.03
        if "high court" in court:
            return 0.2 + min(bench_size, 5) * 0.02
        return 0.05

    def _graph_bonus(self, document: LegalDocument) -> float:
        outgoing = len(document.citations_made)
        followed = len(document.followed_by)
        distinguished = len(document.distinguished_by)
        return min((outgoing + followed + distinguished) * 0.03, 0.4)

    def _document_case_name(self, document: LegalDocument) -> str | None:
        appellant = document.parties.get("appellant") or document.parties.get("petitioner")
        respondent = document.parties.get("respondent") or document.parties.get("opposite_party")
        if appellant and respondent:
            return f"{appellant} v {respondent}"
        return None

    def _normalize_case_name(self, value: str) -> str:
        return (
            value.lower()
            .replace("vs.", "v")
            .replace("vs", "v")
            .replace(".", " ")
            .replace(",", " ")
        ).strip()


class CitationGraphTraversal:
    def traverse(
        self,
        session: Session,
        *,
        anchors: Sequence[GraphAnchor],
        max_depth: int = 4,
        max_nodes: int = 50,
    ) -> dict[str, TraversedNode]:
        traversed: dict[str, TraversedNode] = {}
        queue: deque[tuple[str, int]] = deque()

        for anchor in anchors:
            document = session.get(LegalDocument, anchor.doc_id)
            if document is None:
                continue
            traversed[anchor.doc_id] = TraversedNode(
                doc_id=anchor.doc_id,
                document=document,
                depth=0,
                score=anchor.score,
                relation=None,
                direction=None,
                is_anchor=True,
            )
            queue.append((anchor.doc_id, 0))

        while queue and len(traversed) < max_nodes:
            current_doc_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for edge, document, direction in self._neighbors(session, current_doc_id):
                node_score = self._node_score(document, edge.citation_type, depth + 1)
                existing = traversed.get(document.doc_id)
                if existing is None or node_score > existing.score:
                    traversed[document.doc_id] = TraversedNode(
                        doc_id=document.doc_id,
                        document=document,
                        depth=depth + 1,
                        score=node_score,
                        relation=edge.citation_type,
                        direction=direction,
                        is_anchor=False,
                    )
                if existing is None and len(traversed) < max_nodes:
                    queue.append((document.doc_id, depth + 1))

        return traversed

    def prune_overruled(
        self,
        session: Session,
        traversed: dict[str, TraversedNode],
    ) -> dict[str, TraversedNode]:
        pruned = dict(traversed)
        for doc_id, node in list(pruned.items()):
            if node.document.current_validity in {
                ValidityStatus.OVERRULED,
                ValidityStatus.REVERSED_ON_APPEAL,
            }:
                del pruned[doc_id]
                continue

            overrules = session.execute(
                select(CitationEdge, LegalDocument)
                .join(LegalDocument, CitationEdge.source_doc_id == LegalDocument.doc_id)
                .where(
                    CitationEdge.target_doc_id == doc_id,
                    CitationEdge.citation_type == "overrules",
                )
            ).all()
            if not overrules:
                continue

            del pruned[doc_id]
            for edge, overruling_document in overrules:
                if overruling_document.doc_id in pruned:
                    continue
                pruned[overruling_document.doc_id] = TraversedNode(
                    doc_id=overruling_document.doc_id,
                    document=overruling_document,
                    depth=node.depth,
                    score=node.score + 0.25,
                    relation=edge.citation_type,
                    direction="forward",
                    is_anchor=False,
                )

        return pruned

    def _neighbors(
        self,
        session: Session,
        doc_id: str,
    ) -> list[tuple[CitationEdge, LegalDocument, str]]:
        rows: list[tuple[CitationEdge, LegalDocument, str]] = []

        forward_rows = session.execute(
            select(CitationEdge, LegalDocument)
            .join(LegalDocument, CitationEdge.source_doc_id == LegalDocument.doc_id)
            .where(
                CitationEdge.target_doc_id == doc_id,
                CitationEdge.citation_type.in_(_FORWARD_EDGE_TYPES),
            )
        ).all()
        rows.extend((edge, document, "forward") for edge, document in forward_rows)

        backward_rows = session.execute(
            select(CitationEdge, LegalDocument)
            .join(LegalDocument, CitationEdge.target_doc_id == LegalDocument.doc_id)
            .where(
                CitationEdge.source_doc_id == doc_id,
                CitationEdge.citation_type.in_(_BACKWARD_EDGE_TYPES),
            )
        ).all()
        rows.extend((edge, document, "backward") for edge, document in backward_rows)

        return rows

    def _node_score(
        self,
        document: LegalDocument,
        relation: str,
        depth: int,
    ) -> float:
        base = 1.0 / (depth + 1)
        relation_bonus = {
            "overrules": 0.35,
            "follows": 0.25,
            "approves": 0.22,
            "affirms": 0.20,
            "explains": 0.18,
        }.get(relation, 0.1)
        court_bonus = 0.3 if (document.court or "").lower().startswith("supreme court") else 0.1
        recency_bonus = 0.0
        if document.date is not None:
            recency_bonus = min(max(document.date.year - 1950, 0) / 250.0, 0.25)
        return base + relation_bonus + court_bonus + recency_bonus


class DoctrinalTimelineBuilder:
    def __init__(self, *, tokenizer: LegalTokenizer | None = None) -> None:
        self.tokenizer = tokenizer or LegalTokenizer()

    def build(
        self,
        session: Session,
        *,
        query: str,
        traversed: dict[str, TraversedNode],
        top_n: int = 15,
    ) -> list[GraphSearchResult]:
        ordered_nodes = sorted(
            traversed.values(),
            key=lambda item: (
                item.document.date or item.document.created_at,
                item.depth,
                item.score,
            ),
        )[:top_n]
        if not ordered_nodes:
            return []

        query_tokens = set(self.tokenizer.tokenize(query))
        results: list[GraphSearchResult] = []
        total = len(ordered_nodes)

        for index, node in enumerate(ordered_nodes):
            chunk = self._best_chunk(session, node.document.doc_id, query_tokens)
            if chunk is None:
                continue
            results.append(
                GraphSearchResult(
                    doc_id=node.doc_id,
                    chunk_id=chunk.chunk_id,
                    chunk=chunk,
                    document=node.document,
                    timeline_phase=self._phase_for_index(index, total),
                    graph_depth=node.depth,
                    relation=node.relation,
                    is_anchor=node.is_anchor,
                    node_score=node.score,
                )
            )

        return results

    def _best_chunk(
        self,
        session: Session,
        doc_id: str,
        query_tokens: set[str],
    ) -> DocumentChunk | None:
        chunks = session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.doc_id == doc_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
        if not chunks:
            return None

        def overlap_score(chunk: DocumentChunk) -> tuple[int, int]:
            tokens = set(self.tokenizer.tokenize(chunk.text))
            return (len(query_tokens & tokens), -chunk.chunk_index)

        return max(chunks, key=overlap_score)

    def _phase_for_index(self, index: int, total: int) -> str:
        if total == 1:
            return "current"
        foundational_cutoff = max(1, total // 3)
        current_cutoff = max(total - 2, foundational_cutoff + 1)
        if index < foundational_cutoff:
            return "foundational"
        if index >= current_cutoff:
            return "current"
        return "development"


class GraphRAGPipeline:
    def __init__(
        self,
        *,
        anchor_finder: ConceptAnchorFinder | None = None,
        traversal: CitationGraphTraversal | None = None,
        timeline_builder: DoctrinalTimelineBuilder | None = None,
        hybrid_fallback: HybridRAGPipeline | None = None,
        router: QueryRouter | None = None,
    ) -> None:
        self.anchor_finder = anchor_finder or ConceptAnchorFinder()
        self.traversal = traversal or CitationGraphTraversal()
        self.timeline_builder = timeline_builder or DoctrinalTimelineBuilder()
        self.hybrid_fallback = hybrid_fallback or HybridRAGPipeline()
        self.router = router or QueryRouter()

    def retrieve(
        self,
        session: Session,
        query: str,
        *,
        analysis: QueryAnalysis | None = None,
    ) -> list[GraphSearchResult]:
        active_analysis = analysis or self.router.analyze(query, session=session)
        anchors = self.anchor_finder.find(
            session,
            query=query,
            analysis=active_analysis,
        )
        if not anchors:
            return self._fallback(session, query, active_analysis)

        traversed = self.traversal.traverse(
            session,
            anchors=anchors,
        )
        pruned = self.traversal.prune_overruled(session, traversed)
        timeline = self.timeline_builder.build(
            session,
            query=query,
            traversed=pruned,
        )
        if timeline:
            return timeline
        return self._fallback(session, query, active_analysis)

    def _fallback(
        self,
        session: Session,
        query: str,
        analysis: QueryAnalysis,
    ) -> list[GraphSearchResult]:
        hybrid_results = self.hybrid_fallback.retrieve(
            session,
            query,
            analysis=analysis,
        )
        return [
            GraphSearchResult(
                doc_id=result.doc_id,
                chunk_id=result.chunk_id,
                chunk=result.chunk,
                document=result.document,
                timeline_phase="fallback",
                graph_depth=0,
                relation=None,
                is_anchor=False,
                node_score=result.rerank_score,
            )
            for result in hybrid_results
        ]
