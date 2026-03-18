# NyayaRAG Master Memory

Read this file before planning, coding, or simplifying anything in NyayaRAG.

This file is the durable operating memory for future Codex sessions. It preserves:
- the product thesis,
- the exact RAG architecture,
- the zero-hallucination verification path,
- the data model and corpus shape,
- the UI trust model,
- the phased execution order,
- and the non-negotiables that must never be optimized away.

## 1. Product Thesis

NyayaRAG is not a generic legal chatbot.

NyayaRAG is an Indian legal research system built around one hard promise:

`No citation is ever shown as verified unless the system has structurally checked that it exists, supports the claim, is still good law, and is the final authoritative judgment if an appeal chain exists.`

Core category claim:
- competitors use RAG to reduce hallucination probability,
- NyayaRAG uses architecture to make citation fabrication and unsupported citation display structurally impossible.

Working positioning:
- Name: `NyayaRAG`
- Meaning: `Nyaya = justice`
- Tagline: `The only Indian legal research system where hallucination is architecturally impossible — built for Indian courts.`
- Target user: Indian advocates, chambers, law students, judges' clerks, and legal researchers who need SCC-level trust without SCC-level cost.

## 2. Founder Narrative and Market Context

The founder narrative driving the product is:
- Indian courts and tribunals are now highly sensitive to AI-generated fake precedents.
- Lawyers do not trust current AI systems enough to cite them directly in court work.
- The market gap is trust, not chat fluency.
- Today the practical workflow is still: verify citations in SCC/Manupatra/BharatLaw first, then use AI.
- NyayaRAG wins only if it collapses that two-tool workflow into one trusted research workflow.

Important rigor note:
- The recent Supreme Court, tribunal, and Stanford claims are core founder narrative and product positioning inputs.
- Before those claims are used in public copy, fundraising decks, or the homepage trust page, verify them with primary sources and exact dates.
- Internally, they remain part of the product rationale and urgency model.

## 3. Non-Negotiable System Invariants

These are absolute rules. If a future implementation weakens any of these, it is no longer NyayaRAG.

1. No raw citation strings generated directly by the LLM.
2. All case citations must resolve to canonical `doc_id` records.
3. All claims shown as verified must pass claim-to-source support checks.
4. All cited judgments must pass appeal-chain validation.
5. All cited statutory text must pass temporal-validity checks.
6. All outputs must carry explicit certainty labeling.
7. Overruled or reversed authorities must never appear as current binding law.
8. Query routing is mandatory. One pipeline for every query is forbidden.
9. Source viewer and process transparency are trust infrastructure, not optional UI polish.
10. The product must always return a useful answer. Unsupported claims are labeled, not silently dropped.

## 4. Canonical Architecture Summary

Stack:
- Frontend: `Next.js 14 App Router + TypeScript + Tailwind`
- Backend: `FastAPI + Python`
- Canonical DB: `PostgreSQL 15`
- Vector DB: `Qdrant`
- Graph DB: `Neo4j Community`
- Cache/queue: `Redis + Celery`
- LLMs: `Claude Sonnet for generation`, `Claude Opus for verification`
- Embeddings: `BGE-M3`
- OCR: `Tesseract 5 + TrOCR`
- Translation: `IndicTrans2`
- Auth: `Clerk`
- Billing: `Razorpay`

Canonical storage rule:
- PostgreSQL is the source of truth for documents, citations, statutes, sections, amendments, appeal links, workspaces, history, evaluations, and verification results.
- Qdrant stores retrieval projections.
- Neo4j stores graph projections.
- Redis stores transient caches and queue state.

## 5. Corpus Vision

The intended v1 corpus is broad public Indian legal material plus user uploads.

Judgment corpus:
- Supreme Court of India
- all 25 High Courts
- selected District/eCourts orders
- NCLT / NCLAT
- ITAT
- NGT
- CAT
- TDSAT
- India Kanoon

Statutory and constitutional corpus:
- Constitution of India
- Constitutional Amendments
- Constituent Assembly Debates
- India Code central acts
- state acts
- BNS / BNSS / BSA
- SEBI regulations
- RBI circulars
- Law Commission reports
- parliamentary/legal policy material where useful for reasoning context

Operational truth:
- This is a public-source-first system.
- If licensed reporters, books, or proprietary treatises are added later, they must enter as a separate corpus layer and never force changes to the canonical document model.

## 6. Canonical Legal Models

### LegalDocument

