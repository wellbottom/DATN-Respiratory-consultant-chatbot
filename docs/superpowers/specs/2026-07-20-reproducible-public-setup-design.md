# Reproducible Public Setup Design

## Goal

A new user can clone the public repository, copy `.env.example` to `.env`, fill in credentials, run `scripts/setup.ps1`, and start the application with the same source, frontend, and RAG pipeline configuration used locally.

## Repository contents

Commit application source, PowerShell scripts, dependency lock files, tests, documentation, and `data/markdown`. Do not commit secrets, virtual environments, Node packages, logs, Python caches, generated frontend output, generated RAG indexes, Chroma storage, or the runtime application database.

`data/golden dataset` may remain in the public repository because the owner confirmed it is permitted for public distribution, but it is not required by the normal setup path.

## Setup flow

`scripts/setup.ps1` remains the single setup entry point. It will:

1. Verify Python and Node/npm are available.
2. Create `.venv` and install `requirements.txt` unless Python setup is skipped.
3. Create `.env` from `.env.example` only when `.env` does not exist.
4. Run `npm ci` and `npm run build` in `web_app/frontend`.
5. Unless the pipeline is skipped, validate the required API keys, chunk `data/markdown`, build the dense and lexical indexes, and recreate local Chroma storage.
6. Verify the frontend bundle, `lexical.sqlite3`, dense vector file, manifests, and non-empty Chroma collection.

The existing `-SkipVenv` and `-SkipPipeline` switches remain. No new setup modes or configuration layer will be added.

## Environment configuration

The root `.env.example` documents every supported variable with empty or safe example values. `.env` is ignored by Git. Frontend build-time configuration continues to use same-origin defaults, so no separate frontend environment file is required for the standard local flow.

## Generated state

All generated artifacts are reproducible and excluded from Git:

- `.venv/`
- `web_app/frontend/node_modules/`
- `web_app/frontend/dist/`
- `data/chunks/`
- `data/indexes/`
- `data/chroma_manifests/`
- `web_app/storage/chroma/`
- `web_app/storage/app.sqlite3`

Embedding output can change if the external provider changes the selected model implementation. The repository guarantees the same inputs and configuration, not byte-identical third-party API output forever.

## Error handling

Setup stops immediately with a clear message when Python, Node/npm, an input directory, a required credential, or an expected generated artifact is missing. Existing files containing secrets are never overwritten.

## Verification

Verification will cover:

- PowerShell syntax parsing for both setup scripts.
- Frontend type-check and production build.
- Existing Python unit tests.
- A setup-flow check that confirms the script contains and orders frontend installation/build and RAG artifact validation.
- A clean packaging audit confirming ignored secrets and generated directories are not tracked.

## User workflow

```powershell
# After cloning the repository, open PowerShell in its root directory.
Copy-Item .env.example .env
notepad .env
.\scripts\setup.ps1
.\scripts\run_webapp.ps1
```
