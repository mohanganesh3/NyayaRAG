from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as date_value

from sqlalchemy.orm import Session

from app.models import CRIMINAL_CODE_CUTOVER, CaseContext, CaseType
from app.schemas import (
    PipelineType,
    PracticeArea,
    QueryAnalysis,
    QueryEntity,
    QueryEntityType,
    QueryType,
)
from app.services.criminal_code_mappings import CriminalCodeMappingResolver


@dataclass(frozen=True)
class CourtDescriptor:
    canonical_name: str
    state: str
    binding_targets: tuple[str, ...]
    patterns: tuple[str, ...]


_SUPREME_COURT = CourtDescriptor(
    canonical_name="Supreme Court of India",
    state="All India",
    binding_targets=("All India",),
    patterns=(r"\bsupreme court(?: of india)?\b", r"\bsc\b"),
)

_HIGH_COURTS: tuple[CourtDescriptor, ...] = (
    CourtDescriptor(
        "Allahabad High Court",
        "Uttar Pradesh",
        ("Allahabad High Court",),
        (r"\ballahabad(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Andhra Pradesh High Court",
        "Andhra Pradesh",
        ("Andhra Pradesh High Court",),
        (r"\bandhra pradesh(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Bombay High Court",
        "Maharashtra",
        ("Bombay High Court",),
        (r"\bbombay(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Calcutta High Court",
        "West Bengal",
        ("Calcutta High Court",),
        (r"\bcalcutta(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Chhattisgarh High Court",
        "Chhattisgarh",
        ("Chhattisgarh High Court",),
        (r"\bchhattisgarh(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Delhi High Court", "Delhi", ("Delhi High Court",), (r"\bdelhi(?: high court| hc)\b",)
    ),
    CourtDescriptor(
        "Gauhati High Court", "Assam", ("Gauhati High Court",), (r"\bgauhati(?: high court| hc)\b",)
    ),
    CourtDescriptor(
        "Gujarat High Court",
        "Gujarat",
        ("Gujarat High Court",),
        (r"\bgujarat(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Himachal Pradesh High Court",
        "Himachal Pradesh",
        ("Himachal Pradesh High Court",),
        (r"\bhimachal pradesh(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "High Court of Jammu and Kashmir and Ladakh",
        "Jammu and Kashmir",
        ("High Court of Jammu and Kashmir and Ladakh",),
        (
            r"\bjammu(?: and)? kashmir(?: and ladakh)?(?: high court| hc)\b",
            r"\bladakh(?: high court| hc)\b",
        ),
    ),
    CourtDescriptor(
        "Jharkhand High Court",
        "Jharkhand",
        ("Jharkhand High Court",),
        (r"\bjharkhand(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Karnataka High Court",
        "Karnataka",
        ("Karnataka High Court",),
        (r"\bkarnataka(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Kerala High Court", "Kerala", ("Kerala High Court",), (r"\bkerala(?: high court| hc)\b",)
    ),
    CourtDescriptor(
        "Madras High Court",
        "Tamil Nadu",
        ("Madras High Court",),
        (r"\bmadras(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Madhya Pradesh High Court",
        "Madhya Pradesh",
        ("Madhya Pradesh High Court",),
        (r"\bmadhya pradesh(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Manipur High Court",
        "Manipur",
        ("Manipur High Court",),
        (r"\bmanipur(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Meghalaya High Court",
        "Meghalaya",
        ("Meghalaya High Court",),
        (r"\bmeghalaya(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Orissa High Court",
        "Odisha",
        ("Orissa High Court",),
        (r"\borissa(?: high court| hc)\b", r"\bodisha(?: high court| hc)\b"),
    ),
    CourtDescriptor(
        "Patna High Court", "Bihar", ("Patna High Court",), (r"\bpatna(?: high court| hc)\b",)
    ),
    CourtDescriptor(
        "Punjab and Haryana High Court",
        "Punjab and Haryana",
        ("Punjab and Haryana High Court",),
        (r"\bpunjab and haryana(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Rajasthan High Court",
        "Rajasthan",
        ("Rajasthan High Court",),
        (r"\brajasthan(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Sikkim High Court", "Sikkim", ("Sikkim High Court",), (r"\bsikkim(?: high court| hc)\b",)
    ),
    CourtDescriptor(
        "Telangana High Court",
        "Telangana",
        ("Telangana High Court",),
        (r"\btelangana(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Tripura High Court",
        "Tripura",
        ("Tripura High Court",),
        (r"\btripura(?: high court| hc)\b",),
    ),
    CourtDescriptor(
        "Uttarakhand High Court",
        "Uttarakhand",
        ("Uttarakhand High Court",),
        (r"\buttarakhand(?: high court| hc)\b",),
    ),
)

_TRIBUNALS: tuple[CourtDescriptor, ...] = (
    CourtDescriptor(
        "National Company Law Tribunal",
        "All India",
        ("National Company Law Tribunal",),
        (r"\bnclt\b", r"\bnational company law tribunal\b"),
    ),
    CourtDescriptor(
        "National Company Law Appellate Tribunal",
        "All India",
        ("National Company Law Appellate Tribunal",),
        (r"\bnclat\b", r"\bnational company law appellate tribunal\b"),
    ),
    CourtDescriptor(
        "Income Tax Appellate Tribunal",
        "All India",
        ("Income Tax Appellate Tribunal",),
        (r"\bitat\b", r"\bincome tax appellate tribunal\b"),
    ),
    CourtDescriptor(
        "National Green Tribunal",
        "All India",
        ("National Green Tribunal",),
        (r"\bngt\b", r"\bnational green tribunal\b"),
    ),
    CourtDescriptor(
        "Central Administrative Tribunal",
        "All India",
        ("Central Administrative Tribunal",),
        (r"\bcat\b", r"\bcentral administrative tribunal\b"),
    ),
    CourtDescriptor(
        "Telecom Disputes Settlement and Appellate Tribunal",
        "All India",
        ("Telecom Disputes Settlement and Appellate Tribunal",),
        (r"\btdsat\b", r"\btelecom disputes settlement and appellate tribunal\b"),
    ),
)

_COURTS: tuple[CourtDescriptor, ...] = (_SUPREME_COURT, *_HIGH_COURTS, *_TRIBUNALS)

_CASE_NAME_PATTERN = re.compile(
    r"("
    r"[A-Z][A-Za-z0-9.&'()/,-]*"
    r"(?:\s+(?:[A-Z][A-Za-z0-9.&'()/,-]*|of|and|the|an|for|in))*"
    r"\s+v(?:\.|s\.?|ersus)?\s+"
    r"[A-Z][A-Za-z0-9.&'()/,-]*"
    r"(?:\s+(?:[A-Z][A-Za-z0-9.&'()/,-]*|of|and|the|an|for|in))*"
    r")"
)
_CITATION_PATTERN = re.compile(
    r"\b(?:AIR\s+\d{4}\s+[A-Z]{1,4}\s+\d+|\(\d{4}\)\s+\d+\s+[A-Z]{2,10}\s+\d+)\b"
)
_CRIMINAL_SECTION_PATTERN = re.compile(
    r"\b(?:section\s+)?(?P<section>\d+[A-Z]?)\s*(?P<code>IPC|CRPC|BNS|BNSS|BSA)\b",
    re.IGNORECASE,
)
_CRIMINAL_CODE_FIRST_PATTERN = re.compile(
    r"\b(?P<code>IPC|CRPC|BNS|BNSS|BSA)\s+(?P<section>\d+[A-Z]?)\b",
    re.IGNORECASE,
)
_ARTICLE_PATTERN = re.compile(r"\barticle\s+(?P<section>\d+[A-Z]?)\b", re.IGNORECASE)
_ACT_SECTION_PATTERN = re.compile(
    r"\b(?:section\s+)?(?P<section>\d+[A-Z]?)\s+(?P<act>(?:[A-Z][A-Za-z.&]*(?:\s+[A-Z][A-Za-z.&]*)*)\s+Act)\b",
    re.IGNORECASE,
)
_ACT_NAME_PATTERN = re.compile(
    r"\b(?:Constitution of India|"
    r"[A-Z][A-Za-z.&]*(?:\s+[A-Z][A-Za-z.&]*)*\s+(?:Act|Code|Sanhita))\b",
    re.IGNORECASE,
)


class QueryRouter:
    def __init__(self, resolver: CriminalCodeMappingResolver | None = None) -> None:
        self.resolver = resolver or CriminalCodeMappingResolver()

    def analyze(
        self,
        query: str,
        *,
        session: Session | None = None,
        case_context: CaseContext | None = None,
        reference_date: date_value | None = None,
        has_uploaded_docs: bool | None = None,
    ) -> QueryAnalysis:
        effective_date = reference_date or date_value.today()
        normalized_query = self._normalize_query(query)
        uploaded_docs_present = self._has_uploaded_docs(
            case_context=case_context,
            has_uploaded_docs=has_uploaded_docs,
        )
        sections = self._extract_sections(query)
        bnss_equivalents = self._expand_bns_equivalents(
            session=session,
            sections=sections,
            reference_date=effective_date,
        )
        entities = self._extract_entities(query, sections)
        jurisdiction = self._extract_jurisdiction(query, case_context)
        practice_area = self._classify_practice_area(query, case_context, sections)
        requires_comparison = self._requires_comparison(normalized_query, entities)
        requires_multi_hop = self._requires_multi_hop(normalized_query)
        is_vague = self._is_vague_query(query, sections, entities)
        query_type, confidence = self._classify_query_type(
            query=query,
            normalized_query=normalized_query,
            sections=sections,
            entities=entities,
            uploaded_docs_present=uploaded_docs_present,
            requires_comparison=requires_comparison,
            requires_multi_hop=requires_multi_hop,
            is_vague=is_vague,
        )
        selected_pipeline, pipeline_reason = self._route_query(query_type=query_type)
        post_july_2024 = effective_date >= CRIMINAL_CODE_CUTOVER or any(
            reference.startswith(("BNS ", "BNSS ", "BSA "))
            for reference in (*sections, *bnss_equivalents)
        )
        time_sensitive = self._is_time_sensitive(normalized_query, sections, bnss_equivalents)

        return QueryAnalysis(
            raw_query=query,
            normalized_query=normalized_query,
            query_type=query_type,
            confidence=confidence,
            jurisdiction_court=jurisdiction.canonical_name,
            jurisdiction_state=jurisdiction.state,
            jurisdiction_binding=list(jurisdiction.binding_targets),
            time_sensitive=time_sensitive,
            reference_date=effective_date,
            post_july_2024=post_july_2024,
            practice_area=practice_area,
            sections_mentioned=sections,
            bnss_equivalents=bnss_equivalents,
            entities=entities,
            is_vague=is_vague,
            requires_multi_hop=requires_multi_hop,
            requires_comparison=requires_comparison,
            has_uploaded_docs=uploaded_docs_present,
            selected_pipeline=selected_pipeline,
            pipeline_reason=pipeline_reason,
        )

    def _normalize_query(self, query: str) -> str:
        return " ".join(re.sub(r"[^\w\s./-]", " ", query.lower()).split())

    def _has_uploaded_docs(
        self,
        *,
        case_context: CaseContext | None,
        has_uploaded_docs: bool | None,
    ) -> bool:
        if has_uploaded_docs is not None:
            return has_uploaded_docs
        if case_context is None:
            return False
        return bool(case_context.uploaded_docs)

    def _extract_sections(self, query: str) -> list[str]:
        results: list[str] = []
        seen: set[str] = set()

        for match in _CRIMINAL_SECTION_PATTERN.finditer(query):
            code = self._format_code(match.group("code"))
            section = match.group("section").upper()
            reference = f"{code} {section}"
            if reference not in seen:
                seen.add(reference)
                results.append(reference)

        for match in _CRIMINAL_CODE_FIRST_PATTERN.finditer(query):
            code = self._format_code(match.group("code"))
            section = match.group("section").upper()
            reference = f"{code} {section}"
            if reference not in seen:
                seen.add(reference)
                results.append(reference)

        for match in _ARTICLE_PATTERN.finditer(query):
            reference = f"Article {match.group('section').upper()}"
            if reference not in seen:
                seen.add(reference)
                results.append(reference)

        for match in _ACT_SECTION_PATTERN.finditer(query):
            act = self._format_act_name(match.group("act"))
            reference = f"{act} {match.group('section').upper()}"
            if reference not in seen:
                seen.add(reference)
                results.append(reference)

        return results

    def _expand_bns_equivalents(
        self,
        *,
        session: Session | None,
        sections: list[str],
        reference_date: date_value,
    ) -> list[str]:
        if session is None:
            return []

        criminal_refs = [
            reference
            for reference in sections
            if reference.startswith(
                ("IPC ", "CrPC ", "Indian Evidence Act ", "BNS ", "BNSS ", "BSA ")
            )
        ]
        if not criminal_refs:
            return []

        expanded = self.resolver.expand_references_for_query(
            session,
            criminal_refs,
            reference_date=reference_date,
        )
        originals = set(criminal_refs)
        return [
            reference
            for reference in expanded
            if reference not in originals and reference.startswith(("BNS ", "BNSS ", "BSA "))
        ]

    def _extract_entities(self, query: str, sections: list[str]) -> list[QueryEntity]:
        entities: list[QueryEntity] = []
        seen: set[tuple[QueryEntityType, str]] = set()

        for case_name in _CASE_NAME_PATTERN.findall(query):
            self._append_entity(
                entities,
                seen,
                QueryEntityType.CASE_NAME,
                self._clean_case_name(case_name),
            )

        for court in _COURTS:
            for pattern in court.patterns:
                if re.search(pattern, query, flags=re.IGNORECASE):
                    self._append_entity(
                        entities,
                        seen,
                        QueryEntityType.COURT,
                        court.canonical_name,
                    )
                    break

        for section in sections:
            entity_type = (
                QueryEntityType.ARTICLE
                if section.startswith("Article ")
                else QueryEntityType.SECTION
            )
            self._append_entity(entities, seen, entity_type, section)

        for match in _ACT_NAME_PATTERN.findall(query):
            self._append_entity(
                entities,
                seen,
                QueryEntityType.ACT,
                self._format_act_name(match),
            )

        return entities

    def _append_entity(
        self,
        entities: list[QueryEntity],
        seen: set[tuple[QueryEntityType, str]],
        entity_type: QueryEntityType,
        text: str,
    ) -> None:
        key = (entity_type, text)
        if key in seen:
            return
        seen.add(key)
        entities.append(QueryEntity(text=text, entity_type=entity_type))

    def _extract_jurisdiction(
        self,
        query: str,
        case_context: CaseContext | None,
    ) -> CourtDescriptor:
        query_match = self._resolve_court_descriptor(query)
        if query_match is not None:
            return query_match

        if case_context and case_context.court:
            context_match = self._resolve_court_descriptor(case_context.court)
            if context_match is not None:
                return context_match
            return CourtDescriptor(
                canonical_name=case_context.court,
                state="All India",
                binding_targets=(case_context.court,),
                patterns=(),
            )

        return CourtDescriptor(
            canonical_name="All India",
            state="All India",
            binding_targets=("All India",),
            patterns=(),
        )

    def _resolve_court_descriptor(self, text: str) -> CourtDescriptor | None:
        for court in _COURTS:
            if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in court.patterns):
                return court
        return None

    def _classify_practice_area(
        self,
        query: str,
        case_context: CaseContext | None,
        sections: list[str],
    ) -> PracticeArea:
        lowered = query.lower()
        section_blob = " ".join(sections)

        criminal_signals = (
            "bail",
            "fir",
            "charge sheet",
            "anticipatory bail",
            "murder",
            "rape",
            "criminal",
            "custody",
        )
        constitutional_signals = (
            "article ",
            "fundamental right",
            "constitutional",
            "privacy",
            "due process",
            "article 14",
            "article 19",
            "article 21",
        )
        property_signals = (
            "landlord",
            "tenant",
            "eviction",
            "possession",
            "specific relief",
            "land record",
        )
        family_signals = (
            "divorce",
            "custody",
            "maintenance",
            "matrimonial",
            "alimony",
            "domestic violence",
        )
        tax_signals = ("income tax", "gst", "pcit", "itat", "tax")
        corporate_signals = ("company", "ibc", "insolvency", "nclt", "nclat", "sebi", "shareholder")
        labour_signals = ("labour", "industrial dispute", "wages", "gratuity", "pf", "employment")
        arbitration_signals = ("arbitration", "arbitral", "award", "section 34")
        consumer_signals = ("consumer", "deficiency in service", "consumer commission")

        if any(signal in lowered for signal in constitutional_signals):
            return PracticeArea.CONSTITUTIONAL
        if any(signal in lowered for signal in criminal_signals) or section_blob.startswith(
            ("IPC ", "CrPC ", "BNS ", "BNSS ", "BSA ")
        ):
            return PracticeArea.CRIMINAL
        if any(signal in lowered for signal in property_signals):
            return PracticeArea.PROPERTY
        if any(signal in lowered for signal in family_signals):
            return PracticeArea.FAMILY
        if any(signal in lowered for signal in tax_signals):
            return PracticeArea.TAX
        if any(signal in lowered for signal in corporate_signals):
            return PracticeArea.CORPORATE
        if any(signal in lowered for signal in labour_signals):
            return PracticeArea.LABOUR
        if any(signal in lowered for signal in arbitration_signals):
            return PracticeArea.ARBITRATION
        if any(signal in lowered for signal in consumer_signals):
            return PracticeArea.CONSUMER

        if case_context and case_context.case_type is not None:
            return self._map_case_type(case_context.case_type)

        if "cpc" in lowered or "maintainability" in lowered or "jurisdiction" in lowered:
            return PracticeArea.PROCEDURE
        if "civil" in lowered:
            return PracticeArea.CIVIL
        return PracticeArea.GENERAL

    def _map_case_type(self, case_type: CaseType) -> PracticeArea:
        mapping = {
            CaseType.CRIMINAL: PracticeArea.CRIMINAL,
            CaseType.CIVIL: PracticeArea.CIVIL,
            CaseType.CONSTITUTIONAL: PracticeArea.CONSTITUTIONAL,
            CaseType.FAMILY: PracticeArea.FAMILY,
            CaseType.CORPORATE: PracticeArea.CORPORATE,
            CaseType.TAX: PracticeArea.TAX,
            CaseType.LABOUR: PracticeArea.LABOUR,
            CaseType.PROPERTY: PracticeArea.PROPERTY,
            CaseType.CONSUMER: PracticeArea.CONSUMER,
            CaseType.ARBITRATION: PracticeArea.ARBITRATION,
        }
        return mapping.get(case_type, PracticeArea.GENERAL)

    def _requires_comparison(self, normalized_query: str, entities: list[QueryEntity]) -> bool:
        comparison_terms = (
            " vs ",
            " versus ",
            " compare ",
            " difference between ",
            " how does ",
            " compared to ",
        )
        court_mentions = [
            entity for entity in entities if entity.entity_type is QueryEntityType.COURT
        ]
        return (
            any(term in normalized_query for term in comparison_terms) and len(court_mentions) >= 2
        )

    def _requires_multi_hop(self, normalized_query: str) -> bool:
        multi_hop_terms = (
            "how has",
            "how did",
            "developed",
            "evolved",
            "evolution",
            "current law on",
            "landmark cases",
            "doctrine",
            "line of cases",
            "traced",
        )
        return any(term in normalized_query for term in multi_hop_terms)

    def _is_vague_query(
        self,
        query: str,
        sections: list[str],
        entities: list[QueryEntity],
    ) -> bool:
        if sections:
            return False
        if any(
            entity.entity_type
            in {QueryEntityType.CASE_NAME, QueryEntityType.COURT, QueryEntityType.ACT}
            for entity in entities
        ):
            return False

        lowered = query.lower()
        vague_signals = (
            "what can i do",
            "can i",
            "my landlord",
            "my employer",
            "my husband",
            "my wife",
            "without notice",
            "they arrested",
            "police took",
        )
        return any(signal in lowered for signal in vague_signals)

    def _classify_query_type(
        self,
        *,
        query: str,
        normalized_query: str,
        sections: list[str],
        entities: list[QueryEntity],
        uploaded_docs_present: bool,
        requires_comparison: bool,
        requires_multi_hop: bool,
        is_vague: bool,
    ) -> tuple[QueryType, float]:
        if uploaded_docs_present:
            return QueryType.DOCUMENT_SPECIFIC, 0.99

        if requires_comparison:
            return QueryType.COMPARATIVE, 0.96

        if requires_multi_hop:
            return QueryType.MULTI_HOP_DOCTRINE, 0.93

        if self._is_constitutional_query(normalized_query, sections):
            return QueryType.CONSTITUTIONAL, 0.94

        if self._is_case_specific_query(query, entities):
            return QueryType.CASE_SPECIFIC, 0.95

        if sections:
            return QueryType.STATUTORY_LOOKUP, 0.94

        if is_vague:
            return QueryType.VAGUE_NATURAL, 0.84

        return QueryType.GENERAL_LEGAL, 0.65

    def _is_constitutional_query(self, normalized_query: str, sections: list[str]) -> bool:
        constitutional_terms = (
            "constitutional validity",
            "constitutionally valid",
            "fundamental right",
            "part iii",
            "article 14",
            "article 19",
            "article 21",
            "constitutional challenge",
        )
        return any(term in normalized_query for term in constitutional_terms) or any(
            section.startswith("Article ") for section in sections
        )

    def _is_case_specific_query(self, query: str, entities: list[QueryEntity]) -> bool:
        if _CITATION_PATTERN.search(query):
            return True
        return any(entity.entity_type is QueryEntityType.CASE_NAME for entity in entities)

    def _route_query(self, *, query_type: QueryType) -> tuple[PipelineType, str]:
        if query_type is QueryType.DOCUMENT_SPECIFIC:
            return (
                PipelineType.AGENTIC_RAG,
                "Uploaded case documents require LangGraph document-specific research.",
            )
        if query_type is QueryType.COMPARATIVE:
            return (
                PipelineType.GRAPH_HYBRID,
                "Comparative jurisdiction queries need graph traversal plus retrieval enrichment.",
            )
        if query_type in {QueryType.MULTI_HOP_DOCTRINE, QueryType.CONSTITUTIONAL}:
            return (
                PipelineType.GRAPH_RAG,
                "Doctrine and constitutional queries require citation-graph traversal.",
            )
        if query_type is QueryType.VAGUE_NATURAL:
            return (
                PipelineType.HYDE_HYBRID,
                "Plain-language fact patterns need hypothetical anchoring before hybrid retrieval.",
            )
        if query_type in {QueryType.STATUTORY_LOOKUP, QueryType.CASE_SPECIFIC}:
            return (
                PipelineType.HYBRID_CRAG,
                "Exact statute and named-case queries use hybrid retrieval "
                "with corrective validation.",
            )
        return PipelineType.HYBRID_RAG, "General legal queries default to hybrid retrieval."

    def _is_time_sensitive(
        self,
        normalized_query: str,
        sections: list[str],
        bnss_equivalents: list[str],
    ) -> bool:
        temporal_terms = (
            "today",
            "current law",
            "currently",
            "latest",
            "as of",
            "now",
            "post july 2024",
            "after july 1 2024",
        )
        return (
            any(term in normalized_query for term in temporal_terms)
            or bool(bnss_equivalents)
            or any(
                reference.startswith(("IPC ", "CrPC ", "BNS ", "BNSS ", "BSA "))
                for reference in sections
            )
        )

    def _format_code(self, code: str) -> str:
        normalized = code.upper()
        if normalized == "CRPC":
            return "CrPC"
        return normalized

    def _format_act_name(self, act_name: str) -> str:
        stopwords = {"of", "and", "the"}
        formatted_words: list[str] = []
        for word in act_name.split():
            if word.isupper() and len(word) <= 5:
                formatted_words.append(word)
            elif word.lower() in stopwords:
                formatted_words.append(word.lower())
            else:
                formatted_words.append(word.capitalize())
        return " ".join(formatted_words)

    def _clean_case_name(self, case_name: str) -> str:
        cleaned = re.sub(
            r"^(?:What|How|Whether|Explain|Summari[sz]e|Tell me about)\b.*?\bin\s+",
            "",
            case_name,
            flags=re.IGNORECASE,
        )
        return cleaned.strip()