```python
class LegalDocument:
    doc_id: str
    doc_type: Literal[
        "judgment", "statute", "amendment", "circular",
        "notification", "order", "constitution", "bill",
        "lc_report", "cab_debate"
    ]
    court: str
    bench: List[str]
    coram: int
    date: date
    citation: str
    neutral_citation: str
    parties: Dict[str, str]
    jurisdiction_binding: List[str]
    jurisdiction_persuasive: List[str]
    current_validity: ValidityStatus
    overruled_by: Optional[str]
    overruled_date: Optional[date]
    distinguished_by: List[str]
    followed_by: List[str]
    statutes_interpreted: List[StatuteRef]
    statutes_applied: List[StatuteRef]
    citations_made: List[str]
    headnotes: List[str]
    ratio_decidendi: str
    obiter_dicta: List[str]
    appeal_history: List["AppealNode"]
    practice_areas: List[str]
    language: str
    full_text: str
```

### AppealNode

This is one of NyayaRAG's strongest structural advantages.

```python
class AppealNode:
    court_level: int
    court_name: str
    judgment_date: date
    citation: str
    outcome: Literal["upheld", "reversed", "modified", "remanded", "dismissed"]
    is_final_authority: bool
    modifies_ratio: bool
    parent_doc_id: str
    child_doc_id: Optional[str]
```

### StatuteDocument and Section

```python
class StatuteDocument:
    doc_id: str
    act_name: str
    short_title: str
    replaced_by: Optional[str]
    replaced_on: Optional[date]
    sections: List["Section"]
    current_sections_in_force: List[str]
    amendment_history: List["Amendment"]
    jurisdiction: str
    enforcement_date: date
    current_validity: bool

class Section:
    section_number: str
    heading: str
    text: str
    original_text: str
    amendments: List["Amendment"]
    is_in_force: bool
    corresponding_new_section: Optional[str]
    punishment: Optional[str]
    cases_interpreting: List[str]
```

### CaseContext

```python
class CaseContext:
    case_id: str
    appellant_petitioner: str
    respondent_opposite_party: str
    advocates: List[str]
    case_type: str
    court: str
    case_number: str
    stage: str
    charges_sections: List[str]
    bnss_equivalents: List[str]
    statutes_involved: List[str]
    key_facts: List[Fact]
    previous_orders: List[CourtOrder]
    bail_history: List[BailOrder]
    open_legal_issues: List[str]
    uploaded_docs: List[ProcessedDocument]
    doc_extraction_confidence: float
```

## 7. Knowledge Graph Design

GraphRAG depends on a formal citation graph.

Nodes:
- `JudgmentNode`
- `StatuteNode`
- `ConceptNode`

Edges:
- `CITES`
- `INTERPRETS`
- `APPLIES`
- `EVOLVED_INTO`
- `PART_OF_DOCTRINE`
- and typed citation variants such as `follows`, `distinguishes`, `overrules`, `approves`, `disapproves`, `doubts`, `explains`, `refers_to`

Graph rules:
- overruled nodes are never final doctrine outputs,
- constitutional queries must anchor on Constitution Bench judgments where possible,
- concept clusters are precomputed for major doctrines such as privacy, natural justice, double jeopardy, promissory estoppel, bail jurisprudence, and due process.

## 8. Query Router: The Core Strategic Insight

NyayaRAG must route queries before retrieval.

The main architectural thesis is:

`There is no single best RAG. There is only the best retrieval architecture for a given legal query type.`

### Query Types

- `STATUTORY_LOOKUP`
- `CASE_SPECIFIC`
- `MULTI_HOP_DOCTRINE`
- `CONSTITUTIONAL`
- `VAGUE_NATURAL`
- `DOCUMENT_SPECIFIC`
- `COMPARATIVE`

### Routing Rules

```python
if uploaded_docs:
    return AgenticRAG
if requires_multi_hop or constitutional or comparative:
    return GraphRAG
if is_vague:
    return HyDE -> HybridRAG
if statutory or case_specific:
    return HybridRAG + CRAG
return HybridRAG
```

### QueryAnalysis fields

Every query should be normalized into a typed analysis object containing:
- query type,
- jurisdiction,
- practice area,
- time sensitivity,
- BNS/BNSS/BSA mapping flags,
- sections mentioned,
- extracted legal entities,
- vagueness score,
- multi-hop need,
- uploaded-doc presence,
- selected pipeline,
- pipeline reason.

## 9. The Five RAG Pipelines

