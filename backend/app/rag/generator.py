from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.models import DocumentChunk, LegalDocument, LegalDocumentType
from app.rag.graph import GraphSearchResult
from app.schemas import PracticeArea, QueryAnalysis, QueryType
from app.services.model_runtime import (
    JSONTaskModelClient,
    ModelRuntimeError,
    ModelTask,
    build_task_model_client,
)


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


_REPORTER_CITATION_PATTERN = re.compile(
    r"\b(?:AIR\s+\d{4}\s+[A-Z]{1,4}\s+\d+|\(\d{4}\)\s+\d+\s+[A-Z]{2,10}\s+\d+)\b"
)


class PlaceholderOnlyGenerator:
    def __init__(
        self,
        *,
        model_client: JSONTaskModelClient | None = None,
    ) -> None:
        self._model_client = (
            model_client
            if model_client is not None
            else build_task_model_client(ModelTask.PLACEHOLDER_GENERATION)
        )

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
        results: Sequence[RetrievalResultLike],
    ) -> GeneratedAnswerDraft:
        fallback_draft = self._generate_deterministic(query, analysis, results)
        if self._model_client is None or not results:
            return fallback_draft

        try:
            return self._generate_with_model(
                query=query,
                analysis=analysis,
                results=results,
                fallback_draft=fallback_draft,
            )
        except ModelRuntimeError:
            return fallback_draft

    def _generate_deterministic(
        self,
        query: str,
        analysis: QueryAnalysis,
        results: Sequence[RetrievalResultLike],
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
        statute_placeholders = [self._statute_placeholder(result) for result in statutes[:2]]
        judgment_placeholders = [
            self._cite_placeholder(result, analysis) for result in judgments[:3]
        ]
        placeholders.extend([*statute_placeholders, *judgment_placeholders])

        sections.append(
            GeneratedSection(
                title="Legal Position",
                paragraphs=(
                    self._legal_position_paragraph(
                        analysis,
                        statutes,
                        judgments,
                        statute_placeholders=statute_placeholders,
                        judgment_placeholders=judgment_placeholders,
                    ),
                ),
            )
        )

        if statutes:
            statute_paragraphs: list[str] = []
            for result, placeholder in zip(statutes[:2], statute_placeholders, strict=False):
                statute_paragraphs.append(
                    f"{self._grounded_excerpt(result)} {placeholder.token}"
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
            for result, placeholder in zip(judgments[:3], judgment_placeholders, strict=False):
                authority_paragraphs.append(
                    f"{self._grounded_excerpt(result)} {placeholder.token}"
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

    def _generate_with_model(
        self,
        *,
        query: str,
        analysis: QueryAnalysis,
        results: Sequence[RetrievalResultLike],
        fallback_draft: GeneratedAnswerDraft,
    ) -> GeneratedAnswerDraft:
        if self._model_client is None:
            raise ModelRuntimeError("No configured model client is available.")

        prompt_contract = self.build_prompt_contract()
        allowed_placeholders = {
            placeholder.token: placeholder
            for placeholder in fallback_draft.placeholders
        }
        allowed_tokens = tuple(allowed_placeholders)
        evidence_cards = []
        for result in results[:5]:
            matching_placeholder = next(
                (
                    placeholder
                    for placeholder in fallback_draft.placeholders
                    if placeholder.doc_id == result.doc_id
                    and placeholder.chunk_id == result.chunk_id
                ),
                None,
            )
            if matching_placeholder is None:
                continue
            evidence_cards.append(
                {
                    "token": matching_placeholder.token,
                    "authority_note": self._authority_note(result),
                    "excerpt": self._grounded_excerpt(result),
                }
            )

        response = self._model_client.generate_json(
            system_prompt="\n".join(
                [
                    prompt_contract.system_prompt,
                    "Return valid JSON with this shape:",
                    (
                        '{"sections":[{"title":"Section title","paragraphs":'
                        '["Paragraph with exact placeholder tokens."]}]}'
                    ),
                    "Use only the exact placeholder tokens provided by the user prompt.",
                ]
            ),
            user_prompt=json_prompt_for_placeholder_generation(
                query=query,
                analysis=analysis,
                allowed_tokens=allowed_tokens,
                evidence_cards=evidence_cards,
            ),
            max_tokens=1400,
        )
        sections_payload = response.get("sections")
        if not isinstance(sections_payload, list):
            raise ModelRuntimeError("Model response omitted the sections array.")

        sections: list[GeneratedSection] = []
        rendered_blocks: list[str] = []
        for section_value in sections_payload:
            if not isinstance(section_value, dict):
                raise ModelRuntimeError("Model section entries must be objects.")
            title = section_value.get("title")
            paragraphs = section_value.get("paragraphs")
            if not isinstance(title, str) or not isinstance(paragraphs, list):
                raise ModelRuntimeError("Model section entries must include title and paragraphs.")
            normalized_paragraphs = tuple(
                paragraph
                for paragraph in paragraphs
                if isinstance(paragraph, str) and paragraph.strip()
            )
            if not normalized_paragraphs:
                continue
            sections.append(
                GeneratedSection(
                    title=title.strip() or "Research Note",
                    paragraphs=normalized_paragraphs,
                )
            )
            rendered_blocks.extend(normalized_paragraphs)

        if not sections:
            raise ModelRuntimeError("Model response did not produce any usable sections.")

        rendered_text = "\n".join(rendered_blocks)
        bracket_tokens = re.findall(r"\[[A-Z]+: [^\]]+\]", rendered_text)
        invalid_tokens = [
            token for token in bracket_tokens if token not in allowed_placeholders
        ]
        if invalid_tokens:
            raise ModelRuntimeError(
                "Model response used placeholder tokens outside the allowed set."
            )

        used_placeholders = tuple(
            placeholder
            for placeholder in fallback_draft.placeholders
            if placeholder.token in rendered_text
        )
        if not used_placeholders:
            raise ModelRuntimeError("Model response did not use any allowed placeholder tokens.")

        if _REPORTER_CITATION_PATTERN.search(rendered_text):
            raise ModelRuntimeError("Model response emitted a raw reporter citation.")

        return GeneratedAnswerDraft(
            query=query,
            sections=tuple(sections),
            placeholders=used_placeholders,
        )

    def _legal_position_paragraph(
        self,
        analysis: QueryAnalysis,
        statutes: Sequence[RetrievalResultLike],
        judgments: Sequence[RetrievalResultLike],
        *,
        statute_placeholders: Sequence[GeneratedPlaceholder],
        judgment_placeholders: Sequence[GeneratedPlaceholder],
    ) -> str:
        if statutes and statute_placeholders:
            return f"{self._grounded_excerpt(statutes[0])} {statute_placeholders[0].token}"
        if judgments and judgment_placeholders:
            return f"{self._grounded_excerpt(judgments[0])} {judgment_placeholders[0].token}"
        if analysis.practice_area is not PracticeArea.GENERAL:
            practice = analysis.practice_area.value.replace("_", " ")
            return (
                f"The current {practice} position could not yet be grounded in a "
                "verified primary authority."
            )
        return (
            "The current legal position could not yet be grounded in a "
            "verified primary authority."
        )

    def _statute_placeholder(self, result: RetrievalResultLike) -> GeneratedPlaceholder:
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
        result: RetrievalResultLike,
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

    def _authority_scope(self, result: RetrievalResultLike) -> str:
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
        result: RetrievalResultLike,
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

    def _authority_note(self, result: RetrievalResultLike) -> str:
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

    def _grounded_excerpt(self, result: RetrievalResultLike) -> str:
        cleaned = self._sanitize_excerpt(result.chunk.text, result.document)
        if cleaned:
            return cleaned

        header = self._section_hint(result.chunk.section_header)
        if header is not None:
            return f"The relevant holding appears under {header}."

        if result.document.doc_type in {
            LegalDocumentType.STATUTE,
            LegalDocumentType.CONSTITUTION,
        }:
            return "The retrieved provision supplies the operative legal text."

        if isinstance(result, GraphSearchResult):
            return (
                f"The {result.timeline_phase.replace('_', ' ')} authority contributes to the "
                "current doctrinal position."
            )

        return f"The retrieved {self._authority_note(result)} informs the current position."

    def _sanitize_excerpt(
        self,
        text: str,
        document: LegalDocument,
    ) -> str:
        first_sentence = self._first_sentence(text)
        if not first_sentence:
            return ""

        sanitized = _REPORTER_CITATION_PATTERN.sub("", first_sentence)
        party_values = sorted(
            {
                value.strip()
                for value in document.parties.values()
                if isinstance(value, str) and value.strip()
            },
            key=len,
            reverse=True,
        )
        for party in party_values:
            sanitized = re.sub(re.escape(party), "the party", sanitized, flags=re.IGNORECASE)

        sanitized = re.sub(
            r"\bthe party\s+v(?:\.|s\.?|ersus)?\s+the party\b",
            "the parties",
            sanitized,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(r"\s+,", ",", sanitized)
        sanitized = " ".join(sanitized.split()).strip(" .,;:-")
        if not sanitized:
            return ""
        if sanitized[-1] not in ".!?":
            sanitized = f"{sanitized}."
        return sanitized

    def _first_sentence(self, text: str) -> str:
        normalized = " ".join(text.split())
        if not normalized:
            return ""
        for delimiter in (".", "!", "?"):
            if delimiter in normalized:
                prefix, _, _ = normalized.partition(delimiter)
                candidate = prefix.strip()
                if candidate:
                    return f"{candidate}{delimiter}"
        return normalized[:220].rstrip() + ("..." if len(normalized) > 220 else "")

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


def json_prompt_for_placeholder_generation(
    *,
    query: str,
    analysis: QueryAnalysis,
    allowed_tokens: Sequence[str],
    evidence_cards: Sequence[dict[str, str]],
) -> str:
    evidence_lines = []
    for index, card in enumerate(evidence_cards, start=1):
        evidence_lines.append(
            "\n".join(
                [
                    f"{index}. Token: {card['token']}",
                    f"   Authority note: {card['authority_note']}",
                    f"   Excerpt: {card['excerpt']}",
                ]
            )
        )

    return "\n".join(
        [
            f"Query: {query}",
            f"Query type: {analysis.query_type.value}",
            f"Practice area: {analysis.practice_area.value}",
            "Allowed placeholder tokens:",
            *[f"- {token}" for token in allowed_tokens],
            "Evidence cards:",
            *evidence_lines,
            "Write concise legal prose and use only the allowed placeholder tokens.",
        ]
    )
