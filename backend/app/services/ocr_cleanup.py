from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

_LEGAL_REPLACEMENTS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\bsectl[o0]n\b", re.IGNORECASE), "Section", "section_spelling"),
    (re.compile(r"\bsecti[o0]n\b", re.IGNORECASE), "Section", "section_spelling"),
    (re.compile(r"\bsecfion\b", re.IGNORECASE), "Section", "section_spelling"),
    (re.compile(r"\bartlcle\b", re.IGNORECASE), "Article", "article_spelling"),
    (re.compile(r"\bpetltloner\b", re.IGNORECASE), "petitioner", "party_label_spelling"),
    (re.compile(r"\brespondent\b", re.IGNORECASE), "respondent", "party_label_spelling"),
    (re.compile(r"\bappeliant\b", re.IGNORECASE), "appellant", "party_label_spelling"),
    (re.compile(r"\bcomplalnant\b", re.IGNORECASE), "complainant", "party_label_spelling"),
    (re.compile(r"\bA1R\b"), "AIR", "air_reporter"),
    (re.compile(r"\b0nLine\b", re.IGNORECASE), "OnLine", "online_reporter"),
)

_CODE_ALIASES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        {
            "ipc": "IPC",
            "lpc": "IPC",
            "indian penal code": "IPC",
            "crpc": "CrPC",
            "code of criminal procedure": "CrPC",
            "bnss": "BNSS",
            "bns": "BNS",
            "bsa": "BSA",
            "specific relief act": "Specific Relief Act",
            "constitution of india": "Constitution of India",
        }.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)

_SECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(
        rf"(?i)\b(?:u/s|u\.s\.|section|sec\.?)\s*([0-9OIl]{{1,4}}[A-Z]?)\s*{re.escape(alias)}\b"
    )
    for alias, _ in _CODE_ALIASES
)

