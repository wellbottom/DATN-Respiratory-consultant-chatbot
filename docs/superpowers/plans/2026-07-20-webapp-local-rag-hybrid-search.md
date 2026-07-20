# Webapp Local RAG Hybrid Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search only `local_rag` with Chroma HNSW plus the existing BM25 index, fuse results with RRF, and remove webapp retrieval routing.

**Architecture:** `RetrievalEngine` keeps Chroma as its dense branch and opens the existing local `HybridIndex` only for BM25 data and ranking. Candidate identities are normalized to `chunk_id`, fused with the existing `reciprocal_rank_fusion`, and sent through the current reranker and section expansion pipeline.

**Tech Stack:** Python 3, unittest, ChromaDB, SQLite BM25, existing RRF implementation.

## Global Constraints

- Only `local_rag` is queried.
- `WEBAPP_HYBRID_INDEX_DIR` defaults to `data/indexes/local_rag`.
- Missing lexical artifacts fail during retrieval initialization.
- No new dependency and no vector-only fallback.

---

### Task 1: Hybrid retrieval contract

**Files:**
- Modify: `tests/test_services.py`
- Modify: `web_app/backend/settings.py`
- Modify: `web_app/backend/services.py`

**Interfaces:**
- Consumes: `HybridIndex.lexical_search(query, top_k)` and `reciprocal_rank_fusion(ranked_lists, rrf_k=60)`.
- Produces: `RetrievalEngine.search(query, retrieval_query=None) -> tuple[QueryPlan, list[CandidateResult]]` with fused candidates.

- [ ] **Step 1: Write failing tests**

Add focused tests using `RetrievalEngine.__new__`, a fake embedder/collection, and a fake lexical index. Assert the Chroma query has no `where` filter, the BM25 and dense lists fuse by shared `chunk_id`, scores are preserved, and missing BM25 artifacts raise during normal initialization.

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python -m unittest tests.test_services -v`

Expected: FAIL because candidates lack BM25/RRF fields and search still performs routed corpus queries.

- [ ] **Step 3: Implement the minimum hybrid path**

Add `hybrid_index_dir: Path` to `AppSettings`, loaded from `WEBAPP_HYBRID_INDEX_DIR` or `<repo>/data/indexes/local_rag`. Construct `HybridIndex` in `RetrievalEngine`, query Chroma once without filters, query BM25 with the same candidate-pool size, map local chunks by `chunk_id`, fuse with existing RRF, and return the fused candidate pool.

- [ ] **Step 4: Verify GREEN**

Run: `.venv\Scripts\python -m unittest tests.test_services -v`

Expected: PASS.

### Task 2: Remove routing and verify the application

**Files:**
- Modify: `tests/test_services.py`
- Modify: `web_app/backend/services.py`
- Modify if score fields are exposed: `web_app/backend/schemas.py`, `web_app/frontend/src/types.ts`

**Interfaces:**
- Consumes: the single `RetrievalEngine` from Task 1.
- Produces: `MedicalAssistantService` with one `retrieval` engine and no specialized route selection.

- [ ] **Step 1: Write failing routing-removal test**

Assert the service chat path calls its single retrieval engine directly and that `SplitCorpusRetrievalEngine` is no longer exported.

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python -m unittest tests.test_services -v`

Expected: FAIL while split/routed engines still exist.

- [ ] **Step 3: Remove routing minimally**

Delete `SplitCorpusRetrievalEngine`, specialized engine initialization, routing helpers, and route diagnostics. Make `chat` use `self.retrieval`; keep contextualization, reranking, section expansion, fallback answer generation, and response payload behavior.

- [ ] **Step 4: Verify all tests and startup imports**

Run: `.venv\Scripts\python -m unittest discover -s tests -v`

Run: `.venv\Scripts\python -c "from web_app.backend.main import app; print(app.title)"`

Expected: all tests PASS and the app title prints without an exception.

- [ ] **Step 5: Restart and smoke-check localhost:8002**

Stop only the process listening on TCP port 8002, launch `scripts/run_webapp.ps1 -Port 8002` hidden, then request `http://127.0.0.1:8002/` and confirm an HTTP response.
