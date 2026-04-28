import re

_NEGATION_PATTERNS = [
    r"\bnot\b", r"\bnever\b", r"\bfails\b", r"\bcannot\b", r"\bdenied\b",
    r"\bwithout\b", r"\bno\b", r"\bnone\b", r"\bimpossible\b", r"\bunavailable\b"
]

def detect_negation_mismatch(claim: str, passage: str) -> bool:
    claim_neg = any(re.search(p, claim.lower()) for p in _NEGATION_PATTERNS)
    passage_neg = any(re.search(p, passage.lower()) for p in _NEGATION_PATTERNS)
    return claim_neg != passage_neg

def calculate_legal_overlap(claim_tokens: set[str], passage_tokens: set[str]) -> float:
    shared = claim_tokens & passage_tokens
    if not claim_tokens: return 0.0
    # Weighted overlap: tokens like 'held', 'judgment', 'section' are higher value in Unit 5.2
    return len(shared) / len(claim_tokens)