### Pipeline 1: Hybrid RAG

Used for:
- statutory queries,
- specific case queries,
- default legal research,
- straightforward case-law lookups.

Stages:
1. BM25 retrieval
2. dense retrieval
3. reciprocal-rank fusion
4. cross-encoder reranking
5. authority ranking

Why this matters:
- BM25 is mandatory for exact section numbers, citations, and legal phrases.
- Dense retrieval is mandatory for semantic relatedness.
- Cross-encoder reranking improves legal relevance.
- Authority ranking keeps binding law above persuasive authority.

Expected final context:
- top 5 binding chunks,
- top 3 persuasive chunks,
- all already filtered to good law.

### Pipeline 2: GraphRAG

Used for:
- doctrinal evolution,
- constitutional law,
- multi-hop legal questions,
- landmark-case chains,
- current-law synthesis requiring citation lineage.

Flow:
1. identify concept anchors,
2. traverse graph bidirectionally,
3. detect overruling,
4. prune dead doctrine,
5. rank subgraph nodes,
6. build doctrinal timeline,
7. fetch supporting chunks.

This is the pipeline that answers:
- `How has the right to privacy developed in India?`
- `What is the current law on natural justice?`
- `How did Article 21 evolve from Gopalan to Puttaswamy?`

### Pipeline 3: CRAG

CRAG is not optional.

It validates whether retrieved context actually answers the query and whether the legal text is temporally current.

CRAG outcomes:
- `PROCEED`
- `REFINE`
- `INSUFFICIENT`
- optional `WEB_SUPPLEMENTED` only under tightly controlled legal-source conditions

CRAG responsibilities:
- semantic relevance scoring,
- entity coverage,
- temporal statute validation,
- amendment awareness,
- possible query decomposition.

### Pipeline 4: HyDE

Used for vague natural-language queries where the user lacks legal vocabulary.

Process:
1. generate a hypothetical ideal Indian judgment excerpt,
2. embed the hypothetical text,
3. retrieve using that embedding,
4. fuse with lexical retrieval from the original user query,
5. rerank against the original user intent.

This is what makes layperson or junior-advocate questions retrievable.

### Pipeline 5: Agentic RAG

Used only when documents are uploaded.

Agents:
- `DocumentUnderstandingAgent`
- `ResearchPlannerAgent`
- `StatutoryResearchAgent`
- `PrecedentResearchAgent`
- `ContradictionCheckerAgent`
- `SynthesisAgent`
- `VerificationAgent`

LangGraph rules:
- no deprecated `langgraph.prebuilt`,
- use `with_structured_output()` for planning/routing,
- use `SqliteSaver` locally and `PostgresSaver` later,
- keep all agent activity logged for the transparency drawer.

## 10. BNS / BNSS / BSA Awareness

NyayaRAG must always understand the July 1, 2024 criminal-code transition.

Rules:
- if a criminal-law query references IPC/CrPC/Evidence Act, map to BNS/BNSS/BSA equivalents,
- if the offence date is post-July 1, 2024, prioritize the new codes,
- if the issue spans pre- and post-transition periods, show both old and new sections,
- if mapping is ambiguous, surface the ambiguity explicitly.

This is not a nice-to-have. It is part of trust.

## 11. Chunking and Embedding Strategy

Standard chunking is not good enough for law.

### Chunking rules

- judgment headnotes: one headnote per chunk
- ratio paragraphs: sentence-aware, paragraph-boundary chunks
- obiter: paragraph-boundary chunks
- statutes: one section per chunk whenever possible
- long statutory sections: subsection-aware chunks with parent heading repeated
- constitution: one article per chunk
- Law Commission reports: paragraph-aware chunks with overlap

### Chunk metadata

Every chunk must carry:
- parent `doc_id`,
- document type,
- chunk position,
- nearest section header,
- court,
- date,
- citation,
- jurisdiction binding/persuasive metadata,
- current validity,
- act and section metadata where relevant,
- embedding metadata.

### Embedding choice

Default embedding model: `BGE-M3`

Reasons:
- multilingual,
- open-source,
- strong long-text retrieval,
- supports dense and sparse use cases,
- appropriate for Indian-language coverage.

## 12. Zero-Hallucination Architecture

There are two hallucination classes that matter:

### Type 1: Fabrication

This is when the model invents a case or citation that does not exist.

Prevention:
- generator uses placeholders only,
- citation resolver maps placeholders to real corpus records,
- unresolved placeholders become `UNVERIFIED`, never fabricated.

