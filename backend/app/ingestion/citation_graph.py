from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_value
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.contracts import CitationCandidate, IngestionExecutionResult
from app.models import CitationEdge, LegalDocument, LegalDocumentType, ValidityStatus

SUPPORTED_CITATION_TYPES = {
    "follows",
    "distinguishes",
    "overrules",
    "approves",
    "disapproves",
    "doubts",
    "explains",
    "refers_to",
    "affirms",
}

_CLASSIFICATION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("overrules", (" overruled ", " overrule ", " reversed ", " reverses ")),
    ("distinguishes", (" distinguished ", " distinguish ", " distinguished from ")),
    ("disapproves", (" disapproved ", " disapproves ")),
    ("doubts", (" doubted ", " doubts ")),
    ("approves", (" approved ", " approves ")),
    ("affirms", (" affirmed ", " affirms ")),
    ("follows", (" followed ", " follows ", " relied on ", " relies on ", " applied ")),
    ("explains", (" explained ", " explains ", " clarified ", " clarifies ")),
)


@dataclass(slots=True)
class GraphNeighbor:
    doc_id: str
    citation: str | None
    neutral_citation: str | None
    court: str | None
    citation_type: str
    direction: str


@dataclass(slots=True)
class CitationGraphProjectionResult:
    source_doc_id: str
    edge_ids: list[str]
    resolved_target_doc_ids: list[str]
    unresolved_references: list[str]
    cypher_statements: list[str]


