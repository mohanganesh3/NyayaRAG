# NyayaRAG Revised Execution Strategy

Read this after:
- `NYAYARAG_MASTER_MEMORY.md`
- `NYAYARAG_EXECUTION_PLAYBOOK.md`

This file corrects the remaining execution order.
It exists because the original build order was technically valid, but too broad.
The remaining work must now be driven by one rule:

`Do not scale corpus ingestion until the answer-integrity layer is complete enough to validate what the corpus is being used for.`

## 1. The Critical Clarification About Placeholders

Placeholders are not a temporary hack.
They are not a scaffolding step we remove later.
They are a core production safety mechanism.

### Why placeholders stay

If the LLM is allowed to emit raw legal citations directly, three bad things happen:
- it can invent a citation string,
- it can attach a real citation to the wrong claim,
- it can bypass the canonical `doc_id` resolution boundary.

NyayaRAG's design requires a hard separation between:
- legal reasoning,
- citation selection,
- citation verification,
- claim-to-source verification.

The placeholder protocol creates that separation.

Correct flow:
1. generator writes a claim plus `[CITE: ...]`
2. resolver maps the placeholder to a real corpus document
3. misgrounding checker confirms the source supports the claim
4. appeal validator confirms final authority
5. temporal validator confirms current law
6. only then does the answer become verified

Without placeholders, the generator is again trusted to name the authority itself.
That collapses the trust boundary.
That is exactly what NyayaRAG is not allowed to do.

### Final rule

`Placeholders are permanent product architecture, not a development convenience.`

## 2. What Is Already Done

As of this revision, the following is real and working in code:

### Foundation
- monorepo structure
- frontend/backend bootstrap
- infra scaffolding
- health, contracts, SSE primitives

### Canonical legal layer
- legal document models
- statute and amendment models
- appeal nodes
- provenance ledger
- BNS / BNSS / BSA mapping support

### Ingestion framework
- adapter contracts
- archetype adapters
- citation graph projection
- appeal-chain builder
- daily validity engine
- legal-aware chunker
- embedding pipeline
- Qdrant collection manager

### Core retrieval
- lexical retrieval
- query router
- Hybrid RAG
- GraphRAG
- CRAG
- HyDE

### Verification status of current codebase
- backend tests are green
- frontend tests are green
- lint and typecheck are green

## 3. What Is Not Done Yet

These are still unfinished:

### Zero-hallucination output layer
- placeholder-only generator
- citation resolver
- misgrounding checker
- answer-time appeal validator
- self-RAG verifier
- structured answer builder

### Evaluation and trust
- retrieval benchmark suite
- answer-quality evaluation suite
- India-legal metrics suite
- trust dashboard backend

### Corpus scale-out
- real large-scale population of SC / HC / tribunal / statute corpora
- daily production ingestion jobs
- bulk re-embedding at real scale
- Neo4j graph population at real corpus size

### Uploads and agentic workflows
- OCR pipeline
- OCR cleanup
- CaseContext builder from real documents
- LangGraph orchestration

### Product UI and launch
- full workspace
- trust-heavy answer rendering
- citation graph UI
- upload UI
- auth
- billing
- trust page

## 4. Corrected Build Principle

The correct remaining strategy is not:
- ingest everything now,
- then figure out how to verify outputs later.

The correct remaining strategy is:
- finish the answer-integrity stack first,
- build the evaluation harness second,
- then start bulk corpus ingestion with validation gates,
- then build uploads and product UI on top of that verified core.

Reason:
- retrieval without final answer verification is incomplete,
- corpus at scale without evaluation is blind,
- UI before answer integrity creates fake progress,
- billing before trust instrumentation is wasted motion.

## 5. Revised Remaining Order

This order supersedes the old "just continue phase by phase blindly" approach.

### Stage A: Finish the answer-integrity core

Build next:
1. `Phase 5 -> Unit 5.1: Placeholder-only generator`
2. `Phase 5 -> Unit 5.2: Citation resolver`
3. `Phase 5 -> Unit 5.3: Misgrounding checker`
4. `Phase 5 -> Unit 5.4: Appeal validator`
5. `Phase 5 -> Unit 5.5: Self-RAG verifier`
6. `Phase 5 -> Unit 5.6: Structured answer builder`

This is the point where NyayaRAG becomes an answer system instead of only a retrieval system.

### Stage B: Build the trust measurement layer immediately after