_AIR_CITATION_RE = re.compile(r"\bAIR\s+([0-9OIl]{4})\s+([A-Za-z]{2,5})\s+([0-9OIl]{1,5})\b")
_SCC_CITATION_RE = re.compile(r"\(([0-9OIl]{4})\)\s*([0-9OIl]{1,3})\s*SCC\s+([0-9OIl]{1,5})\b")
_SCC_ONLINE_RE = re.compile(
    r"\b([0-9OIl]{4})\s*SCC\s*OnLine\s*([A-Za-z]{1,5})\s*([0-9OIl]{1,6})\b",
    re.IGNORECASE,
)
_CASE_STYLE_RE = re.compile(
    r"([A-Z][A-Za-z0-9&.,' -]{1,80}?)\s+(?:v\.|vs\.?|versus)\s+"
    r"([A-Z][A-Za-z0-9&.,' -]{1,80}?)(?=[.,]|$)"
)
_PARTY_LABEL_RE = re.compile(
    r"\b(?:petitioner|respondent|appellant|complainant)\b\s*[:.-]\s*"
    r"([A-Za-z0-9&.,' -]{2,100}?)(?=(?:\s+\b(?:petitioner|respondent|appellant|complainant)"
    r"\b\s*[:.-])|$)",
    re.IGNORECASE,
)
_CORPORATE_SUFFIX_RE = re.compile(
    r"\b(private limited|pvt\.?\s*ltd\.?|limited|ltd\.?)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class NormalizedPartyCluster:
    canonical_name: str
    aliases: tuple[str, ...]


@dataclass(slots=True)
class LegalTextNormalizationResult:
    raw_text: str
    normalized_text: str
    normalized_citations: tuple[str, ...]
    normalized_sections: tuple[str, ...]
    normalized_parties: tuple[NormalizedPartyCluster, ...]
    corrections_applied: tuple[str, ...]


class LegalTextNormalizer:
    def normalize(self, text: str) -> LegalTextNormalizationResult:
        raw_text = " ".join(text.split())
        normalized_text = raw_text
        corrections: list[str] = []

        for pattern, replacement, label in _LEGAL_REPLACEMENTS:
            updated_text, replaced_count = pattern.subn(replacement, normalized_text)
            if replaced_count:
                normalized_text = updated_text
                corrections.append(label)

        normalized_text = self._normalize_case_style(normalized_text)
        normalized_text, sections = self._normalize_sections(normalized_text)
        normalized_text, citations = self._normalize_citations(normalized_text)
        parties = self._deduplicate_parties(self._extract_parties(normalized_text))

        return LegalTextNormalizationResult(
            raw_text=raw_text,
            normalized_text=normalized_text,
            normalized_citations=tuple(citations),
            normalized_sections=tuple(sections),
            normalized_parties=tuple(parties),
            corrections_applied=tuple(dict.fromkeys(corrections)),
        )

    def _normalize_case_style(self, text: str) -> str:
        return re.sub(r"\b(vs\.?|versus)\b", "v.", text, flags=re.IGNORECASE)

    def _normalize_sections(self, text: str) -> tuple[str, list[str]]:
        normalized_sections: list[str] = []
        updated_text = text

        for pattern, (_, display_code) in zip(_SECTION_PATTERNS, _CODE_ALIASES, strict=True):
            def replacer(match: re.Match[str], display_code: str = display_code) -> str:
                section = self._normalize_numeric_token(match.group(1)).upper()
                rendered = f"Section {section} {display_code}"
                normalized_sections.append(rendered)
                return rendered

            updated_text = pattern.sub(replacer, updated_text)

        return updated_text, self._unique_preserve_order(normalized_sections)

    def _normalize_citations(self, text: str) -> tuple[str, list[str]]:
        citations: list[str] = []
        updated_text = text

        def air_replacer(match: re.Match[str]) -> str:
            citation = (
                f"AIR {self._normalize_numeric_token(match.group(1))} "
                f"{match.group(2).upper()} {self._normalize_numeric_token(match.group(3))}"
            )
            citations.append(citation)
            return citation

        def scc_replacer(match: re.Match[str]) -> str:
            citation = (
                f"({self._normalize_numeric_token(match.group(1))}) "
                f"{self._normalize_numeric_token(match.group(2))} SCC "
                f"{self._normalize_numeric_token(match.group(3))}"
            )
            citations.append(citation)
            return citation

        def scc_online_replacer(match: re.Match[str]) -> str:
            citation = (
                f"{self._normalize_numeric_token(match.group(1))} SCC OnLine "
                f"{match.group(2).upper()} {self._normalize_numeric_token(match.group(3))}"
            )
            citations.append(citation)
            return citation

        updated_text = _AIR_CITATION_RE.sub(air_replacer, updated_text)
        updated_text = _SCC_CITATION_RE.sub(scc_replacer, updated_text)
        updated_text = _SCC_ONLINE_RE.sub(scc_online_replacer, updated_text)

        return updated_text, self._unique_preserve_order(citations)

    def _extract_parties(self, text: str) -> list[str]:
        parties: list[str] = []
        for match in _CASE_STYLE_RE.finditer(text):
            parties.extend([match.group(1), match.group(2)])
        for match in _PARTY_LABEL_RE.finditer(text):
            parties.append(match.group(1))
        cleaned_parties = [self._clean_party_alias(party) for party in parties]
        return [party for party in cleaned_parties if party]

    def _deduplicate_parties(self, parties: list[str]) -> list[NormalizedPartyCluster]:
        clusters: list[list[str]] = []
        for party in parties:
            added = False
            for cluster in clusters:
                if self._is_same_party(cluster[0], party):
                    if party not in cluster:
                        cluster.append(party)
                    added = True
                    break
            if not added:
                clusters.append([party])

        deduped: list[NormalizedPartyCluster] = []
        for cluster in clusters:
            canonical = max(cluster, key=lambda candidate: (len(candidate), candidate))
            deduped.append(
                NormalizedPartyCluster(
                    canonical_name=canonical,
                    aliases=tuple(cluster),
                )
            )
        return deduped

    def _is_same_party(self, left: str, right: str) -> bool:
        left_key = self._party_compare_key(left)
        right_key = self._party_compare_key(right)
        if left_key == right_key:
            return True
        return SequenceMatcher(a=left_key, b=right_key).ratio() >= 0.84

    def _party_compare_key(self, value: str) -> str:
        lowered = value.lower().replace("0", "o").replace("1", "l")
        lowered = lowered.replace("v", "u")
        lowered = _CORPORATE_SUFFIX_RE.sub("", lowered)
        lowered = re.sub(r"[^a-z0-9]+", "", lowered)
        return lowered

    def _clean_party_alias(self, value: str) -> str:
        cleaned = " ".join(value.replace(" ,", ",").split()).strip(" ,.-")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def _normalize_numeric_token(self, token: str) -> str:
        translation = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"})
        return token.translate(translation)

    def _unique_preserve_order(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                ordered.append(value)
        return ordered
