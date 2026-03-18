# NyayaRAG Execution Playbook

Read this after `NYAYARAG_MASTER_MEMORY.md`.

This file is the execution-grade companion to the master memory. It is meant to answer:
- what to build first,
- what file/module boundaries to use,
- what every phase must produce,
- what tests must pass before moving on,
- and what future Codex sessions must never simplify away.

## 1. How To Use This File

At the start of each serious build session:
1. Read `NYAYARAG_MASTER_MEMORY.md`.
2. Read this file.
3. Pick one exact phase and one exact unit.
4. Build only that unit plus any required supporting code.
5. Run the unit tests and phase gate.
6. Do not move forward until the gate passes.

Session prompt discipline:
- always state the active phase,
- always state the active unit,
- always restate the non-negotiables,
- always verify after implementation,
- never skip verification layers for speed.

## 2. Default Build Assumptions

Use these assumptions unless the product direction changes intentionally:
- local-first development on laptop,
- Docker-managed infra,
- web-first product,
- English-first public beta, translation-ready architecture,
- public-source-first corpus,
- representative real-source subset first, then fan out to full coverage,
- managed APIs allowed temporarily if they preserve the same interfaces and do not weaken the architecture.

## 3. Non-Negotiables For Every Phase

Never do any of the following:
- collapse the router into a single default RAG pipeline,
- let the generator emit raw legal citations,
- remove misgrounding checks,
- skip appeal-chain validation,
- skip temporal statute validation,
- store citations only as strings,
- use generic chatbot UX as the main product interaction,
- surface unverified claims as verified,
- publish aspirational trust metrics as real benchmark values.

## 4. Intended Repository Scaffold

Create this shape first:

```text
frontend/
backend/
data/
infrastructure/
```

Recommended internal layout:

```text
frontend/
  app/
  components/
    research/
    citation/
    agents/
    upload/
    ui/
  lib/

backend/
  api/
    routes/
    streaming/
  models/
  db/
  rag/
    router.py
    pipelines/
    verification/
  ingestion/
    scrapers/
    parsers/
    extractors/
    validators/
  evaluation/
  tasks/
  tests/

data/
  corpus/
  processed/
  graphs/
  evaluation/

infrastructure/
  docker-compose.yml
  scripts/
  evaluation/
```

## 5. Phase 0: Foundation and Bootstrap

Goal:
- create the technical spine before any legal logic is added.

### Unit 0.1: Monorepo bootstrap

Deliver:
- root folder layout,
- frontend app scaffold,
- backend app scaffold,
- infrastructure folder,
- baseline env files,
- lint/typecheck/test runners.

Must include:
- FastAPI app entrypoint,
- Next.js app entrypoint,
- docker compose for Postgres, Qdrant, Neo4j, Redis,
- basic health endpoint,
- shared naming conventions.

Exit check:
- frontend boots,
- backend boots,
- infra services start,
- backend can connect to Postgres.

### Unit 0.2: Canonical backend foundations

Deliver:
- SQLAlchemy models or equivalent persistence layer,
- migrations,
- Pydantic schemas,
- config/settings layer,
- structured logging,
- background task skeleton.

Exit check:
- database migrations run cleanly,
- test database can be created and torn down,
- model imports are stable,
- settings load correctly in local dev.

### Unit 0.3: Contracts and streaming primitives

Deliver:
- SSE event schema,
- response envelope conventions,
- error shape conventions,
- backend-to-frontend event typing plan.

Exit check:
- dummy query can emit `STEP_START`, `TOKEN`, `COMPLETE`,
- frontend can consume and render those events.

## 6. Phase 1: Canonical Legal Data Layer

Goal:
- implement the legal model before any retrieval shortcuts appear.

### Unit 1.1: Core legal models

Implement:
- `LegalDocument`
- `AppealNode`
- `StatuteDocument`
- `Section`
- `Amendment`
- `DocumentChunk`
- `CaseContext`
- validity enums
- citation edge model

Must include:
- provenance fields,
- canonical `doc_id`,
- relationship integrity,
- timestamps and parser versioning.

Exit check:
- models serialize and validate,
- migrations create required tables,
- seed fixtures can insert and query round-trip.

### Unit 1.2: Canonical source/provenance ledger

Implement:
- source registry,
- ingestion run tracking,
- checksum tracking,
- approval status,
- parser version persistence.

Exit check:
- every ingested record can be traced to source URL and ingestion run.