### Type 2: Misgrounding

This is when the citation is real but does not support the claim.

Prevention:
- extract the exact claim,
- find the best supporting passage,
- compute semantic similarity,
- run NLI/entailment,
- downgrade or remove unsupported support,
- reretrieve if needed,
- if still unresolved, mark the claim as uncertain or unverified.

### Verification stack order

1. constrained generation
2. citation resolver
3. misgrounding checker
4. appeal-chain validator
5. temporal validator
6. Self-RAG verifier
7. output builder with claim-level status

## 13. Output Semantics

The user-facing answer must be structured, not conversational fluff.

Main sections:
- Legal Position
- Applicable Law
- Key Cases
- Verification Status
- optionally Arguments / Counter-Arguments / Timeline / Case-Specific Strategy

Citation statuses:
- `GREEN_VERIFIED`
- `YELLOW_UNCERTAIN`
- `BLUE_UNVERIFIED`
- `RED_REVERSED`
- `GRAY_PERSUASIVE`

The governing rule:

`The user always receives a complete answer, but certainty is displayed precisely.`

## 14. Appeal Chain Validation

This is a signature feature and must not be weakened.

If a cited judgment:
- has no appeal history: cite normally,
- has pending appeal: allow citation with warning,
- was reversed: redirect to the reversing authority and show a red warning,
- was modified: cite with modification note,
- is not final authority: surface the final authority instead.

NyayaRAG must stop lawyers from accidentally relying on a reversed intermediate judgment.

## 15. Daily Validity Engine

The corpus is alive. Daily validation is part of the product.

Daily jobs must:
- check if statutes remain in force,
- detect section amendments,
- update BNS/BNSS/BSA mappings,
- scan new judgments for overruling language,
- update `current_validity`,
- flag affected chunks for re-embedding,
- refresh graph edges where doctrine status changed.

## 16. Evaluation Framework

NyayaRAG is not trusted unless it measures itself publicly.

### Metric layers

Classical IR:
- Precision@K
- Recall@K
- MRR
- nDCG
- MAP

Generation:
- BERTScore
- ROUGE-L
- METEOR

RAGAS:
- Faithfulness
- Answer Relevancy
- Context Precision
- Context Recall
- Context Entity Recall

DeepEval:
- Hallucination Score
- Contextual Precision
- Contextual Recall
- G-Eval Legal Accuracy
- Noise Robustness

India-legal-specific metrics:
- Citation Existence Rate
- Citation Accuracy Rate
- Appeal Chain Accuracy
- Jurisdiction Binding Accuracy
- Temporal Validity Rate
- Amendment Awareness Rate
- Multi-hop Completeness
- BNS/BNSS/BSA Awareness

### Trust Dashboard rule

The `/trust` page is one of the most important pages in the product.

It must show:
- benchmark coverage,
- current measured hallucination-prevention metrics,
- retrieval metrics,
- answer-quality metrics,
- latency metrics,
- update date,
- benchmark size.

Do not show aspirational numbers as measured truth.

## 17. Document Upload System

Accepted sources:
- typed PDFs,
- scanned PDFs,
- photos,
- DOCX/DOC,
- handwritten documents,
- mixed bundles,
- WhatsApp-forwarded legal docs.

Processing path:
- classify file/page type,
- extract text or OCR,
- clean legal OCR errors,
- extract parties, sections, dates, facts, courts, prior orders,
- build `CaseContext`,
- persist the workspace so the user never re-explains the case.

This is a major differentiator.

## 18. UI and Trust Design

Design philosophy:
- a legal library, not a tech startup,
- information density of a law journal,
- trust signals of a Supreme Court website,
- no generic chat bubbles as the primary interaction model.

Design language:
- Inter for prose,
- Lora for citations,
- JetBrains Mono for structured metadata/logs,
- navy/cream/gold palette,
- no dark mode in v1,
- no glassmorphism,
- no decorative gradients,
- no animations without semantic meaning.

Core screens:
- landing page with trust number and proof,
- three-panel research workspace,
- live research process display,
- structured answer output,
- citation graph toggle,
- agent transparency drawer.

The most important UX principle:

`Trust is built by showing the system think, retrieve, validate, and verify in public.`

## 19. Streaming Architecture

Real-time transparency is required.

Transport:
- `Server-Sent Events`