class CitationGraphProjector:
    def project(
        self,
        session: Session,
        execution: IngestionExecutionResult,
        source_doc_id: str,
    ) -> CitationGraphProjectionResult:
        source_document = session.get(LegalDocument, source_doc_id)
        if source_document is None:
            raise ValueError(f"Unknown source document: {source_doc_id}")

        edge_ids: list[str] = []
        resolved_target_doc_ids: list[str] = []
        unresolved_references: list[str] = []

        for candidate in execution.citations:
            citation_type = self.classify_edge_type(candidate)
            target_document = self.resolve_target_document(session, candidate)
            if target_document is None or target_document.doc_id == source_doc_id:
                unresolved_references.append(
                    candidate.citation_text or candidate.case_name or candidate.raw_text
                )
                continue

            edge_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"{source_doc_id}|{target_document.doc_id}|{citation_type}",
                )
            )
            edge = session.get(CitationEdge, edge_id)
            if edge is None:
                edge = CitationEdge(
                    id=edge_id,
                    source_doc_id=source_doc_id,
                    target_doc_id=target_document.doc_id,
                    citation_type=citation_type,
                )
                session.add(edge)
            else:
                edge.citation_type = citation_type

            self._apply_doc_linkage(source_document, target_document, citation_type)
            edge_ids.append(edge_id)
            resolved_target_doc_ids = self._append_unique(
                resolved_target_doc_ids,
                target_document.doc_id,
            )

        source_document.citations_made = resolved_target_doc_ids
        session.flush()

        return CitationGraphProjectionResult(
            source_doc_id=source_doc_id,
            edge_ids=edge_ids,
            resolved_target_doc_ids=resolved_target_doc_ids,
            unresolved_references=unresolved_references,
            cypher_statements=self.build_neo4j_projection(session, source_doc_id),
        )

    def classify_edge_type(self, candidate: CitationCandidate) -> str:
        candidate_type = candidate.citation_type.strip().lower()
        if candidate_type in SUPPORTED_CITATION_TYPES and candidate_type != "refers_to":
            return candidate_type

        normalized = f" {candidate.raw_text.lower()} "
        for citation_type, markers in _CLASSIFICATION_RULES:
            if any(marker in normalized for marker in markers):
                return citation_type
        return "refers_to"

    def resolve_target_document(
        self,
        session: Session,
        candidate: CitationCandidate,
    ) -> LegalDocument | None:
        if candidate.citation_text:
            direct_match = session.scalar(
                select(LegalDocument).where(
                    (LegalDocument.citation == candidate.citation_text)
                    | (LegalDocument.neutral_citation == candidate.citation_text)
                    | (LegalDocument.source_document_ref == candidate.citation_text)
                )
            )
            if direct_match is not None:
                return direct_match

        if not candidate.case_name:
            return None

        normalized_case_name = self._normalize_case_name(candidate.case_name)
        documents = session.scalars(select(LegalDocument)).all()
        for document in documents:
            rendered = self._document_case_name(document)
            if rendered and self._normalize_case_name(rendered) == normalized_case_name:
                return document
        return None

    def get_neighbors(
        self,
        session: Session,
        doc_id: str,
        *,
        direction: str = "outgoing",
    ) -> list[GraphNeighbor]:
        if direction == "incoming":
            edges = session.scalars(
                select(CitationEdge).where(CitationEdge.target_doc_id == doc_id)
            ).all()
            return [
                GraphNeighbor(
                    doc_id=edge.source_document.doc_id,
                    citation=edge.source_document.citation,
                    neutral_citation=edge.source_document.neutral_citation,
                    court=edge.source_document.court,
                    citation_type=edge.citation_type,
                    direction="incoming",
                )
                for edge in edges
            ]

        edges = session.scalars(
            select(CitationEdge).where(CitationEdge.source_doc_id == doc_id)
        ).all()
        return [
            GraphNeighbor(
                doc_id=edge.target_document.doc_id,
                citation=edge.target_document.citation,
                neutral_citation=edge.target_document.neutral_citation,
                court=edge.target_document.court,
                citation_type=edge.citation_type,
                direction="outgoing",
            )
            for edge in edges
        ]

    def build_neo4j_projection(self, session: Session, doc_id: str) -> list[str]:
        source_document = session.get(LegalDocument, doc_id)
        if source_document is None:
            raise ValueError(f"Unknown document for graph projection: {doc_id}")

        statements = [self._node_merge_statement(source_document, alias="source")]
        for neighbor in self.get_neighbors(session, doc_id, direction="outgoing"):
            target_document = session.get(LegalDocument, neighbor.doc_id)
            if target_document is None:
                continue
            statements.append(self._node_merge_statement(target_document, alias="target"))
            statements.append(
                "\n".join(
                    [
                        (
                            "MERGE "
                            f"(source:{self._neo4j_label(source_document)} "
                            f"{{doc_id: '{source_document.doc_id}'}})"
                        ),
                        (
                            "MERGE "
                            f"(target:{self._neo4j_label(target_document)} "
                            f"{{doc_id: '{target_document.doc_id}'}})"
                        ),
                        (
                            "MERGE (source)-"
                            f"[:CITES {{citation_type: '{neighbor.citation_type}'}}]->(target)"
                        ),
                    ]
                )
            )
        return statements

    def _apply_doc_linkage(
        self,
        source_document: LegalDocument,
        target_document: LegalDocument,
        citation_type: str,
    ) -> None:
        if citation_type == "follows":
            target_document.followed_by = self._append_unique(
                target_document.followed_by,
                source_document.doc_id,
            )
        elif citation_type == "distinguishes":
            target_document.distinguished_by = self._append_unique(
                target_document.distinguished_by,
                source_document.doc_id,
            )
        elif citation_type == "overrules":
            target_document.overruled_by = source_document.doc_id
            target_document.overruled_date = source_document.date
            target_document.current_validity = ValidityStatus.OVERRULED

    def _document_case_name(self, document: LegalDocument) -> str | None:
        appellant = (
            document.parties.get("appellant")
            or document.parties.get("petitioner")
            or document.parties.get("appellant_petitioner")
        )
        respondent = (
            document.parties.get("respondent")
            or document.parties.get("opposite_party")
            or document.parties.get("respondent_opposite_party")
        )
        if appellant and respondent:
            return f"{appellant} v {respondent}"
        return None

    def _normalize_case_name(self, case_name: str) -> str:
        return (
            case_name.lower()
            .replace("vs.", "v")
            .replace("vs", "v")
            .replace(".", " ")
            .replace(",", " ")
            .replace("  ", " ")
            .strip()
        )

    def _node_merge_statement(self, document: LegalDocument, *, alias: str) -> str:
        date_text = self._format_date(document.date)
        citation = self._escape(document.citation)
        court = self._escape(document.court)
        return "\n".join(
            [
                f"MERGE ({alias}:{self._neo4j_label(document)} {{doc_id: '{document.doc_id}'}})",
                (
                    f"SET {alias}.citation = '{citation}', "
                    f"{alias}.court = '{court}', "
                    f"{alias}.date = '{date_text}'"
                ),
            ]
        )

    def _neo4j_label(self, document: LegalDocument) -> str:
        if document.doc_type in {
            LegalDocumentType.STATUTE,
            LegalDocumentType.CONSTITUTION,
            LegalDocumentType.AMENDMENT,
        }:
            return "StatuteNode"
        return "JudgmentNode"

    def _format_date(self, value: date_value | None) -> str:
        return value.isoformat() if value is not None else ""

    def _escape(self, value: str | None) -> str:
        return (value or "").replace("\\", "\\\\").replace("'", "\\'")

    def _append_unique(self, items: list[str], value: str) -> list[str]:
        if value not in items:
            return [*items, value]
        return items