### Unit 1.3: BNS / BNSS / BSA mapping tables

Implement:
- old-to-new criminal code mapping storage,
- lookup helpers,
- migration-safe updates,
- query-time resolution helpers.

Exit check:
- representative mappings resolve correctly,
- pre/post-July-2024 logic can be unit tested.

## 7. Phase 2: Ingestion Framework

Goal:
- create reusable ingestion architecture, not ad hoc scrapers.

### Unit 2.1: Ingestion adapter interface

Define one adapter contract with stages:
- fetch,
- normalize,
- parse,
- extract metadata,
- extract citations,
- resolve appeal links where possible,
- chunk,
- embed,
- project to stores.

Exit check:
- one mock adapter and one real adapter conform to the same interface.

### Unit 2.2: Archetype source adapters

Build first:
- Constitution and amendments,
- India Code,
- BNS / BNSS / BSA,
- Supreme Court judgments,
- one High Court,
- one tribunal.

Exit check:
- each archetype source lands in canonical DB with full metadata,
- one end-to-end ingestion run succeeds for each archetype.

### Unit 2.3: Citation extraction and graph projection

Implement:
- citation parsing,
- typed edge classification,
- graph export to Neo4j,
- doc-to-doc linkage storage.

Exit check:
- known sample judgments create correct graph edges,
- graph queries return expected neighbors.

### Unit 2.4: Appeal-chain builder

Implement:
- appeal-chain discovery,
- final-authority resolution,
- persistence of appeal graph,
- modified/reversed/upheld handling.

Exit check:
- seeded multi-level appeal fixtures resolve to final authority correctly.

### Unit 2.5: Daily validity engine

Implement:
- statute revalidation,
- amendment propagation,
- judgment overruling updates,
- re-embedding flags,
- stale projection invalidation.

Exit check:
- seeded repeal/amendment/overrule fixtures update derived state correctly.

## 8. Phase 3: Chunking, Indexing, and Retrieval Stores

Goal:
- build legal-aware retrieval foundations before generation.

### Unit 3.1: Legal-aware chunker

Implement chunking rules for:
- headnotes,
- ratio paragraphs,
- obiter,
- statutory sections,
- long sections with subsections,
- constitutional articles,
- Law Commission reports.

Exit check:
- sample docs chunk at correct legal boundaries,
- chunks preserve section/article identity.

### Unit 3.2: Embedding pipeline

Implement:
- BGE-M3 embedding service interface,
- batch embedding jobs,
- metadata-rich Qdrant writes,
- embedding version tracking.

Exit check:
- embeddings stored for sample corpus,
- re-embedding can be triggered by model/version changes.

### Unit 3.3: Qdrant collection manager

Create collections:
- `sc_judgments`
- `hc_judgments`
- `statutes`
- `constitution`
- `tribunal_orders`
- `lc_reports`
- `doctrine_clusters`

Exit check:
- collection filters work for validity, date, jurisdiction, bench size, act, section, and doctrine fields.

### Unit 3.4: Lexical retrieval layer

Implement:
- BM25 or equivalent lexical search abstraction,
- legal-aware tokenization,
- section/citation-preserving token handling,
- synonym and BNS expansion hooks.

Exit check:
- exact section-number and case-name queries retrieve the expected candidates.

## 9. Phase 4: Query Router and Core Pipelines

Goal:
- retrieval becomes query-type aware.

### Unit 4.1: Query router

Implement:
- rule-first query classification,
- jurisdiction extraction,
- practice area classification,
- temporal detection,
- BNS/BNSS/BSA transition flags,
- vague-query detection,
- multi-hop detection,
- uploaded-doc routing.

Exit check:
- curated query set routes to correct pipeline type.

### Unit 4.2: Hybrid RAG

Implement stages:
- lexical retrieval,
- dense retrieval,
- reciprocal-rank fusion,
- cross-encoder reranking,
- authority ranking.

Exit check:
- statutory and case-specific benchmark queries return relevant binding context.

### Unit 4.3: GraphRAG

Implement:
- concept anchor lookup,
- bidirectional traversal,
- overruling pruning,
- timeline construction,
- chunk fetch from graph results.

Exit check:
- doctrinal query returns an ordered chain instead of isolated chunks.

### Unit 4.4: CRAG

Implement:
- relevance scoring,
- entity coverage,
- `PROCEED` / `REFINE` / `INSUFFICIENT`,
- temporal check integration,
- optional tightly scoped web supplementation interface.