Build next:
1. `Phase 6 -> Unit 6.1: Retrieval benchmark suite`
2. `Phase 6 -> Unit 6.2: Answer-quality suite`
3. `Phase 6 -> Unit 6.3: India-legal evaluation suite`
4. `Phase 6 -> Unit 6.4: Trust dashboard backend`

This is the point where we can measure whether the architecture is actually doing what it claims.

### Stage C: Only then begin bulk corpus ingestion fan-out

After Stage A and Stage B, scale ingestion from archetypes to real corpus breadth:
- Supreme Court full runs
- High Court fan-out
- tribunals
- India Code full pull
- constitutional and amendment materials
- Law Commission corpus

This is where real corpus population happens seriously.

### Stage D: Build document-specific workflows after the verified base exists

Build:
1. OCR and file ingestion
2. OCR cleanup and normalization
3. CaseContext builder
4. LangGraph workflow

Reason:
- uploaded-document workflows depend on a trustworthy research backend,
- not the other way around.

### Stage E: Build product UI after the backend truth model is stable

Build:
1. workspace shell
2. live process display
3. structured answer rendering
4. source viewer and citation UI
5. citation graph and transparency drawer
6. upload UX

### Stage F: Commercial and launch systems come last

Build only after the trust path is real:
- auth
- billing
- trust page
- launch assets

## 6. Dataset Strategy: Two Different Dataset Types

One source of confusion is the word "dataset".
NyayaRAG needs two different dataset categories.

### Dataset type 1: Gold evaluation sets

These are small, curated, manually validated benchmark sets.
They are needed now, before full ingestion scale.

Purpose:
- test retrieval correctness,
- test claim grounding,
- test appeal-chain handling,
- test temporal statute validity,
- test BNS/BNSS/BSA transitions,
- test multi-hop doctrine completeness.

These datasets should be built early because they are how we judge correctness.

### Dataset type 2: Production legal corpus

This is the massive real corpus:
- judgments,
- statutes,
- constitutional material,
- tribunals,
- reports.

This should scale after the architecture that uses it is stable enough to evaluate.

### Rule

`Build gold benchmark datasets first. Scale production corpus second.`

## 7. What "Build Everything First, Then Ingest" Should Actually Mean

The phrase is correct only if interpreted carefully.

It should mean:
- build every correctness-critical backend layer first,
- not every possible UI/commercial feature first.

So the accurate version is:

### Build first
- answer integrity
- verification
- evaluation
- retrieval benchmarks
- structured answer format

### Then ingest at scale
- because now the system can measure and validate what the data is doing

### Then finish product layers
- uploads
- agentic workflows
- full UI
- billing

That is the right dependency order.

## 8. Hard Gates Before Bulk Ingestion

Do not begin large-scale ingestion fan-out until all of the following are true:

1. generator emits placeholders only
2. citation resolver never invents citations
3. misgrounding checker catches seeded bad examples
4. appeal validator redirects reversed authorities
5. self-RAG verifier marks unsupported claims
6. structured answer output exists
7. retrieval benchmark suite runs
8. India-legal metrics run on curated examples

If these are not done, bulk ingestion creates volume without trust.

## 9. Revised Definition Of Progress

Progress is not:
- more scrapers,
- more pages,
- more UI,
- more documents indexed.

Progress is:
- stronger correctness guarantees,
- stronger evaluation coverage,
- stronger authority resolution,
- stronger measured trust.

Bulk data volume matters only after those layers exist.

## 10. The Immediate Next Build Sequence

The next exact units should be:

1. `Phase 5 -> Unit 5.1: Placeholder-only generator`
2. `Phase 5 -> Unit 5.2: Citation resolver`
3. `Phase 5 -> Unit 5.3: Misgrounding checker`
4. `Phase 5 -> Unit 5.4: Appeal validator`
5. `Phase 5 -> Unit 5.5: Self-RAG verifier`
6. `Phase 5 -> Unit 5.6: Structured answer builder`
7. `Phase 6 -> Unit 6.1: Retrieval benchmark suite`
8. `Phase 6 -> Unit 6.2: Answer-quality suite`
9. `Phase 6 -> Unit 6.3: India-legal evaluation suite`
10. `Phase 6 -> Unit 6.4: Trust dashboard backend`

Only after that:
- start full real corpus ingestion expansion.

## 11. Final Operating Rule

If a future session asks:
- "why not remove placeholders?"
- "why not scale ingestion first?"
- "why not build the UI first?"

the answer is:

`Because NyayaRAG wins on verified legal trust, not on raw retrieval volume or UI speed.`

