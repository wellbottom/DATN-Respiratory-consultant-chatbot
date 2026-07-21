# Vercel, Supabase PostgreSQL, and Chroma Cloud Design

## Goal

Deploy the existing React/FastAPI application as one Vercel project while keeping Clerk authentication, storing conversations in Supabase PostgreSQL, and retrieving RAG vectors from the existing Chroma Cloud `Respiratory` database.

## Architecture

Vercel builds the Vite frontend and runs the FastAPI application as one Python Function. FastAPI continues to verify Clerk JWTs. SQLAlchemy connects to Supabase through `DATABASE_URL`, and the existing Chroma adapter connects to Chroma Cloud using environment variables.

No Supabase JavaScript or Python client is added. Supabase is used only as managed PostgreSQL, so the existing SQLAlchemy models remain the database contract.

## Runtime configuration

Vercel receives these secrets and settings through its Environment Variables UI:

- `DATABASE_URL`: Supabase transaction-pooler PostgreSQL URL.
- `CHROMA_API_KEY`: rotated Chroma Cloud API key.
- `WEBAPP_CHROMA_MODE=cloud`.
- `WEBAPP_CHROMA_TENANT=f3848f2b-0188-476c-a987-e1d6eb6f9f2d`.
- `WEBAPP_CHROMA_DATABASE=Respiratory`.
- `SILICONFLOW_API_KEY` and `GROQ_API_KEY`.
- Existing Clerk publishable/JWKS settings and the production Vercel origin.

Secrets are never committed. The public Supabase URL and publishable key are unnecessary because the application does not use Supabase Auth or its client SDK.

## Backend and deployment changes

1. Add a root Vercel-recognized FastAPI entrypoint that re-exports `web_app.backend.main.app`.
2. Add the minimum Vercel build/routing configuration needed to build `web_app/frontend` and route requests through the existing FastAPI application.
3. Make cloud retrieval independent of local `data/indexes/local_rag` files. Chroma Cloud documents and metadata are the production source of retrieved content; local hybrid files remain available for local development only.
4. Keep the current `DATABASE_URL` normalization and SQLAlchemy models. Supabase schema tables continue to be created by the existing startup behavior.
5. Document the exact Vercel environment variables and deployment checks.

## Data flow

1. The browser obtains a Clerk session token and sends it to FastAPI.
2. FastAPI verifies the Clerk token and reads/writes conversations through SQLAlchemy using Supabase PostgreSQL.
3. For chat retrieval, FastAPI embeds the query with SiliconFlow, queries Chroma Cloud collection `local_rag`, reranks candidates, and calls the configured Groq-compatible LLM.
4. The existing SPA is returned for non-API routes.

## Failure handling

- Startup fails clearly when mandatory AI, database, Clerk, or Chroma variables are absent.
- Missing local hybrid-index files do not break cloud mode.
- Chroma, embedding, reranking, and LLM upstream failures continue to surface through the existing API error handling.
- SQLite remains the local-development fallback only; production configuration must provide `DATABASE_URL`.

## Verification

- Add focused tests proving cloud mode starts without the ignored local RAG index.
- Run the Python test suite and frontend type-check/build.
- Build with the Vercel configuration.
- Verify `/api/health`, Clerk-protected conversation access, Supabase persistence, and one Chroma-backed chat request after deployment.

## Out of scope

- Migrating authentication from Clerk to Supabase Auth.
- Adding `@supabase/server`, `supabase-js`, or a Python Supabase SDK.
- Moving ingestion into Vercel; corpus ingestion remains an explicit offline command.
