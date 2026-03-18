from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date as date_value

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentChunk, LegalDocument, ValidityStatus
from app.services.criminal_code_mappings import CriminalCodeMappingResolver

_INITIALS_PATTERN = re.compile(r"\b(?:[a-z]\.){2,}[a-z]?\.?", re.IGNORECASE)
_SECTION_WITH_CODE_PATTERN = re.compile(
    r"\b(?:section|s\.)\s*([0-9]+[a-z]?)\s*(ipc|crpc|bns|bnss|bsa)\b",
    re.IGNORECASE,
)
_CODE_WITH_SECTION_PATTERN = re.compile(
    r"\b(ipc|crpc|bns|bnss|bsa)\s*([0-9]+[a-z]?)\b",
    re.IGNORECASE,
)
_ARTICLE_PATTERN = re.compile(r"\barticle\s*([0-9]+[a-z]?)\b", re.IGNORECASE)
_AIR_CITATION_PATTERN = re.compile(r"\bair\s+\d{4}\s+sc\s+\d+\b", re.IGNORECASE)
_SCC_CITATION_PATTERN = re.compile(r"\(\d{4}\)\s*\d+\s*scc\s*\d+", re.IGNORECASE)
_INSC_CITATION_PATTERN = re.compile(r"\b\d{4}\s+insc\s+\d+\b", re.IGNORECASE)
_WORD_PATTERN = re.compile(r"[a-z]+[a-z0-9]*|\d+[a-z]?")

_ACT_ALIAS_MAP: dict[str, list[str]] = {
    "indian penal code": ["ipc", "indian penal code"],
    "bharatiya nyaya sanhita": ["bns", "bharatiya nyaya sanhita"],
    "code of criminal procedure": ["crpc", "code of criminal procedure"],
    "bharatiya nagarik suraksha sanhita": ["bnss", "bharatiya nagarik suraksha sanhita"],
    "indian evidence act": ["indian evidence act", "evidence act"],
    "bharatiya sakshya adhiniyam": ["bsa", "bharatiya sakshya adhiniyam"],
    "bharatiya sakshya": ["bsa"],
    "constitution of india": ["constitution", "constitution of india"],
}
_SYNONYM_MAP: dict[str, tuple[str, ...]] = {
    "murder": ("culpable homicide", "ipc 302", "bns 101"),
    "bail": ("anticipatory bail", "crpc 437", "bnss 480"),
    "privacy": ("article 21", "fundamental right"),
}


@dataclass(slots=True)
class LegalLexicalDocument:
    doc_id: str
    chunk_id: str
    text: str
    title: str | None = None
    citation: str | None = None
    neutral_citation: str | None = None
    section_header: str | None = None
    act_name: str | None = None
    section_number: str | None = None
    court: str | None = None
    parties: dict[str, str] = field(default_factory=dict)
    current_validity: str = ValidityStatus.GOOD_LAW.value
    practice_areas: list[str] = field(default_factory=list)
    attributes: dict[str, object] = field(default_factory=dict)

    def combined_text(self) -> str:
        case_name = self.case_name()
        fields = [
            self.title,
            case_name,
            self.citation,
            self.neutral_citation,
            self.section_header,
            self.act_name,
            self.section_number,
            self.court,
            " ".join(self.practice_areas),
            self.text,
        ]
        return " ".join(part for part in fields if part)

    def case_name(self) -> str | None:
        appellant = self.parties.get("appellant")
        respondent = self.parties.get("respondent")
        if appellant and respondent:
            return f"{appellant} v {respondent}"
        return None


@dataclass(slots=True)
class ExpandedQuery:
    raw_query: str
    tokens: list[str]
    references: list[str]
    synonym_expansions: list[str]
    criminal_code_expansions: list[str]


@dataclass(slots=True)
class LegalSearchResult:
    doc_id: str
    chunk_id: str
    score: float
    matched_terms: list[str]
    document: LegalLexicalDocument


class LegalDocumentAliasResolver:
    def aliases_for(self, act_name: str | None) -> list[str]:
        if act_name is None:
            return []
        normalized = self._normalize_alias_text(act_name)
        aliases: list[str] = []
        for key, values in _ACT_ALIAS_MAP.items():
            if key in normalized:
                aliases.extend(values)
        return list(dict.fromkeys(aliases))

    def _normalize_alias_text(self, text: str) -> str:
        lowered = text.lower()
        lowered = re.sub(r"[^a-z0-9 ]+", " ", lowered)
        return " ".join(lowered.split())


