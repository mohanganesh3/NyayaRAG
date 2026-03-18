from __future__ import annotations

import re
from datetime import date
from uuid import uuid4

from app.models import CaseContext, CaseStage, CaseType
from app.rag.router import QueryRouter
from app.schemas import PracticeArea
from app.services.criminal_code_mappings import CriminalCodeMappingResolver
from app.services.ocr_cleanup import NormalizedPartyCluster
from app.services.upload_ingestion import ProcessedUploadDocument
from sqlalchemy.orm import Session

_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?P<day>\d{1,2})\s+"
        r"(?P<month>January|February|March|April|May|June|July|August|September|October|"
        r"November|December)\s+"
        r"(?P<year>\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})\b"),
    re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b"),
)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_PETITIONER_LABEL_RE = re.compile(
    r"\b(?:petitioner|appellant|applicant|accused)\b\s*[:.-]\s*"
    r"([A-Za-z0-9&.,' -]{2,100}?)(?=(?:\s+\b(?:petitioner|respondent|appellant|"
    r"applicant|accused|complainant)\b\s*[:.-])|[.!?]|$)",
    re.IGNORECASE,
)
_RESPONDENT_LABEL_RE = re.compile(
    r"\b(?:respondent|opposite party|complainant)\b\s*[:.-]\s*"
    r"([A-Za-z0-9&.,' -]{2,100}?)(?=(?:\s+\b(?:petitioner|respondent|appellant|"
    r"applicant|accused|complainant)\b\s*[:.-])|[.!?]|$)",
    re.IGNORECASE,
)
_ADVOCATE_RE = re.compile(
    r"\b(?:adv\.?|advocate)\s+"
    r"([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}?)(?=(?:\s+for\b)|[.!?,]|$)",
    re.IGNORECASE,
)
_CASE_NUMBER_RE = re.compile(
    r"\b(?:[A-Z]{1,5}|BA|CRA|CRL\.?M\.?|WP|SLP|FA|MA)/\d{1,6}/\d{4}\b",
    re.IGNORECASE,
)
_COURT_RE = re.compile(
    r"\b("
    r"Supreme Court(?: of India)?|"
    r"Bombay High Court|Delhi High Court|Madras High Court|Calcutta High Court|"
    r"Karnataka High Court|Kerala High Court|Allahabad High Court|Patna High Court|"
    r"Rajasthan High Court|Punjab and Haryana High Court|Sessions Court|District Court"
    r")\b",
    re.IGNORECASE,
)
_SECTION_CANONICAL_RE = re.compile(r"^Section\s+([0-9A-Z]+)\s+(.+)$")
_CRIMINAL_CODES = {"IPC", "CrPC", "BNS", "BNSS", "BSA", "Indian Evidence Act"}
_RESPONDENT_HINTS = (
    "state of",
    "union of india",
    "pcit",
    "commissioner",
    "respondent",
    "complainant",
)


