# Vercel Supabase Chroma Cloud Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the existing Vite/FastAPI app on Vercel with Clerk authentication, Supabase PostgreSQL, and Chroma Cloud retrieval without requiring ignored local RAG files.

**Architecture:** A root FastAPI entrypoint lets Vercel package the backend as one Python Function, while a Vercel build command produces the existing frontend bundle served by FastAPI. Cloud retrieval uses Chroma documents directly when the optional local BM25/section store is absent; local development keeps hybrid retrieval when those files exist.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/psycopg, ChromaDB CloudClient, React/Vite, Vercel Functions, Supabase PostgreSQL.

## Global Constraints

- Keep Clerk authentication unchanged.
- Supabase is PostgreSQL only; add no Supabase SDK.
- Never commit credentials or the production `DATABASE_URL`.
- Keep local hybrid retrieval working when `data/indexes/local_rag` exists.
- Use the existing Chroma Cloud collection `local_rag` in database `Respiratory`.

---

### Task 1: Make cloud retrieval independent of local index files

**Files:**
- Modify: `web_app/backend/services.py`
- Test: `tests/test_services.py`

**Interfaces:**
- Consumes: `AppSettings.chroma_mode`, `AppSettings.hybrid_index_dir`, and Chroma query results.
- Produces: `RetrievalEngine.search()` that returns dense Chroma candidates when no local `HybridIndex` is available.

- [ ] **Step 1: Write the failing test**

Add a test that constructs a retrieval engine with `hybrid_index=None`, calls `search()`, and expects Chroma candidates ordered by vector rank without accessing local files.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_services.RetrievalEngineTests.test_search_uses_chroma_without_local_hybrid_index -v`

Expected: failure caused by calling `lexical_search` on `None`.

- [ ] **Step 3: Write minimal implementation**

Instantiate `HybridIndex` only when its required files exist. Allow the section store/index to be empty. In `search()`, return dense candidates directly when no hybrid index is loaded; preserve the current fusion branch otherwise.

- [ ] **Step 4: Run focused and existing service tests**

Run: `python -m unittest tests.test_services -v`

Expected: all service tests pass.

### Task 2: Add the Vercel deployment entrypoint and build configuration

**Files:**
- Create: `app.py`
- Create: `vercel.json`
- Modify: `tests/test_repository_contract.py`

**Interfaces:**
- Consumes: `web_app.backend.main.app` and `web_app/frontend/package-lock.json`.
- Produces: Vercel-recognized root `app` and a build that generates `web_app/frontend/dist`.

- [ ] **Step 1: Write failing repository contract assertions**

Assert that `app.py` re-exports the backend application and `vercel.json` builds the frontend, includes the built bundle in the Python function, and sets a bounded function duration.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_repository_contract -v`

Expected: failure because `app.py` and `vercel.json` do not exist.

- [ ] **Step 3: Add minimal deployment files**

Create `app.py` containing `from web_app.backend.main import app`, and create `vercel.json` with the frontend build command plus Python-function inclusion/duration settings.

- [ ] **Step 4: Run repository contract tests**

Run: `python -m unittest tests.test_repository_contract -v`

Expected: all contract tests pass.

### Task 3: Document production environment and verify the deployable build

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `tests/test_repository_contract.py`

**Interfaces:**
- Consumes: Vercel environment variables and the Supabase transaction-pooler URL.
- Produces: a credential-free deployment checklist using `DATABASE_URL`, Clerk, Chroma Cloud, SiliconFlow, and Groq variables.

- [ ] **Step 1: Add failing env-contract assertions**

Require `.env.example` to list `DATABASE_URL`, Chroma cloud mode/key/tenant/database, and existing Clerk/AI keys without real values.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_repository_contract -v`

Expected: failure because the cloud variables are absent.

- [ ] **Step 3: Add minimal env template and deployment instructions**

Document the URL-encoded Supabase password form with `sslmode=require`, Vercel environment setup, and the health/chat checks. Do not include real credentials.

- [ ] **Step 4: Run full verification**

Run:

```text
python -m unittest discover -s tests -v
npm run lint --prefix web_app/frontend
npm run build --prefix web_app/frontend
python -m compileall -q scripts web_app app.py
```

Expected: every command exits 0.