Event types:
- `STEP_START`
- `STEP_COMPLETE`
- `STEP_ERROR`
- `AGENT_LOG`
- `TOKEN`
- `CITATION_RESOLVED`
- `COMPLETE`

The frontend should render process steps live, not hide them behind a spinner.

## 20. Qdrant Collection Design

Default collections:
- `sc_judgments`
- `hc_judgments`
- `statutes`
- `constitution`
- `tribunal_orders`
- `lc_reports`
- `doctrine_clusters`

Collection intent:
- `sc_judgments`: Supreme Court judgments with authority-rich metadata
- `hc_judgments`: High Courts with court/state/date/validity filters
- `statutes`: one current section per chunk where possible
- `constitution`: article-centric constitutional retrieval
- `tribunal_orders`: tribunal jurisprudence
- `lc_reports`: Law Commission reasoning context
- `doctrine_clusters`: precomputed doctrinal summaries and landmark anchor sets

Key filter fields across collections:
- validity
- court
- state
- date
- bench size
- practice area
- act name
- section number
- amendment metadata
- doctrine name

## 21. API Surface That Must Stay Stable

Core endpoints:
- `POST /api/query`
- `GET /api/query/{id}/stream`
- `POST /api/workspace`
- `GET /api/workspace/{case_id}`
- `POST /api/workspace/{case_id}/upload`
- `GET /api/workspace/{case_id}/history`
- `GET /api/citation/{doc_id}/verify`
- `GET /api/citation/{doc_id}/source`
- `GET /api/citation/{doc_id}/appeal-chain`
- `GET /api/judgment/{doc_id}`
- `GET /api/statute/{act_id}/section/{num}`
- `GET /api/evaluation/public`
- `POST /api/auth/signup`
- `POST /api/billing/subscribe`
- `GET /api/health`

API design rules:
- backend models are the source of truth,
- frontend types should be generated from backend contracts where possible,
- every streaming event must be typed and documented,
- citation/source endpoints must resolve by canonical IDs, not raw strings.

## 22. Workspace UX Details That Matter

### Landing page

Must communicate:
- one bold trust claim,
- one visible trust number,
- one demo showing verified citations beating generic AI,
- one dashboard preview,
- one pricing table.

Must avoid:
- homepage chatbot widget,
- stock courtroom imagery,
- generic "AI-powered" badges,
- startup-style noise that weakens credibility.

### Workspace layout

Left panel:
- files,
- case context,
- research history,
- saved answers,
- settings.

Center panel:
- query bar,
- jurisdiction and practice chips,
- live query understanding,
- process display,
- structured answer,
- follow-up bar.

Right panel:
- always-open source viewer,
- exact source paragraph,
- highlight state,
- metadata and authority info.

### Trust-critical UI components

- `ProcessDisplay`
- `CitationBadge`
- `SourceViewer`
- `AnswerPanel`
- `CitationGraph`
- `AgentLogDrawer`
- `DocumentUpload`
- `CaseContextSummary`

### Citation color semantics

- green: exists and supports claim
- yellow: exists but partial/uncertain support
- blue: principle useful but unresolved source
- red: reversed/overruled or blocked
- gray: persuasive authority only

## 23. Pricing and Go-To-Market Memory

Initial pricing shape:
- Free: `₹0`, limited daily queries, no upload
- Advocate Pro: `₹799/month`
- Chamber Pro: `₹2,499/month`
- Law School: `₹9,999/year per institution`
- Enterprise: custom

Commercial thesis:
- undercut expensive incumbents,
- keep solo advocates within reach,
- use trust, not chat novelty, as the primary conversion lever.

Primary launch assets:
- public trust dashboard,
- side-by-side demo video,
- legal-community distribution through WhatsApp, legal Twitter/X, professors, and relevant public communities.

## 24. Caching and Performance

Redis caches should include:
- full query-result cache,
- citation-existence cache,
- appeal-chain cache,
- validity cache,
- BM25 result cache,
- embedding cache where useful.

Performance goals:
- Hybrid p50 under 2 seconds
- GraphRAG p50 under 4 seconds
- Agentic p95 under 30 seconds
- first token under 1 second where possible

Cost target:
- keep Pro-tier per-query cost well under subscription value,
- preserve free tier through open-source embeddings, translation, OCR, and caching.

## 25. Failure-Mode Philosophy

NyayaRAG does not fail silently.

If something is weak, uncertain, stale, reversed, or unsupported:
- show it,
- label it,
- redirect if possible,
- degrade gracefully.