class CaseContextBuilder:
    def __init__(
        self,
        *,
        resolver: CriminalCodeMappingResolver | None = None,
        router: QueryRouter | None = None,
    ) -> None:
        self._resolver = resolver or CriminalCodeMappingResolver()
        self._router = router or QueryRouter(resolver=self._resolver)

    def build_from_uploads(
        self,
        session: Session,
        *,
        processed_documents: list[ProcessedUploadDocument],
        case_id: str | None = None,
        court: str | None = None,
        case_number: str | None = None,
    ) -> CaseContext:
        if not processed_documents:
            raise ValueError("At least one processed upload document is required.")

        existing = session.get(CaseContext, case_id) if case_id else None
        context = existing or CaseContext(case_id=case_id or str(uuid4()))

        combined_text = "\n".join(document.extracted_text for document in processed_documents)
        extracted_sections = self._extract_canonical_sections(processed_documents)
        bnss_equivalents = self._resolve_bnss_equivalents(session, extracted_sections)
        all_statutes = self._extract_statutes_involved(extracted_sections, bnss_equivalents)
        all_parties = self._collect_parties(processed_documents)
        petitioner = self._select_petitioner(processed_documents, all_parties)
        respondent = self._select_respondent(processed_documents, all_parties, petitioner)
        advocates = self._extract_advocates(processed_documents)
        derived_case_number = case_number or self._extract_case_number(processed_documents)
        derived_court = court or self._extract_court(session, combined_text)
        case_type = self._infer_case_type(combined_text, extracted_sections, session)
        stage = self._infer_stage(processed_documents, combined_text)
        key_facts = self._extract_key_facts(processed_documents)
        previous_orders = self._extract_previous_orders(processed_documents)
        bail_history = self._extract_bail_history(processed_documents, previous_orders)
        open_legal_issues = self._derive_open_legal_issues(
            stage=stage,
            case_type=case_type,
            charges_sections=extracted_sections,
            previous_orders=previous_orders,
            statutes_involved=all_statutes,
        )

        context.appellant_petitioner = petitioner
        context.respondent_opposite_party = respondent
        context.advocates = advocates
        context.case_type = case_type
        context.court = derived_court
        context.case_number = derived_case_number
        context.stage = stage
        context.charges_sections = extracted_sections
        context.bnss_equivalents = bnss_equivalents
        context.statutes_involved = all_statutes
        context.key_facts = key_facts
        context.previous_orders = previous_orders
        context.bail_history = bail_history
        context.open_legal_issues = open_legal_issues
        context.uploaded_docs = [
            {
                "name": document.file_name,
                "media_type": document.media_type,
                "document_mode": document.document_mode.value,
                "extraction_method": document.extraction_method,
                "page_count": document.page_count,
                "confidence": document.confidence,
                "sections": document.normalized_sections,
                "citations": document.normalized_citations,
            }
            for document in processed_documents
        ]
        context.doc_extraction_confidence = round(
            sum(document.confidence for document in processed_documents) / len(processed_documents),
            3,
        )

        session.add(context)
        session.flush()
        return context

    def get(self, session: Session, case_id: str) -> CaseContext | None:
        return session.get(CaseContext, case_id)

    def _collect_parties(
        self, processed_documents: list[ProcessedUploadDocument]
    ) -> list[NormalizedPartyCluster]:
        clusters: list[NormalizedPartyCluster] = []
        for document in processed_documents:
            for cluster in document.normalized_parties:
                self._merge_party_cluster(clusters, cluster)
        return clusters

    def _merge_party_cluster(
        self, clusters: list[NormalizedPartyCluster], candidate: NormalizedPartyCluster
    ) -> None:
        candidate_key = self._party_key(candidate.canonical_name)
        for index, cluster in enumerate(clusters):
            if self._party_key(cluster.canonical_name) == candidate_key:
                aliases = tuple(dict.fromkeys((*cluster.aliases, *candidate.aliases)))
                canonical_name = max(
                    (cluster.canonical_name, candidate.canonical_name),
                    key=lambda value: (len(value), value),
                )
                clusters[index] = NormalizedPartyCluster(
                    canonical_name=canonical_name,
                    aliases=aliases,
                )
                return
        clusters.append(candidate)

    def _select_petitioner(
        self,
        processed_documents: list[ProcessedUploadDocument],
        parties: list[NormalizedPartyCluster],
    ) -> str | None:
        for document in processed_documents:
            match = _PETITIONER_LABEL_RE.search(document.extracted_text)
            if match:
                return match.group(1).strip(" .")

        for cluster in parties:
            if not self._looks_like_respondent(cluster.canonical_name):
                return cluster.canonical_name
        return parties[0].canonical_name if parties else None

    def _select_respondent(
        self,
        processed_documents: list[ProcessedUploadDocument],
        parties: list[NormalizedPartyCluster],
        petitioner: str | None,
    ) -> str | None:
        for document in processed_documents:
            match = _RESPONDENT_LABEL_RE.search(document.extracted_text)
            if match:
                return match.group(1).strip(" .")

        petitioner_key = self._party_key(petitioner) if petitioner else None
        for cluster in parties:
            if petitioner_key and self._party_key(cluster.canonical_name) == petitioner_key:
                continue
            if self._looks_like_respondent(cluster.canonical_name):
                return cluster.canonical_name

        for cluster in parties:
            if petitioner_key and self._party_key(cluster.canonical_name) == petitioner_key:
                continue
            return cluster.canonical_name
        return None

    def _extract_advocates(
        self, processed_documents: list[ProcessedUploadDocument]
    ) -> list[str]:
        seen: set[str] = set()
        advocates: list[str] = []
        for document in processed_documents:
            for match in _ADVOCATE_RE.finditer(document.extracted_text):
                advocate = match.group(1).strip(" .")
                if advocate not in seen:
                    seen.add(advocate)
                    advocates.append(advocate)
        return advocates

    def _extract_case_number(
        self, processed_documents: list[ProcessedUploadDocument]
    ) -> str | None:
        for document in processed_documents:
            match = _CASE_NUMBER_RE.search(document.extracted_text)
            if match:
                return match.group(0).replace(" ", "")
        return None

    def _extract_court(self, session: Session, combined_text: str) -> str | None:
        analysis = self._router.analyze(
            combined_text[:4000],
            session=session,
            has_uploaded_docs=True,
        )
        if analysis.jurisdiction_court != "All India":
            return analysis.jurisdiction_court

        match = _COURT_RE.search(combined_text)
        if match:
            return self._normalize_court(match.group(1))
        return None

    def _normalize_court(self, value: str) -> str:
        lowered = value.lower()
        if "bombay high court" in lowered:
            return "Bombay High Court"
        if "delhi high court" in lowered:
            return "Delhi High Court"
        if "sessions court" in lowered:
            return "Sessions Court"
        if "supreme court" in lowered:
            return "Supreme Court of India"
        return " ".join(part.capitalize() for part in value.split())

    def _infer_case_type(
        self, combined_text: str, sections: list[str], session: Session
    ) -> CaseType | None:
        combined_lower = combined_text.lower()
        if any(
            section.startswith(("IPC ", "CrPC ", "BNS ", "BNSS ", "BSA "))
            for section in sections
        ):
            return CaseType.CRIMINAL
        if "landlord" in combined_lower or "specific relief act" in combined_lower:
            return CaseType.PROPERTY
        if "divorce" in combined_lower or "maintenance" in combined_lower:
            return CaseType.FAMILY
        if "fundamental right" in combined_lower or "article 21" in combined_lower:
            return CaseType.CONSTITUTIONAL
        if "income tax" in combined_lower or "gst" in combined_lower:
            return CaseType.TAX
        if (
            "company" in combined_lower
            or "insolvency" in combined_lower
            or "nclt" in combined_lower
        ):
            return CaseType.CORPORATE
        if "labour" in combined_lower or "wages" in combined_lower:
            return CaseType.LABOUR
        if "arbitration" in combined_lower or "arbitral" in combined_lower:
            return CaseType.ARBITRATION
        if "consumer" in combined_lower:
            return CaseType.CONSUMER

        analysis = self._router.analyze(
            combined_text[:4000],
            session=session,
            has_uploaded_docs=True,
        )
        return self._practice_area_to_case_type(analysis.practice_area)

    def _practice_area_to_case_type(self, practice_area: PracticeArea) -> CaseType | None:
        mapping = {
            PracticeArea.CRIMINAL: CaseType.CRIMINAL,
            PracticeArea.CIVIL: CaseType.CIVIL,
            PracticeArea.CONSTITUTIONAL: CaseType.CONSTITUTIONAL,
            PracticeArea.FAMILY: CaseType.FAMILY,
            PracticeArea.CORPORATE: CaseType.CORPORATE,
            PracticeArea.TAX: CaseType.TAX,
            PracticeArea.LABOUR: CaseType.LABOUR,
            PracticeArea.PROPERTY: CaseType.PROPERTY,
            PracticeArea.CONSUMER: CaseType.CONSUMER,
            PracticeArea.ARBITRATION: CaseType.ARBITRATION,
        }
        return mapping.get(practice_area)

    def _infer_stage(
        self, processed_documents: list[ProcessedUploadDocument], combined_text: str
    ) -> CaseStage | None:
        lowered = combined_text.lower()
        file_names = " ".join(document.file_name.lower() for document in processed_documents)
        haystack = f"{lowered} {file_names}"

        if "bail" in haystack:
            return CaseStage.BAIL
        if "charge sheet" in haystack or "chargesheet" in haystack:
            return CaseStage.CHARGES
        if "appeal" in haystack:
            return CaseStage.APPEAL
        if "revision" in haystack:
            return CaseStage.REVISION
        if "trial" in haystack:
            return CaseStage.TRIAL
        if "execution" in haystack:
            return CaseStage.EXECUTION
        if "fir" in haystack or "investigation" in haystack:
            return CaseStage.INVESTIGATION
        return None

    def _extract_canonical_sections(
        self, processed_documents: list[ProcessedUploadDocument]
    ) -> list[str]:
        sections: list[str] = []
        seen: set[str] = set()
        for document in processed_documents:
            for section in document.normalized_sections:
                canonical = self._canonicalize_section(section)
                if canonical and canonical not in seen:
                    seen.add(canonical)
                    sections.append(canonical)
        return sections

    def _canonicalize_section(self, section: str) -> str | None:
        match = _SECTION_CANONICAL_RE.match(section)
        if not match:
            return None

        section_number = match.group(1).upper()
        act_name = match.group(2).strip()
        normalized_act = self._normalize_act_name(act_name)
        return f"{normalized_act} {section_number}"

    def _normalize_act_name(self, act_name: str) -> str:
        lowered = act_name.lower()
        if lowered == "crpc":
            return "CrPC"
        if lowered in {"ipc", "bns", "bnss", "bsa"}:
            return act_name.upper()
        if lowered == "indian evidence act":
            return "Indian Evidence Act"
        return act_name

    def _resolve_bnss_equivalents(self, session: Session, sections: list[str]) -> list[str]:
        criminal_sections = [
            section
            for section in sections
            if section.startswith(("IPC ", "CrPC ", "Indian Evidence Act "))
        ]
        if not criminal_sections:
            return []

        expanded = self._resolver.expand_references_for_query(
            session,
            criminal_sections,
            reference_date=date.today(),
        )
        seen = set(sections)
        equivalents: list[str] = []
        for section in expanded:
            if section.startswith(("BNS ", "BNSS ", "BSA ")) and section not in seen:
                seen.add(section)
                equivalents.append(section)
        return equivalents

    def _extract_statutes_involved(
        self, sections: list[str], equivalents: list[str]
    ) -> list[str]:
        statutes: list[str] = []
        seen: set[str] = set()
        for section in (*sections, *equivalents):
            statute = self._statute_name_from_section(section)
            if statute not in seen:
                seen.add(statute)
                statutes.append(statute)
        return statutes

    def _statute_name_from_section(self, section: str) -> str:
        if " " not in section:
            return section
        return section.rsplit(" ", 1)[0]

    def _extract_key_facts(
        self, processed_documents: list[ProcessedUploadDocument]
    ) -> list[dict[str, object]]:
        facts: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for document in processed_documents:
            for sentence in self._split_sentences(document.extracted_text):
                parsed_date = self._parse_date(sentence)
                if parsed_date is None:
                    continue
                fact = sentence.strip()
                key = (parsed_date.isoformat(), fact)
                if key in seen:
                    continue
                seen.add(key)
                facts.append(
                    {
                        "date": parsed_date.isoformat(),
                        "fact": fact,
                        "source_doc": document.file_name,
                    }
                )
        return sorted(facts, key=lambda item: str(item["date"]))

    def _extract_previous_orders(
        self, processed_documents: list[ProcessedUploadDocument]
    ) -> list[dict[str, object]]:
        previous_orders: list[dict[str, object]] = []
        for document in processed_documents:
            for sentence in self._split_sentences(document.extracted_text):
                lowered = sentence.lower()
                if not any(
                    term in lowered
                    for term in ("order", "rejected", "dismissed", "allowed", "granted")
                ):
                    continue
                order_date = self._parse_date(sentence)
                previous_orders.append(
                    {
                        "court": self._extract_inline_court(sentence),
                        "outcome": self._extract_outcome(sentence),
                        "date": order_date.isoformat() if order_date else None,
                        "summary": sentence.strip(),
                        "source_doc": document.file_name,
                    }
                )
        return previous_orders

    def _extract_bail_history(
        self,
        processed_documents: list[ProcessedUploadDocument],
        previous_orders: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        bail_entries: list[dict[str, object]] = []
        for order in previous_orders:
            summary = str(order.get("summary", "")).lower()
            if "bail" not in summary and "ba/" not in summary:
                continue
            bail_entries.append(
                {
                    "date": order.get("date"),
                    "status": order.get("outcome") or "pending",
                    "summary": order.get("summary"),
                }
            )

        for document in processed_documents:
            if "bail" not in document.extracted_text.lower():
                continue
            if not bail_entries:
                bail_entries.append(
                    {
                        "date": None,
                        "status": "pending",
                        "summary": f"Bail proceedings referenced in {document.file_name}.",
                    }
                )
        return bail_entries

    def _derive_open_legal_issues(
        self,
        *,
        stage: CaseStage | None,
        case_type: CaseType | None,
        charges_sections: list[str],
        previous_orders: list[dict[str, object]],
        statutes_involved: list[str],
    ) -> list[str]:
        issues: list[str] = []
        if stage is CaseStage.BAIL:
            charges = (
                ", ".join(charges_sections[:2])
                if charges_sections
                else "the alleged offences"
            )
            issues.append(f"Whether bail should be granted for {charges}.")
            if any(
                str(order.get("outcome", "")).lower() == "rejected"
                for order in previous_orders
            ):
                issues.append(
                    "Whether changed circumstances justify bail after the earlier rejection order."
                )
        elif case_type is CaseType.PROPERTY and any(
            statute.startswith("Specific Relief Act") for statute in statutes_involved
        ):
            issues.append("Whether possession must be restored under the Specific Relief Act.")
        elif charges_sections:
            issues.append(f"What relief is available under {charges_sections[0]}?")
        return issues

    def _extract_inline_court(self, sentence: str) -> str | None:
        match = _COURT_RE.search(sentence)
        if match:
            return self._normalize_court(match.group(1))
        return None

    def _extract_outcome(self, sentence: str) -> str | None:
        lowered = sentence.lower()
        if "rejected" in lowered:
            return "rejected"
        if "dismissed" in lowered:
            return "dismissed"
        if "granted" in lowered or "allowed" in lowered:
            return "granted"
        return None

    def _split_sentences(self, text: str) -> list[str]:
        return [
            segment.strip()
            for segment in re.split(r"(?<=[.!?])\s+", text)
            if segment.strip()
        ]

    def _parse_date(self, text: str) -> date | None:
        for pattern in _DATE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            year = int(match.group("year"))
            month_token = match.group("month")
            month = int(month_token) if month_token.isdigit() else _MONTHS[month_token.lower()]
            day = int(match.group("day"))
            return date(year, month, day)
        return None

    def _party_key(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    def _looks_like_respondent(self, value: str) -> bool:
        lowered = value.lower()
        return any(hint in lowered for hint in _RESPONDENT_HINTS)


case_context_builder = CaseContextBuilder()