Exit check:
- weak retrieval paths are flagged or refined, not silently used.

### Unit 4.5: HyDE

Implement:
- hypothetical judgment generation,
- hypothetical embedding,
- fusion with original-query lexical retrieval,
- fallback when hypothetical quality is poor.

Exit check:
- vague-query retrieval improves against baseline Hybrid-only retrieval.

## 10. Phase 5: Zero-Hallucination Layer

Goal:
- prevent both fabricated and misgrounded legal output.

### Unit 5.1: Placeholder-only generator

Implement:
- prompt contract that forbids raw citations,
- placeholder grammar for case and statute references,
- unsupported-claim marker path.

Exit check:
- generation output contains placeholders only.

### Unit 5.2: Citation resolver

Implement:
- placeholder parsing,
- match against retrieved chunks,
- fallback corpus search,
- `VERIFIED` vs `UNVERIFIED` outputs,
- source text capture.

Exit check:
- fake or ambiguous placeholders never become invented citations.

### Unit 5.3: Misgrounding checker

Implement:
- passage extraction within source doc,
- semantic similarity scoring,
- NLI/entailment verification,
- downgrade/reretrieve behavior.

Exit check:
- seeded misgrounded examples are caught.

### Unit 5.4: Appeal validator

Implement:
- pending appeal warnings,
- reversed authority redirects,
- modified-authority notes,
- final-authority substitution.

Exit check:
- reversed judgment cannot survive as the surfaced authority.

### Unit 5.5: Self-RAG verifier

Implement:
- claim extraction,
- per-claim verification status,
- reretrieve-on-unsupported loop,
- final answer status map.

Exit check:
- unsupported claims are labeled or reretrieved before output finalization.

### Unit 5.6: Structured answer builder

Implement:
- legal position section,
- applicable law section,
- key cases section,
- verification status section,
- inline citation badge data model.

Exit check:
- final answer can render claim-level citation statuses and source hooks.

## 11. Phase 6: Evaluation and Trust Infrastructure

Goal:
- make trust measurable and public.

### Unit 6.1: Retrieval benchmark suite

Implement:
- Precision@K,
- Recall@K,
- MRR,
- nDCG,
- MAP.

Exit check:
- retrieval benchmark runs on curated legal query set.

### Unit 6.2: Answer-quality suite

Implement:
- BERTScore,
- ROUGE-L,
- METEOR,
- RAGAS metrics,
- DeepEval metrics.

Exit check:
- answer metrics can run against reference sets.

### Unit 6.3: India-legal evaluation suite

Implement:
- Citation Existence Rate,
- Citation Accuracy Rate,
- Appeal Chain Accuracy,
- Jurisdiction Binding Accuracy,
- Temporal Validity Rate,
- Amendment Awareness Rate,
- Multi-hop Completeness,
- BNS/BNSS/BSA Awareness.

Exit check:
- all India-specific metrics can be computed from benchmark outputs and stored.

### Unit 6.4: Trust dashboard backend

Implement:
- evaluation run persistence,
- public metrics endpoint,
- update date and benchmark metadata,
- historical run storage.

Exit check:
- trust endpoint serves only measured data.

## 12. Phase 7: Document Upload and Agentic Workflows

Goal:
- turn uploads into persistent legal context.

### Unit 7.1: File ingestion and OCR

Implement:
- typed PDF extraction,
- scanned PDF OCR,
- image OCR,
- DOCX extraction,
- page-type classification,
- confidence scoring.

Exit check:
- one sample from each input type processes successfully.

### Unit 7.2: OCR cleanup and legal normalization

Implement:
- legal spelling dictionary,
- citation regex correction,
- section-format normalization,
- party deduplication.

Exit check:
- representative OCR errors normalize correctly.

### Unit 7.3: CaseContext builder

Implement:
- parties,
- charges,
- BNS equivalents,
- facts timeline,
- prior orders,
- open legal issues,
- confidence score.

Exit check:
- uploaded docs produce a persistent and queryable `CaseContext`.

### Unit 7.4: LangGraph workflow

Implement:
- document understanding,
- research planning,
- statutory research,
- precedent research,
- contradiction checking,
- synthesis,
- verification,
- agent logging.

Exit check:
- uploaded-doc query takes the agentic path and emits full agent logs.

## 13. Phase 8: Frontend Productization

Goal:
- turn backend capability into a trust-heavy legal workspace.