Typical failure cases to handle explicitly:
- low CRAG score,
- missing citation resolution,
- misgrounding,
- reversed judgment,
- statute repeal,
- section amendment,
- graph-anchor miss,
- low OCR confidence,
- LLM timeout,
- Neo4j outage,
- high unsupported-claim rate,
- ambiguous BNS mapping.

## 26. Build-Phase Test Gates

Each phase should have a pass/fail gate before the next phase starts.

### Data pipeline gate
- representative corpus ingested successfully,
- statutes and constitutional material parsed,
- citation extraction working,
- appeal chains stored,
- Qdrant projection populated,
- Neo4j projection populated,
- BNS mapping available for targeted criminal sections.

### RAG pipeline gate
- all query types route correctly,
- Hybrid returns relevant binding results,
- GraphRAG returns a doctrinal chain rather than isolated cases,
- HyDE improves vague-query retrieval,
- CRAG blocks weak statute retrieval from proceeding silently.

### Hallucination-prevention gate
- fabricated citations never reach verified output,
- misgrounded claims are downgraded or reretrieved,
- reversed judgments redirect correctly,
- unsupported claims are labeled.

### Evaluation gate
- benchmark suite runs end to end,
- trust metrics are stored,
- dashboard API can serve real measured results.

### Upload gate
- OCR works on at least one typed, scanned, image, and DOCX sample,
- case context persists,
- uploaded-doc queries route through Agentic RAG.

### Frontend gate
- SSE process display renders,
- source viewer highlights exact text,
- answer badges show correctly,
- citation graph and transparency drawer work.

## 27. Repository Shape

The intended repository shape is:

```text
frontend/
backend/
data/
infrastructure/
```

With internal modules for:
- research UI,
- citation/source UI,
- agent transparency,
- upload pipeline,
- rag router,
- rag pipelines,
- verification,
- ingestion,
- evaluation,
- tasks,
- streaming.

## 28. Build Order

The build order is fixed unless there is a very strong reason to change it.

### Phase 1: Data pipeline
- corpus adapters
- parser layer
- metadata extraction
- citation extraction
- appeal-chain builder
- validity checker
- chunking
- embedding
- Qdrant and Neo4j projection

### Phase 2: Core RAG
- query router
- Hybrid RAG
- GraphRAG
- CRAG
- HyDE
- Agentic RAG scaffold

### Phase 3: Zero-hallucination layer
- placeholder generation
- citation resolver
- misgrounding checker
- appeal validator
- Self-RAG verifier
- structured output builder

### Phase 4: Evaluation
- RAGAS
- DeepEval
- India-specific metrics
- benchmark runner
- trust dashboard API

### Phase 5: Upload
- typed PDF
- OCR
- page classification
- case-context builder
- persistence

### Phase 6: Frontend
- design system
- landing page
- workspace
- streaming process display
- answer rendering
- source viewer
- citation graph
- transparency drawer
- history
- export
- multilingual

### Phase 7: Billing and launch
- Razorpay
- usage tracking
- rate limiting
- trust page live
- demo video
- launch distribution

## 29. Future Codex Instructions

When working on NyayaRAG in future sessions:
- do not simplify the architecture into a single-pipeline chatbot,
- do not remove any verification layer for convenience,
- do not replace `doc_id`-based citation identity with citation strings,
- do not collapse validity into a boolean if richer status is needed,
- do not hide uncertainty from the user,
- do not reduce the UI to a spinner plus answer bubble,
- do not use generic UI defaults without adapting them to the legal-library design language,
- do not skip tests after each build unit,
- do not market unverified public claims as already proven measurements.

## 30. Read-First Session Checklist

Before any serious implementation session, review:
- this file,
- `NyayaRAG_Complete_Specification.docx`,
- the current phase/unit being built,
- the current test gates,
- any existing benchmark results.

If a future plan or implementation conflicts with this file, the default assumption is:

`This file wins unless the product direction has intentionally changed and the file has been updated.`

## 31. Final Mental Model

NyayaRAG is not "ChatGPT for law."

NyayaRAG is:
- a verified legal corpus,
- a multi-pipeline legal retrieval system,
- a citation and appeal-aware knowledge graph,
- a zero-hallucination answer-construction engine,
- a transparency-first legal workspace,
- and a trust dashboard that proves the system deserves to be used.

The entire company is built on one pillar:

`Verified retrieval + verified citation + verified support + verified current law + visible uncertainty.`