class LegalTokenizer:
    def tokenize(self, text: str) -> list[str]:
        normalized = self._normalize_text(text)
        tokens: list[str] = []
        tokens.extend(self._extract_reference_tokens(normalized))
        tokens.extend(self._extract_citation_tokens(normalized))
        tokens.extend(_WORD_PATTERN.findall(normalized))
        return list(dict.fromkeys(token for token in tokens if token))

    def section_reference_tokens(self, code: str, section: str) -> list[str]:
        section_lower = section.lower()
        code_lower = code.lower()
        return [
            code_lower,
            section_lower,
            f"{code_lower}_{section_lower}",
            f"section_{section_lower}",
        ]

    def article_reference_tokens(self, article: str) -> list[str]:
        article_lower = article.lower()
        return [article_lower, f"article_{article_lower}"]

    def _normalize_text(self, text: str) -> str:
        lowered = text.lower()
        lowered = _INITIALS_PATTERN.sub(self._collapse_initials, lowered)
        lowered = re.sub(r"\bvs?\.?\b", " v ", lowered)
        lowered = re.sub(r"[^a-z0-9() ]+", " ", lowered)
        return " ".join(lowered.split())

    def _collapse_initials(self, match: re.Match[str]) -> str:
        return match.group(0).replace(".", "")

    def _extract_reference_tokens(self, normalized: str) -> list[str]:
        tokens: list[str] = []
        for code, section in _SECTION_WITH_CODE_PATTERN.findall(normalized):
            tokens.extend(self.section_reference_tokens(code, section))
        for code, section in _CODE_WITH_SECTION_PATTERN.findall(normalized):
            tokens.extend(self.section_reference_tokens(code, section))
        for article in _ARTICLE_PATTERN.findall(normalized):
            tokens.extend(self.article_reference_tokens(article))
        return tokens

    def _extract_citation_tokens(self, normalized: str) -> list[str]:
        tokens: list[str] = []
        for pattern in (_AIR_CITATION_PATTERN, _SCC_CITATION_PATTERN, _INSC_CITATION_PATTERN):
            for match in pattern.findall(normalized):
                token = "_".join(match.replace("(", "").replace(")", "").split())
                tokens.append(token)
        return tokens


class LegalSynonymExpander:
    def expansions_for(self, query: str) -> list[str]:
        normalized = " ".join(query.lower().split())
        expansions: list[str] = []
        for phrase, values in _SYNONYM_MAP.items():
            if phrase in normalized:
                expansions.extend(values)
        return list(dict.fromkeys(expansions))


class LegalQueryExpander:
    def __init__(
        self,
        *,
        tokenizer: LegalTokenizer | None = None,
        synonym_expander: LegalSynonymExpander | None = None,
        mapping_resolver: CriminalCodeMappingResolver | None = None,
    ) -> None:
        self.tokenizer = tokenizer or LegalTokenizer()
        self.synonym_expander = synonym_expander or LegalSynonymExpander()
        self.mapping_resolver = mapping_resolver or CriminalCodeMappingResolver()

    def expand(
        self,
        query: str,
        *,
        session: Session | None = None,
        reference_date: date_value | None = None,
    ) -> ExpandedQuery:
        references = self._extract_criminal_code_references(query)
        synonym_expansions = self.synonym_expander.expansions_for(query)
        criminal_code_expansions: list[str] = []
        if session is not None and references:
            criminal_code_expansions = self.mapping_resolver.expand_references_for_query(
                session,
                references,
                reference_date=reference_date,
            )

        tokens = self.tokenizer.tokenize(query)
        for expansion in synonym_expansions + criminal_code_expansions:
            tokens.extend(self.tokenizer.tokenize(expansion))
        return ExpandedQuery(
            raw_query=query,
            tokens=tokens,
            references=references,
            synonym_expansions=synonym_expansions,
            criminal_code_expansions=criminal_code_expansions,
        )

    def _extract_criminal_code_references(self, query: str) -> list[str]:
        normalized = " ".join(query.split())
        references: list[str] = []
        seen: set[str] = set()

        for section, code in _SECTION_WITH_CODE_PATTERN.findall(normalized):
            reference = f"{code.upper()} {section.upper()}"
            if reference not in seen:
                seen.add(reference)
                references.append(reference)

        for code, section in _CODE_WITH_SECTION_PATTERN.findall(normalized):
            reference = f"{code.upper()} {section.upper()}"
            if reference not in seen:
                seen.add(reference)
                references.append(reference)

        return references


