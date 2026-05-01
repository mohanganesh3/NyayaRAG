"""
NyayaRAG Gold Standard Citation Sentinel
Exhaustive extraction of all Indian legal citation formats from text.
"""
import re
from typing import List, Set, Tuple

from app.ingestion.contracts import CitationCandidate


def normalize_citation(text: str) -> str:
    """Canonical normalization: lowercase, collapse all whitespace."""
    return re.sub(r'\s+', ' ', text.lower().strip())


class StrictCitationSentinel:
    """
    Gold-Standard citation extraction engine for Indian legal documents.
    Covers ALL 12 major citation formats including new neutral citations.
    Case-insensitive. Handles OCR artifacts (newlines, double spaces).
    """

    # ── All Indian Legal Citation Patterns ──────────────────────────────────
    JOURNAL_PATTERNS = {

        # SCC: (2018) 3 SCC 22, (2018)3 SCC 22, 2018 SCC 22, (2006) 5 scc 446
        "SCC": re.compile(
            r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*SCC\s*\d+',
            re.IGNORECASE
        ),

        # AIR: AIR 2024 SC 50, AIR\n2024 SC 50 — all 25 states + SC
        "AIR": re.compile(
            r'AIR[\s\n]+\d{4}[\s\n]+'
            r'(?:SC|Mad|Bom|Del|Cal|Guj|Kar|Ker|MP|Ori|Pat|'
            r'P&H|Raj|All|Gau|HP|J&K|Jhar|Mani|Megh|Sikk|'
            r'Trip|Uttr|AP|TS|CG|Chh|TNHC)\s+\d+',
            re.IGNORECASE
        ),

        # SCR: (2024) 1 SCR 100, [1978] 3 S.C.R. 207
        "SCR": re.compile(
            r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*S\.?C\.?R\.?\s*\d+',
            re.IGNORECASE
        ),

        # SCALE / JT
        "SCALE": re.compile(
            r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*SCALE\s*\d+', re.IGNORECASE
        ),
        "JT": re.compile(
            r'[\(\[]?\d{4}[\)\]]?\s*\d*\s*JT\s*\d+', re.IGNORECASE
        ),

        # ILR: ILR 2019 Delhi 123
        "ILR": re.compile(
            r'ILR[\s\n]+\d{4}[\s\n]+'
            r'(?:Delhi|Bombay|Madras|Calcutta|Allahabad|Rajasthan|'
            r'Karnataka|Kerala|Punjab|Patna|Andhra|Telangana)\s+\d+',
            re.IGNORECASE
        ),

        # Neutral SC new: 2024 INSC 1  or  2024:INSC:1
        "Neutral_SC": re.compile(
            r'\d{4}[\s:]+INSC[\s:]+\d+', re.IGNORECASE
        ),

        # Neutral HC new format: 2023:DHC:2715 (all 25 HCs)
        "Neutral_HC": re.compile(
            r'\d{4}:(?:DHC|MHC|BHC|CHC|GHC|KHC|MPHC|OHC|PHC|RHC|AHC|'
            r'TNHC|TSHC|APHC|UCHC|JKHC|HPHC|JHKHC|GHCHC|CHHCHC|'
            r'SKHC|TRHC|MNHC|LMHC|MMHC):\d+',
            re.IGNORECASE
        ),

        # SCC Online: 2024 SCC OnLine SC 1
        "SCC_Online": re.compile(
            r'\d{4}\s+SCC\s+OnLine\s+'
            r'(?:SC|Mad|Bom|Del|Cal|Guj|Kar|Ker|MP|Ori|Pat|All|Gau|'
            r'HP|J&K|Jhar|AP|TS|CG|Raj|UP)\s+\d+',
            re.IGNORECASE
        ),

        # Manupatra: MANU/SC/0001/2024
        "MANU": re.compile(
            r'MANU/(?:SC|HC|[A-Z]{2})/\d{3,6}/\d{4}',
            re.IGNORECASE
        ),

        # All India Reporter full form: All India Reporter 2024 SC 50
        "AIR_Full": re.compile(
            r'All\s+India\s+Reporter[\s,]+\d{4}[\s,]+'
            r'(?:SC|Supreme Court)\s+\d+',
            re.IGNORECASE
        ),
    }

    # ── Relationship Markers ─────────────────────────────────────────────────
    RELATIONSHIP_MARKERS = [
        ("overrules",    re.compile(r'\boverruled?\b|\breversed?\b|\boverruling\b', re.IGNORECASE)),
        ("distinguishes",re.compile(r'\bdistinguished?\b|\bdistinguish\b', re.IGNORECASE)),
        ("follows",      re.compile(r'\bfollowed?\b|\bfollows\b|\brelied\s+on\b|\bapplied\b', re.IGNORECASE)),
        ("approves",     re.compile(r'\bapproved?\b|\bapproves\b', re.IGNORECASE)),
        ("disapproves",  re.compile(r'\bdisapproved?\b|\bdisapproves\b', re.IGNORECASE)),
        ("doubts",       re.compile(r'\bdoubted?\b|\bdoubts\b', re.IGNORECASE)),
        ("explains",     re.compile(r'\bexplained?\b|\bexplains\b|\bclarified?\b', re.IGNORECASE)),
        ("affirms",      re.compile(r'\baffirmed?\b|\baffirms\b', re.IGNORECASE)),
    ]

    # ── Case Name: "Name v. Name" or "Name vs. Name" ─────────────────────────
    CASE_NAME_PATTERN = re.compile(
        r'([A-Z][A-Za-z0-9 .,&\'-]{2,60?}\s+[Vv](?:s\.?|\.?)\s+[A-Z][A-Za-z0-9 .,&\'-]{2,60})'
    )

    def extract_all(self, text: str) -> List[CitationCandidate]:
        """
        Exhaustive scan of text for all citation patterns.
        Returns deduplicated CitationCandidates with normalized citation_text.
        """
        candidates: List[CitationCandidate] = []
        seen_keys: Set[str] = set()

        # Step 1: Find all matches across all patterns
        matches = []
        for journal, pattern in self.JOURNAL_PATTERNS.items():
            for match in pattern.finditer(text):
                matches.append((match.start(), match.end(), match.group(), journal))

        matches.sort()  # Process in document order

        for start, end, raw_citation, journal in matches:
            # Normalize the extracted citation text for consistent DB lookup
            citation_normalized = normalize_citation(raw_citation)

            # Deduplicate by normalized citation text
            if citation_normalized in seen_keys:
                continue
            seen_keys.add(citation_normalized)

            # Context window for case name and relationship
            window_start = max(0, start - 200)
            window_end = min(len(text), end + 100)
            context_window = text[window_start:window_end]

            # Extract case name from context
            case_match = self.CASE_NAME_PATTERN.search(context_window)
            case_name = case_match.group(1).strip() if case_match else None

            # Classify relationship from pre-citation context
            citation_type = "refers_to"
            pre_context = text[max(0, start - 150):start]
            for rel_type, rel_pattern in self.RELATIONSHIP_MARKERS:
                if rel_pattern.search(pre_context):
                    citation_type = rel_type
                    break

            candidates.append(CitationCandidate(
                raw_text=text[window_start:window_end],
                case_name=case_name,
                citation_text=citation_normalized,   # Always normalized
                citation_type=citation_type,
            ))

        return candidates