### Unit 8.1: Design system

Implement:
- typography tokens,
- color tokens,
- spacing rules,
- citation badge variants,
- monospace process panel styling.

Exit check:
- components reflect legal-library visual language rather than generic startup UI.

### Unit 8.2: Landing page

Implement:
- hero,
- trust number,
- dashboard preview,
- pricing,
- proof-oriented structure.

Exit check:
- the page communicates trust and product positioning in one screenful.

### Unit 8.3: Workspace shell

Implement:
- three-panel layout,
- query input,
- case context sidebar,
- source viewer panel.

Exit check:
- the workspace can support research flow before final styling polish.

### Unit 8.4: Live process display

Implement:
- SSE consumption,
- step rendering,
- running/completed/error states,
- fade into answer stream.

Exit check:
- live backend steps appear in the UI in order.

### Unit 8.5: Structured answer rendering

Implement:
- answer sections,
- inline citation badges,
- hover/click source binding,
- verification summary block.

Exit check:
- a verified answer can be navigated end to end with source evidence.

### Unit 8.6: Citation graph and transparency drawer

Implement:
- D3 citation graph,
- agent log drawer,
- graph-to-source linking.

Exit check:
- cited nodes link back to documents and logs reflect actual backend events.

### Unit 8.7: Upload and workspace persistence UI

Implement:
- drag-and-drop upload,
- OCR progress,
- case context display,
- history and saved answers,
- export hooks.

Exit check:
- user can upload, query, revisit workspace, and inspect prior outputs.

## 14. Phase 9: Commercial and Launch Systems

Goal:
- make the product launchable without weakening the trust model.

### Unit 9.1: Auth

Implement:
- Clerk integration,
- protected workspaces,
- session-aware query history.

### Unit 9.2: Billing

Implement:
- Razorpay subscriptions,
- plan enforcement,
- free-tier query limit,
- invoice/billing history hooks.

### Unit 9.3: Public trust page

Implement:
- `/trust` frontend,
- dashboard rendering,
- benchmark metadata display,
- update timestamp.

### Unit 9.4: Launch assets

Implement:
- comparison demo workflow,
- benchmark storytelling,
- initial distribution checklist.

## 15. Definition of Done By Phase

No phase is done because code exists. A phase is done only when:
- its core features work,
- its tests pass,
- its outputs match the architecture,
- and it does not break the trust invariants.

Phase-specific done definition:
- Foundation: stack runs locally end to end.
- Data: canonical legal records exist and can be queried.
- Retrieval: router and pipelines return correct context.
- Verification: fabricated/misgrounded output is blocked or labeled.
- Evaluation: benchmark runs and stores results.
- Upload: documents become reusable case context.
- Frontend: lawyer can see system process and sources live.
- Launch: trust page and pricing enforcement are live.

## 16. Suggested Session Order For Codex

Recommended first 12 active units:
1. Unit 0.1 Monorepo bootstrap
2. Unit 0.2 Backend foundations
3. Unit 1.1 Core legal models
4. Unit 1.2 Provenance ledger
5. Unit 2.1 Ingestion adapter interface
6. Unit 2.2 Constitution and India Code adapters
7. Unit 2.3 Citation extraction and graph projection
8. Unit 3.1 Legal-aware chunker
9. Unit 3.2 Embedding pipeline
10. Unit 4.1 Query router
11. Unit 4.2 Hybrid RAG
12. Unit 5.1 Placeholder-only generator

That order gives the fastest path to a real NyayaRAG spine without prematurely building shiny UI over weak legal foundations.

## 17. Future Codex Prompt Template

Use this structure:

```text
You are building NyayaRAG.

Read:
1. NYAYARAG_MASTER_MEMORY.md
2. NYAYARAG_EXECUTION_PLAYBOOK.md

Active phase: [phase]
Active unit: [unit]

Do not simplify the architecture.
Do not remove any verification layers.
Do not use raw citation strings as source identity.
Do not skip tests before closing the unit.

Build the unit completely, including supporting code and tests.
After implementation, verify the specific acceptance criteria for this unit.
```

## 18. Final Operating Principle

If a future session faces pressure between speed and trust, trust wins.

NyayaRAG only becomes valuable if the legal profession can rely on it more than they rely on generic AI. That happens only if the execution stays faithful to the architecture:

`route correctly -> retrieve correctly -> verify existence -> verify support -> verify authority -> verify current law -> show certainty honestly`
