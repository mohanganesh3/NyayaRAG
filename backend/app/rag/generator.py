from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.models import DocumentChunk, LegalDocument, LegalDocumentType
from app.rag.graph import GraphSearchResult
from app.rag.hybrid import HybridSearchResult
from app.schemas import PracticeArea, QueryAnalysis, QueryType


class PlaceholderKind(StrEnum):
    CITE = "CITE"
    STATUTE = "STATUTE"
    UNSUPPORTED = "UNSUPPORTED"


class RetrievalResultLike(Protocol):
    doc_id: str
    chunk_id: str
    chunk: DocumentChunk
    document: LegalDocument


@dataclass(slots=True, frozen=True)
class PlaceholderPromptContract:
    system_prompt: str
    rules: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class GeneratedPlaceholder:
    token: str
    kind: PlaceholderKind
    description: str
    doc_id: str | None
    chunk_id: str | None


@dataclass(slots=True, frozen=True)
class GeneratedSection:
    title: str
    paragraphs: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class GeneratedAnswerDraft:
    query: str
    sections: tuple[GeneratedSection, ...]
    placeholders: tuple[GeneratedPlaceholder, ...]
    prompt_contract_version: str = "placeholder-v1"

    def rendered_text(self) -> str:
        blocks: list[str] = []
        for section in self.sections:
            blocks.append(section.title.upper())
            blocks.extend(section.paragraphs)
        return "\n\n".join(blocks)

    def placeholder_tokens(self) -> list[str]:
        return [placeholder.token for placeholder in self.placeholders]


PlaceholderSearchResult = HybridSearchResult | GraphSearchResult