class BM25Index:
    def __init__(
        self,
        documents: Sequence[LegalLexicalDocument],
        *,
        tokenizer: LegalTokenizer | None = None,
        alias_resolver: LegalDocumentAliasResolver | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.documents = list(documents)
        self.tokenizer = tokenizer or LegalTokenizer()
        self.alias_resolver = alias_resolver or LegalDocumentAliasResolver()
        self.k1 = k1
        self.b = b
        self.doc_tokens: dict[str, list[str]] = {}
        self.doc_term_freqs: dict[str, Counter[str]] = {}
        self.doc_lengths: dict[str, int] = {}
        self.document_frequency: Counter[str] = Counter()
        self.avg_doc_length = 0.0
        self._build()

    def search(
        self,
        query_tokens: Sequence[str],
        *,
        top_k: int = 10,
        min_score: float = 0.0,
        filter_fn: Callable[[LegalLexicalDocument], bool] | None = None,
    ) -> list[LegalSearchResult]:
        if not query_tokens:
            return []

        filtered_documents = self.documents
        if filter_fn is not None:
            filtered_documents = [document for document in self.documents if filter_fn(document)]

        results: list[LegalSearchResult] = []
        for document in filtered_documents:
            term_freqs = self.doc_term_freqs[document.chunk_id]
            score = 0.0
            matched_terms: list[str] = []
            doc_length = self.doc_lengths[document.chunk_id]

            for token in query_tokens:
                frequency = term_freqs.get(token, 0)
                if frequency == 0:
                    continue
                idf = self._idf(token)
                numerator = frequency * (self.k1 + 1)
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * (doc_length / max(self.avg_doc_length, 1.0))
                )
                score += idf * (numerator / denominator)
                matched_terms.append(token)

            if score <= min_score:
                continue
            results.append(
                LegalSearchResult(
                    doc_id=document.doc_id,
                    chunk_id=document.chunk_id,
                    score=score,
                    matched_terms=sorted(set(matched_terms)),
                    document=document,
                )
            )

        return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]

    def _build(self) -> None:
        total_length = 0
        for document in self.documents:
            tokens = self._document_tokens(document)
            self.doc_tokens[document.chunk_id] = tokens
            term_freqs = Counter(tokens)
            self.doc_term_freqs[document.chunk_id] = term_freqs
            self.doc_lengths[document.chunk_id] = len(tokens)
            total_length += len(tokens)
            for token in term_freqs:
                self.document_frequency[token] += 1

        self.avg_doc_length = total_length / max(len(self.documents), 1)

    def _document_tokens(self, document: LegalLexicalDocument) -> list[str]:
        tokens = self.tokenizer.tokenize(document.combined_text())
        aliases = self.alias_resolver.aliases_for(document.act_name)
        for alias in aliases:
            tokens.extend(self.tokenizer.tokenize(alias))
            if document.section_number is not None:
                if " " not in alias:
                    tokens.extend(
                        self.tokenizer.section_reference_tokens(alias, document.section_number)
                    )
                else:
                    tokens.extend(
                        self.tokenizer.tokenize(f"{alias} section {document.section_number}")
                    )
        if document.section_number is not None:
            tokens.append(f"section_{document.section_number.lower()}")
        return list(dict.fromkeys(tokens))

    def _idf(self, token: str) -> float:
        num_docs = len(self.documents)
        df = self.document_frequency.get(token, 0)
        return math.log(1 + ((num_docs - df + 0.5) / (df + 0.5)))


class LexicalRetriever:
    def __init__(
        self,
        documents: Sequence[LegalLexicalDocument],
        *,
        tokenizer: LegalTokenizer | None = None,
        query_expander: LegalQueryExpander | None = None,
    ) -> None:
        self.tokenizer = tokenizer or LegalTokenizer()
        self.query_expander = query_expander or LegalQueryExpander(tokenizer=self.tokenizer)
        self.index = BM25Index(documents, tokenizer=self.tokenizer)

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        session: Session | None = None,
        reference_date: date_value | None = None,
        valid_only: bool = True,
    ) -> list[LegalSearchResult]:
        expanded = self.query_expander.expand(
            query,
            session=session,
            reference_date=reference_date,
        )
        filter_fn = None
        if valid_only:
            def valid_filter(document: LegalLexicalDocument) -> bool:
                return document.current_validity == ValidityStatus.GOOD_LAW.value

            filter_fn = valid_filter
        return self.index.search(expanded.tokens, top_k=top_k, min_score=0.0, filter_fn=filter_fn)


class LexicalCorpusBuilder:
    def build_from_session(
        self,
        session: Session,
        *,
        limit: int | None = None,
    ) -> list[LegalLexicalDocument]:
        statement = (
            select(DocumentChunk, LegalDocument)
            .join(LegalDocument, DocumentChunk.doc_id == LegalDocument.doc_id)
            .order_by(DocumentChunk.doc_id, DocumentChunk.chunk_index)
        )
        if limit is not None:
            statement = statement.limit(limit)

        rows = session.execute(statement).all()
        documents: list[LegalLexicalDocument] = []
        for chunk, document in rows:
            title = self._case_name(document.parties)
            documents.append(
                LegalLexicalDocument(
                    doc_id=document.doc_id,
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    title=title,
                    citation=document.citation,
                    neutral_citation=document.neutral_citation,
                    section_header=chunk.section_header,
                    act_name=chunk.act_name,
                    section_number=chunk.section_number,
                    court=document.court,
                    parties=document.parties,
                    current_validity=document.current_validity.value,
                    practice_areas=document.practice_areas,
                    attributes={
                        "doc_type": document.doc_type.value,
                    },
                )
            )
        return documents

    def _case_name(self, parties: dict[str, str]) -> str | None:
        appellant = parties.get("appellant")
        respondent = parties.get("respondent")
        if appellant and respondent:
            return f"{appellant} v {respondent}"
        return None
