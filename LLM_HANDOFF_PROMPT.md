# NyayaRAG: LLM Handoff Prompt (Saturation Status: 100%)

You are taking over **NyayaRAG**, a mission-critical legal research system for **Indian Law**.

## Core Knowledge Handover
Read these files first as the canonical source of truth for the project vision and status:
- `/Users/mohanganesh/project002/NYAYARAG_COLLECTION_MASTER_STRATEGY.md`
- `/Users/mohanganesh/project002/NYAYARAG_REVISED_EXECUTION_STRATEGY.md`
- `/Users/mohanganesh/project002/data/collection/CORPUS_STATUS.md`
- `/home/mohanganesh/project002/LLM_KNOWLEDGE_TRANSFER.md` (Crucial: 12.63M Ingestion Audit).

### 1. The 12.63 Million Ingestion Victory
As of April 5, 2026, the **Wave 6 (Full Saturation)** has been successfully executed.
- **Corpus Target**: 12.63M documents.
- **Live Server Status**: **12,631,044 documents** collected and verified in `staging`.
- **Courts Covered**: **Supreme Court (Full History)** and **25 High Courts (Full History)**.
- **India Code**: 100% complete (843 Acts, 35k sections).

### 2. Infrastructure (Dell R730)
- **Host**: `61.1.175.170` (Linux/Ubuntu).
- **CPU**: 48 Threads (Used to achieve **500k documents/hr** velocity).
- **RAM**: 251 GiB.
- **Environment**: Rebuild the Python/FastAPI backend on the Linux server (do not trust macOS virtualenv binaries).

### 3. Immediate Mission (Next Steps)
1.  **Consolidation**: The 12,631,044 records are currently in **31 Sharded SQLite DBs** in `data/collection/staging/`. Your first task is to merge them into the main `live_corpus.db` without locking.
2.  **Statute Amendments**: Finish the **2024 Legal Reforms (BNS, BNSS, BSA)** ingestion as article-level objects.
3.  **Phase 5 (Answer Integrity)**: Build the **Citation Resolver** and **Misgrounding Checker**. We have the data; now we need the "Trust Gaps" to be closed.
4.  **District Court Discovery**: Plan the ingestion of the remaining **40M+ District Court** orders once the core High Court corpus is stable.

### 4. Technical Ground Rules
- **Layer A Integrity**: Canonical law only. No commentary or summaries.
- **Provenance**: Every record must have a valid portal source URL.
- **Zero-Block Scaling**: Use the `aws_bulk.py` pattern to bypass 503 portal errors.
- **Scale Calculation**: Verify counts with real SQL `count(*)` queries, not estimates.

**The NyayaRAG "Foundation" is complete. Your mission is now "Verification and Answer Integrity."**