class PlaceholderOnlyGenerator:
    def build_prompt_contract(self) -> PlaceholderPromptContract:
        rules = (
            (
                "When you need to cite a case, emit [CITE: brief description] "
                "and never write an actual case name or reporter citation."
            ),
            (
                "When you need to cite a statute, emit [STATUTE: Act name, Section] "
                "and never write the statutory text yourself."
            ),
            (
                "If the retrieved context does not safely support a proposition, "
                "emit [UNSUPPORTED: proposition text] instead of fabricating support."
            ),
            (
                "The draft may contain explanatory prose, but every authority reference "
                "must remain a placeholder until verification resolves it."
            ),
        )
        system_prompt = "\n".join(
            [
                "You are a legal research assistant operating under a strict citation protocol.",
                *[f"{index}. {rule}" for index, rule in enumerate(rules, start=1)],
            ]
        )
        return PlaceholderPromptContract(system_prompt=system_prompt, rules=rules)

    def generate(
        self,
        query: str,
        analysis: QueryAnalysis,
        results: Sequence[PlaceholderSearchResult],
    ) -> GeneratedAnswerDraft:
        sections: list[GeneratedSection] = []
        placeholders: list[GeneratedPlaceholder] = []

        if not results:
            unsupported = self._placeholder(
                PlaceholderKind.UNSUPPORTED,
                self._unsupported_description(query, analysis),
                doc_id=None,
                chunk_id=None,
            )
            placeholders.append(unsupported)
            sections.append(
                GeneratedSection(
                    title="Research Note",
                    paragraphs=(
                        (
                            "The current retrieval set does not safely support a "
                            "verified legal answer yet."
                        ),
                        f"{unsupported.token}",
                    ),
                )
            )
            return GeneratedAnswerDraft(
                query=query,
                sections=tuple(sections),
                placeholders=tuple(placeholders),
            )

        statutes = [
            result
            for result in results
            if result.document.doc_type
            in {LegalDocumentType.STATUTE, LegalDocumentType.CONSTITUTION}
        ]
        judgments = [
            result for result in results if result.document.doc_type is LegalDocumentType.JUDGMENT
        ]

        sections.append(
            GeneratedSection(
                title="Legal Position",
                paragraphs=(self._legal_position_paragraph(analysis, statutes, judgments),),
            )
        )

        if statutes:
            statute_paragraphs: list[str] = []
            for result in statutes[:2]:
                placeholder = self._statute_placeholder(result)
                placeholders.append(placeholder)
                statute_paragraphs.append(
                    f"The governing in-force provision should be resolved from {placeholder.token}."
                )
            sections.append(
                GeneratedSection(
                    title="Applicable Law",
                    paragraphs=tuple(statute_paragraphs),
                )
            )
        elif analysis.query_type is QueryType.STATUTORY_LOOKUP:
            unsupported = self._placeholder(
                PlaceholderKind.UNSUPPORTED,
                "current statutory text required for this answer",
                doc_id=None,
                chunk_id=None,
            )
            placeholders.append(unsupported)
            sections.append(
                GeneratedSection(
                    title="Applicable Law",
                    paragraphs=(
                        f"{unsupported.token}",
                    ),
                )
            )

        if judgments:
            authority_paragraphs: list[str] = []
            for result in judgments[:3]:
                placeholder = self._cite_placeholder(result, analysis)
                placeholders.append(placeholder)
                authority_paragraphs.append(
                    f"The primary {self._authority_note(result)} is {placeholder.token}."
                )
            sections.append(
                GeneratedSection(
                    title="Key Authorities",
                    paragraphs=tuple(authority_paragraphs),
                )
            )
        elif analysis.query_type in {
            QueryType.CASE_SPECIFIC,
            QueryType.MULTI_HOP_DOCTRINE,
            QueryType.CONSTITUTIONAL,
        }:
            unsupported = self._placeholder(
                PlaceholderKind.UNSUPPORTED,
                "supporting precedent required for this answer",
                doc_id=None,
                chunk_id=None,
            )
            placeholders.append(unsupported)
            sections.append(
                GeneratedSection(
                    title="Key Authorities",
                    paragraphs=(
                        f"{unsupported.token}",
                    ),
                )
            )

        return GeneratedAnswerDraft(
            query=query,
            sections=tuple(sections),
            placeholders=tuple(placeholders),
        )

    def _legal_position_paragraph(
        self,
        analysis: QueryAnalysis,
        statutes: Sequence[PlaceholderSearchResult],
        judgments: Sequence[PlaceholderSearchResult],
    ) -> str:
        if analysis.query_type is QueryType.STATUTORY_LOOKUP:
            if statutes and judgments:
                return (
                    "The retrieved materials indicate a current statutory rule "
                    "supported by judicial interpretation, "
                    "but each authority reference remains unresolved until verification completes."
                )
            if statutes:
                return (
                    "The retrieved materials indicate a current statutory rule, and the "
                    "final authority references "
                    "must remain placeholders until verification completes."
                )
        if analysis.query_type in {QueryType.MULTI_HOP_DOCTRINE, QueryType.CONSTITUTIONAL}:
            return (
                "The retrieved materials indicate an evolving doctrinal position "
                "across multiple authorities, "
                "with the controlling path to be resolved through verified citations."
            )
        if analysis.practice_area is not PracticeArea.GENERAL:
            practice = analysis.practice_area.value.replace("_", " ")
            return (
                f"The retrieved materials indicate a current {practice} position, "
                "but the final authorities remain placeholder-only until "
                "verification resolves them."
            )
        return (
            "The retrieved materials indicate a current legal position, but the final "
            "authorities remain "
            "placeholder-only until verification resolves them."
        )

    def _statute_placeholder(self, result: PlaceholderSearchResult) -> GeneratedPlaceholder:
        act_name = result.chunk.act_name or result.document.court or "Unknown Act"
        section_number = result.chunk.section_number or self._section_hint(
            result.chunk.section_header
        )
        if section_number is None:
            description = act_name
        else:
            description = f"{act_name}, Section {section_number}"
        return self._placeholder(
            PlaceholderKind.STATUTE,
            description,
            doc_id=result.doc_id,
            chunk_id=result.chunk_id,
        )

    def _cite_placeholder(
        self,
        result: PlaceholderSearchResult,
        analysis: QueryAnalysis,
    ) -> GeneratedPlaceholder:
        authority_scope = self._authority_scope(result)
        issue = self._issue_phrase(result, analysis)
        description = f"{authority_scope} {issue}".strip()
        return self._placeholder(
            PlaceholderKind.CITE,
            description,
            doc_id=result.doc_id,
            chunk_id=result.chunk_id,
        )

    def _authority_scope(self, result: PlaceholderSearchResult) -> str:
        if isinstance(result, GraphSearchResult):
            phase_prefix = {
                "foundational": "foundational doctrinal authority",
                "development": "development-stage doctrinal authority",
                "current": "current doctrinal authority",
                "fallback": "fallback doctrinal authority",
            }.get(result.timeline_phase, "doctrinal authority")
            return phase_prefix

        authority_class = getattr(result, "authority_class", "authority")
        court = (result.document.court or "").lower()
        if "supreme court" in court:
            court_label = "Supreme Court"
        elif "high court" in court:
            court_label = "High Court"
        else:
            court_label = "court"
        return f"{authority_class} {court_label} authority"

    def _issue_phrase(
        self,
        result: PlaceholderSearchResult,
        analysis: QueryAnalysis,
    ) -> str:
        if result.chunk.section_number is not None:
            return f"interpreting Section {result.chunk.section_number}"
        if analysis.query_type is QueryType.CONSTITUTIONAL:
            return "on the constitutional issue"
        if analysis.practice_area is not PracticeArea.GENERAL:
            return f"on the {analysis.practice_area.value.replace('_', ' ')} issue"
        header = self._section_hint(result.chunk.section_header)
        if header is not None:
            return f"on {header}"
        return "on the queried issue"

    def _authority_note(self, result: PlaceholderSearchResult) -> str:
        if isinstance(result, GraphSearchResult):
            return result.timeline_phase.replace("_", " ")
        authority_class = getattr(result, "authority_class", "authority")
        court = (result.document.court or "").lower()
        if "supreme court" in court:
            court_label = "Supreme Court authority"
        elif "high court" in court:
            court_label = "High Court authority"
        else:
            court_label = "authority"
        return f"{authority_class} {court_label}"

    def _unsupported_description(self, query: str, analysis: QueryAnalysis) -> str:
        if analysis.query_type is QueryType.STATUTORY_LOOKUP:
            return "current statutory proposition requires independent verification"
        if analysis.query_type in {QueryType.MULTI_HOP_DOCTRINE, QueryType.CONSTITUTIONAL}:
            return "doctrinal position requires independent verification"
        return f"legal proposition for query: {query}"

    def _placeholder(
        self,
        kind: PlaceholderKind,
        description: str,
        *,
        doc_id: str | None,
        chunk_id: str | None,
    ) -> GeneratedPlaceholder:
        token = f"[{kind.value}: {description}]"
        return GeneratedPlaceholder(
            token=token,
            kind=kind,
            description=description,
            doc_id=doc_id,
            chunk_id=chunk_id,
        )

    def _section_hint(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            return None
        return normalized
