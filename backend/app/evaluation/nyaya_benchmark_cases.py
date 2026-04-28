from dataclasses import dataclass
from enum import StrEnum

class EvalCategory(StrEnum):
    LANDMARK = "landmark"
    OVERRULED_TRAP = "overruled_trap"
    LAW_TRANSITION = "law_transition"
    APPEAL_CHAIN = "appeal_chain"
    JURISDICTION = "jurisdiction"
    MULTI_HOP = "multi_hop"

@dataclass(slots=True)
class BenchmarkCase:
    query: str
    target_doc_id: str | None
    ground_truth_citation: str
    expected_answer_elements: list[str]
    category: EvalCategory
    jurisdiction: str = "All India"

NYAYA_BENCHMARK_CASES = [
    # LANDMARK CITATIONS
    BenchmarkCase(
        query="What was the ruling in Kesavananda Bharati Sripadagalvaru v. State of Kerala regarding the basic structure of the Constitution?",
        target_doc_id=None,
        ground_truth_citation="1973 4 SCC 225",
        expected_answer_elements=["Basic Structure Doctrine", "cannot be amended by Parliament", "Art 368"],
        category=EvalCategory.LANDMARK
    ),
    BenchmarkCase(
        query="Right to privacy is a fundamental right under which article according to Justice K.S. Puttaswamy v. Union of India?",
        target_doc_id=None,
        ground_truth_citation="2017 10 SCC 1",
        expected_answer_elements=["Article 21", "Fundamental Right", "Privacy"],
        category=EvalCategory.LANDMARK
    ),
    
    # OVERRULED LAW TRAPS
    BenchmarkCase(
        query="Is the judgment in ADM Jabalpur v. Shivkant Shukla still good law regarding Habeas Corpus?",
        target_doc_id=None,
        ground_truth_citation="1976 2 SCC 521",
        expected_answer_elements=["Overruled", "Justice K.S. Puttaswamy Case", "Article 21 cannot be suspended"],
        category=EvalCategory.OVERRULED_TRAP
    ),
    
    # BNS / BNSS / BSA TRANSITIONS
    BenchmarkCase(
        query="What is the equivalent section for Section 302 of IPC in Bharatiya Nyaya Sanhita (BNS)?",
        target_doc_id=None,
        ground_truth_citation="Section 103 BNS",
        expected_answer_elements=["Section 103", "Punishment for Murder", "BNS"],
        category=EvalCategory.LAW_TRANSITION
    ),
    BenchmarkCase(
        query="How does Bharatiya Nagarik Suraksha Sanhita (BNSS) handle Section 154 CrPC (FIR)?",
        target_doc_id=None,
        ground_truth_citation="Section 173 BNSS",
        expected_answer_elements=["Section 173", "e-FIR", "Zero FIR"],
        category=EvalCategory.LAW_TRANSITION
    ),
    
    # APPEAL CHAINS
    BenchmarkCase(
        query="Was the High Court judgment in the case of [X] reversed by the Supreme Court?",
        target_doc_id=None,
        ground_truth_citation="SC Citation",
        expected_answer_elements=["Reversed", "Upheld"],
        category=EvalCategory.APPEAL_CHAIN
    ),
    
    # JURISDICTION BINDING
    BenchmarkCase(
        query="Is a judgment of the Delhi High Court binding on the Mumbai District Court?",
        target_doc_id=None,
        ground_truth_citation="N/A",
        expected_answer_elements=["Persuasive", "Not Binding"],
        category=EvalCategory.JURISDICTION
    ),
    
    # MULTI-HOP PRECEDENT
    BenchmarkCase(
        query="Trace the evolution of the concept of 'creamy layer' from Indra Sawhney to Jarnail Singh.",
        target_doc_id=None,
        ground_truth_citation="Multiple",
        expected_answer_elements=["Indra Sawhney", "M. Nagaraj", "Jarnail Singh"],
        category=EvalCategory.MULTI_HOP
    )
]

# NOTE: In a real-world scenario, this list would be expanded to 100 cases with exact doc_ids 
# once the corpus is migrated to PostgreSQL and doc_ids are stable.
