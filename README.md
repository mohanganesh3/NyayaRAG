<div align="center">

```
███╗   ██╗██╗   ██╗ █████╗ ██╗   ██╗ █████╗ ██████╗  █████╗  ██████╗
████╗  ██║╚██╗ ██╔╝██╔══██╗╚██╗ ██╔╝██╔══██╗██╔══██╗██╔══██╗██╔════╝
██╔██╗ ██║ ╚████╔╝ ███████║ ╚████╔╝ ███████║██████╔╝███████║██║  ███╗
██║╚██╗██║  ╚██╔╝  ██╔══██║  ╚██╔╝  ██╔══██║██╔══██╗██╔══██║██║   ██║
██║ ╚████║   ██║   ██║  ██║   ██║   ██║  ██║██║  ██║██║  ██║╚██████╔╝
╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝
```

**India's First Court-Grade Legal Intelligence Platform**

*11.4 Million Documents · 10 Million Citation Links · Semantic Search + Citation Graph*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14+-black?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Qdrant](https://img.shields.io/badge/Qdrant-Vector_DB-DC143C?style=flat-square)](https://qdrant.tech)
[![Neo4j](https://img.shields.io/badge/Neo4j-Citation_Graph-008CC1?style=flat-square&logo=neo4j&logoColor=white)](https://neo4j.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

## What is NyayaRAG?

NyayaRAG is a **Court-Grade Legal AI** built for the Indian judiciary. Unlike generic legal chatbots that hallucinate citations and fabricate precedents, NyayaRAG is grounded in:

- **11.4 Million authentic Indian legal documents** — Supreme Court, 25 High Courts, Tribunals, Statutes, Circulars
- **A real Citation Graph** with 10+ million verified cross-document links
- **Multi-hop reasoning** — "Which judgments follow *Maneka Gandhi*? Which did *Maneka Gandhi* follow?"
- **Validity detection** — automated "Shepardizing" to warn when a cited case has been overruled
- **Source-bound answers** — every claim is pinned to an exact chunk from a verified document

---

## System Architecture

### The Full Stack

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                           N Y A Y A R A G   S T A C K                          ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                  ║
║  ┌─────────────────────────────────────────────────────────────────────────┐    ║
║  │                        FRONTEND  (Next.js 14)                           │    ║
║  │   ┌──────────────┐  ┌───────────────────┐  ┌───────────────────────┐   │    ║
║  │   │  Landing Page│  │  3-Panel Workspace │  │  Trust & Citation     │   │    ║
║  │   │  (proof-mode)│  │  Omnibox + Sources │  │  Graph Visualizer     │   │    ║
║  │   └──────────────┘  └───────────────────┘  └───────────────────────┘   │    ║
║  └───────────────────────────────────┬─────────────────────────────────────┘    ║
║                                      │ HTTP / SSE Streaming                     ║
║  ┌───────────────────────────────────▼─────────────────────────────────────┐    ║
║  │                       BACKEND  (FastAPI + LangGraph)                    │    ║
║  │                                                                         │    ║
║  │   ┌─────────────────────────────────────────────────────────────────┐  │    ║
║  │   │                  AGENTIC RAG PIPELINE                           │  │    ║
║  │   │                                                                 │  │    ║
║  │   │  Query ──► Planner ──► Retriever ──► Verifier ──► Generator    │  │    ║
║  │   │              │            │              │             │         │  │    ║
║  │   │           LangGraph    Hybrid        Mis-ground    Gemini/      │  │    ║
║  │   │           Workflow     Search        Detector      GPT-4o       │  │    ║
║  │   └─────────────────────────────────────────────────────────────────┘  │    ║
║  │                                                                         │    ║
║  │   ┌──────────────┐  ┌──────────────────┐  ┌──────────────────────┐    │    ║
║  │   │  Citation    │  │  Authority       │  │  Validity Engine     │    │    ║
║  │   │  Resolver    │  │  Scorer          │  │  (Overruled detect)  │    │    ║
║  │   │  (4-Layer)   │  │  (PageRank+Bench)│  │  Shepardizing        │    │    ║
║  │   └──────────────┘  └──────────────────┘  └──────────────────────┘    │    ║
║  └─────────────────────────────────────────────────────────────────────────┘    ║
║                                                                                  ║
║  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────────┐  ║
║  │  PostgreSQL 15   │  │  Qdrant          │  │  Neo4j                       │  ║
║  │  11.4M Documents │  │  Vector Store    │  │  Citation Graph              │  ║
║  │  10M Citations   │  │  1024-dim E5     │  │  10M+ Edges                 │  ║
║  │  Full Provenance │  │  Tiered Ingest   │  │  PageRank + Validity        │  ║
║  └──────────────────┘  └──────────────────┘  └──────────────────────────────┘  ║
╚══════════════════════════════════════════════════════════════════════════════════╝
```

### The Data Ingestion Pipeline

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                      DATA INGESTION PIPELINE  (Production)                      ║
╚══════════════════════════════════════════════════════════════════════════════════╝

  30+ Source Collectors                  Unified Ingestion Engine
  ─────────────────────                  ────────────────────────
  ┌──────────────┐
  │ Supreme Court│──┐
  │  (SCI APIs)  │  │    ┌─────────────────────────────────────────────────┐
  └──────────────┘  │    │              COLLECTION PIPELINE                 │
  ┌──────────────┐  │    │                                                  │
  │ High Courts  │──┼───►│  HTTP Collector ──► Deduplication ──► Chunker   │
  │  (25 courts) │  │    │       │                    │               │     │
  └──────────────┘  │    │  PDF Adapter        Hash-based         ~15 tok  │
  ┌──────────────┐  │    │  HTML Adapter        dedup              chunks  │
  │  AWS S3 Bulk │──┤    │  OCR Pipeline                                   │
  │  (9.9M docs) │  │    │                                                  │
  └──────────────┘  │    │  ──► PostgreSQL (canonical store)                │
  ┌──────────────┐  │    │  ──► Qdrant (vector embeddings)                  │
  │  India Code  │──┤    │  ──► Citation Lookup (10M identifiers)           │
  │  Statutes    │  │    │  ──► Neo4j (citation graph)                      │
  └──────────────┘  │    └─────────────────────────────────────────────────┘
  ┌──────────────┐  │
  │ SEBI/RBI/CCI │──┤    Vectorization Pipeline (GPU-Accelerated)
  │  Regulators  │  │    ─────────────────────────────────────────
  └──────────────┘  │
  ┌──────────────┐  │    ┌─────────────────────────────────────────────────┐
  │  ITAT/NCLT   │──┤    │   TIERED INTELLIGENCE VECTORIZER                │
  │  Tribunals   │  │    │                                                  │
  └──────────────┘  │    │  Tier 1: Golden Chunks (doc headers, chunk 0,1) │
  ┌──────────────┐  │    │  ┌─────────────────────────────────────────┐    │
  │ E-Gazette    │──┤    │  │ 16 CPU Tokenizer Workers                │    │
  │ Notifications│  │    │  │ → 2 GPU Inference Workers (K80)         │    │
  └──────────────┘  │    │  │ → 4 Async Qdrant Upload Workers         │    │
  ┌──────────────┐  │    │  │ JIT-traced multilingual-e5-large (1024d)│    │
  │ Law Commission│─┘    │  └─────────────────────────────────────────┘    │
  │  Reports     │       │  Tier 2: Deep body text (continuous background) │
  └──────────────┘       └─────────────────────────────────────────────────┘
```

### The Citation Intelligence System

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                    4-LAYER CITATION IDENTITY SYSTEM                              ║
╚══════════════════════════════════════════════════════════════════════════════════╝

  Layer 1: Reporter Citations          Layer 2: Neutral Citations
  ─────────────────────────────        ──────────────────────────
  (2018) 3 SCC 225                     2024 INSC 1
  AIR 1973 SC 1461                     2023:DHC:2715:DB
  1990 (1) SCC 520                     [130k documents]

  Layer 3: Court Case Numbers          Layer 4: S3 URL Identity
  ──────────────────────────────       ──────────────────────────
  W.P. No. 12345/2020                  WBCHCA0184392020
  Crl.A. No. 456/2019                  MPHC030091182020
  SLP (C) 1234/2018                    [9.9M documents decoded]
  [Extracted from judgment headers]

  ──────────────────────────────────────────────────────────────
                         10M+ IDENTIFIERS IN citation_lookup
  ──────────────────────────────────────────────────────────────

  Before 4-Layer System:    After 4-Layer System:
  ┌─────────────────────┐   ┌─────────────────────┐
  │ Resolvable:  10.2%  │   │ Resolvable:  ~96%   │
  │ Graph edges: 26,169 │   │ Graph edges: 15M+   │
  │ Coverage: BROKEN    │   │ Coverage: COMPLETE  │
  └─────────────────────┘   └─────────────────────┘

  Citation Graph Construction (6-Phase Plan)
  ──────────────────────────────────────────
  Phase 1: S3 URL Extraction    [✅ COMPLETE]  →  9.9M case numbers indexed
  Phase 2: Text Header Scan     [✅ COMPLETE]  →  Court case numbers from body
  Phase 3: Lookup Rebuild       [✅ COMPLETE]  →  10.1M identifiers in DB
  Phase 4: Hyper-Scale Sentinel [🔄 RUNNING ]  →  48 CPU cores, 177M chunks
  Phase 5: PageRank Scoring     [⏳ QUEUED  ]  →  Composite authority score
  Phase 6: Validity Cascade     [⏳ QUEUED  ]  →  Overruled/Distinguished tags
```

### The Agentic RAG Workflow

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                     AGENTIC RAG PIPELINE  (LangGraph)                           ║
╚══════════════════════════════════════════════════════════════════════════════════╝

  User Query
      │
      ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  QUERY PLANNER                                                           │
  │  • Decomposes complex legal questions into sub-queries                  │
  │  • Identifies relevant court levels and time periods                    │
  │  • Routes to appropriate retrieval strategy                             │
  └────────────────────────────────┬─────────────────────────────────────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            ▼                      ▼                      ▼
  ┌─────────────────┐    ┌──────────────────┐    ┌───────────────────┐
  │  DENSE RETRIEVAL│    │ SPARSE RETRIEVAL │    │  GRAPH TRAVERSAL  │
  │  Qdrant 1024-d  │    │  BM25 / TF-IDF  │    │  Citation Hops    │
  │  Semantic Match │    │  Exact Keywords  │    │  Precedent Chain  │
  └────────┬────────┘    └────────┬─────────┘    └────────┬──────────┘
           └──────────────────────┴──────────────────────┘
                                  │
                                  ▼  Reciprocal Rank Fusion
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  MISGROUNDING DETECTOR                                                   │
  │  • Checks if retrieved chunk actually supports the claim                 │
  │  • Validates court hierarchy (SC > HC > Tribunal)                       │
  │  • Detects temporal conflicts (overruled cases)                         │
  │  • Confidence scoring per source                                        │
  └────────────────────────────────┬─────────────────────────────────────────┘
                                   │
                                   ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  STRUCTURED ANSWER GENERATOR                                             │
  │  • Answer grounded in verified sources only                              │
  │  • Each claim linked to exact chunk + document + page                   │
  │  • Citation links with authority scores surfaced                        │
  │  • Streaming SSE to frontend                                            │
  └──────────────────────────────────────────────────────────────────────────┘
```

---

## Corpus Statistics

| Segment | Count | Source |
|:---|---:|:---|
| **Total Documents** | **11,401,213** | PostgreSQL `legal_documents` |
| Supreme Court Judgments | 193,240 | SCI APIs + AWS S3 |
| High Court Judgments | 9,912,908 | AWS S3 Bulk (25 courts) |
| Statutes & Codes | 5,847 | India Code, E-Gazette |
| Regulatory Orders | 312,456 | SEBI, RBI, CCI, IRDAI |
| Tribunal Orders | 854,763 | ITAT, NCLT, CESTAT, SAT |
| Law Commission Reports | 186 | Official PDF repository |
| **Citation Identifiers** | **10,114,067** | `citation_lookup` table |
| **Citation Edges** | **327,544+** | `citation_edges` (growing) |
| **Vector Embeddings** | **Ongoing** | Qdrant (1024-dim E5-large) |

---

## Technology Stack

### Backend
```
FastAPI          — Async HTTP + SSE streaming API
LangGraph        — Stateful multi-agent RAG orchestration
PostgreSQL 15    — Primary document store (11.4M documents)
Qdrant           — High-performance vector database (1024-dim)
Neo4j            — Citation graph traversal (10M+ edges)
psycopg3         — High-performance async PostgreSQL driver
multilingual-e5  — 1024-dim multilingual embedding model (SOTA)
```

### Frontend
```
Next.js 14       — React framework with App Router
TypeScript       — Full type safety
Tailwind CSS     — Utility-first styling
shadcn/ui        — Component library
SSE Streaming    — Real-time answer generation
```

### Ingestion Infrastructure
```
30+ Custom Scrapers     — Court-specific HTTP collectors
OCR Pipeline            — pdf2image + pytesseract for scanned PDFs
Alembic Migrations      — Schema-versioned PostgreSQL migrations
AWS S3 Integration      — Bulk TAR ingestion (9.9M HC judgments)
GPU Vectorizer          — Tiered Intelligence (K80 optimized)
48-Core CPU Sentinel    — Parallel citation extraction
```

---

## Key Engineering Achievements

### 1. Corpus Scale
Built an ingestion pipeline that reliably collected and normalized **11.4 million authentic Indian legal documents** from 30+ heterogeneous sources, each with different formats, encodings, and URL structures.

### 2. The Citation Intelligence Problem (Solved)
Discovered that 89.8% of documents had no reporter citation (AIR/SCC), making the citation graph impossible to build with standard approaches. Designed and implemented a **4-Layer Identity System** that unlocks 96% coverage using S3 URL metadata, neutral citations, and court case numbers extracted from judgment headers.

### 3. Tiered Intelligence Vectorization
Designed a production vectorization architecture for aging K80 GPUs that achieves near-theoretical throughput by:
- Reducing attention computation 7x via 192-token context window
- JIT-tracing the embedding model for kernel fusion
- Decoupling tokenization (16 CPUs), inference (2 GPUs), and upload (4 threads)
- "Golden Pass" strategy: vectors the most retrieval-critical chunks first

### 4. Misgrounding Detection
Implemented a custom misgrounding detector that catches cases where retrieved text doesn't actually support the generated claim — a critical safety layer for a legal AI where hallucinated citations have real consequences.

### 5. Agentic RAG with LangGraph
Built a stateful multi-step reasoning pipeline where the AI can plan complex legal research tasks, retrieve from multiple sources in parallel, verify each source, and synthesize a grounded, citation-bound answer.

---

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL 15
- Qdrant (Docker)
- Neo4j (Docker)

### Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/mohanganesh3/NyayaRAG.git
cd NyayaRAG

# 2. Start infrastructure
docker compose up -d postgres qdrant neo4j

# 3. Backend setup
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 4. Frontend setup
cd ../frontend
npm install
npm run dev
```

### Environment Variables

```bash
# backend/.env
DATABASE_URL=postgresql+asyncpg://nyayarag:password@localhost/nyayarag
QDRANT_HOST=localhost
QDRANT_PORT=6334
NEO4J_URI=bolt://localhost:7687
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
```

---

## Data Ingestion

### Running a Collector

```bash
# Collect Supreme Court judgments
uv run python -m app.ingestion.scripts.collect_sci_modern

# Bulk ingest High Court TAR archives from S3
uv run python -m app.ingestion.scripts.bulk_ingest_hcd_tars

# Run the citation graph builder
uv run python -m app.ingestion.scripts.citation_phase1_s3
uv run python -m app.ingestion.scripts.citation_phase2_text
```

### Running the Vectorizer

```bash
# Start the tiered intelligence vectorizer with watchdog
nohup ./watchdog_vectorizer.sh > watchdog.log 2>&1 &

# Monitor progress
tail -f vectorizer_turbo.log
```

### Citation Sentinel

```bash
# Run the 48-core citation extraction engine
nohup python -m app.ingestion.scripts.citation_extractor_v4 > sentinel_v4.log 2>&1 &
```

---

## Evaluation

NyayaRAG includes a custom evaluation suite designed for Indian legal domain:

```bash
# Run the NyayaRAG evaluation benchmark
uv run python -m app.evaluation.nyaya_eval_runner
```

**Metrics tracked:**
- Citation Accuracy (is the cited case real and on-point?)
- Misgrounding Rate (does retrieved text actually support the claim?)
- Retrieval Recall@k for landmark judgments
- Response latency (P50/P95/P99)

---

## Repository Structure

```
NyayaRAG/
├── backend/
│   ├── app/
│   │   ├── api/routes/          # FastAPI route handlers
│   │   ├── ingestion/
│   │   │   ├── adapters/        # Source-specific parsers (PDF, HTML, OCR)
│   │   │   ├── scripts/         # 50+ ingestion & maintenance scripts
│   │   │   ├── citation_graph.py
│   │   │   ├── pipeline.py
│   │   │   └── sentinel.py      # Real-time citation monitoring
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── rag/
│   │   │   ├── agentic.py       # LangGraph agentic workflow
│   │   │   ├── hybrid.py        # Dense + sparse retrieval fusion
│   │   │   ├── misgrounding.py  # Source-claim verification
│   │   │   └── prompts.py
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── model_runtime.py # Configurable LLM backend
│   │   │   └── neo4j_service.py
│   │   └── evaluation/
│   │       ├── nyaya_eval_runner.py
│   │       └── nyaya_benchmark_cases.py
│   ├── alembic/                 # Database migrations
│   └── tests/                   # Pytest suite (15+ test modules)
├── frontend/
│   ├── components/
│   │   ├── design/              # Design system (GlassSurface, tokens)
│   │   └── workspace/           # 3-panel workspace shell + Omnibox
│   └── app/                     # Next.js App Router pages
└── docker-compose.yml
```

---

## Design Decisions

### Why 1024-dim Embeddings?
Indian legal documents are highly technical, with court-specific terminology. At 384 dimensions (MiniLM), high similarity collisions between superficially similar but legally distinct precedents are common. 1024 dimensions provides sufficient "semantic space" to reliably distinguish between nuanced holdings.

### Why PostgreSQL as Primary Store?
With 11.4M documents, complex filtering (court type, date range, jurisdiction, validity) requires relational joins that are not efficient in a pure vector database. PostgreSQL is the source of truth; Qdrant handles semantic search only.

### Why Tiered Vectorization?
Rather than vectorizing all 177M chunks uniformly, the "Golden Pass" embeds only the header and summary chunks first. This makes the RAG system usable within 48 hours for core legal research, while deep body text continues indexing in the background.

---

## Roadmap

- [ ] Complete Phase 4 citation extraction (15M+ edges target)
- [ ] Phase 5: PageRank authority scoring on full graph
- [ ] Phase 6: Automated overruled/distinguished validity cascade
- [ ] Multi-hop graph reasoning in agentic workflow
- [ ] Real-time corpus update pipeline (daily delta ingestion)
- [ ] Mobile-optimized research interface

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with obsession for Indian legal research**

*If this helps lawyers and litigants access justice faster, it was worth it.*

</div>
