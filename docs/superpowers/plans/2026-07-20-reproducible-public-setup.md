# Reproducible Public Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a public clone install Python and frontend dependencies, build the frontend and all RAG indexes, and verify the result through one `scripts/setup.ps1` command.

**Architecture:** Keep `scripts/setup.ps1` as the only setup entry point. Git stores source inputs and lock files; setup recreates every generated artifact locally and fails immediately when prerequisites, credentials, or outputs are missing.

**Tech Stack:** PowerShell, Python/venv/pip, Node/npm/Vite, SQLite lexical index, NumPy dense index, ChromaDB.

## Global Constraints

- The repository is public and may include `data/markdown` and `data/golden dataset`.
- Never commit `.env`, credentials, user history, dependency directories, logs, caches, or generated indexes.
- Preserve `-SkipVenv` and `-SkipPipeline`; add no new setup modes.
- Do not overwrite an existing `.env`.
- Same inputs and configuration are reproducible; third-party embedding output is not guaranteed byte-identical forever.

---

### Task 1: Public repository boundary and environment template

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `tests/test_repository_contract.py`

**Interfaces:**
- Consumes: current root `.env` variable names.
- Produces: safe public-file boundary and the environment template consumed by setup.

- [ ] **Step 1: Write the failing repository contract test**

```python
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_public_repository_files_exist_and_cover_private_state(self):
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        for name in (
            "SILICONFLOW_API_KEY",
            "GROQ_API_KEY",
            "CLERK_PUBLISHABLE_KEY",
            "CLERK_JWKS_URL",
            "CLERK_ALLOWED_ORIGINS",
        ):
            self.assertIn(f"{name}=", env_example)

        for ignored in (
            ".env",
            ".venv/",
            "node_modules/",
            "__pycache__/",
            "*.log",
            "web_app/storage/app.sqlite3",
            "web_app/storage/chroma/",
            "data/chunks/",
            "data/indexes/",
            "data/chroma_manifests/",
            "web_app/frontend/dist/",
        ):
            self.assertIn(ignored, gitignore)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.\.venv\Scripts\python -m unittest tests.test_repository_contract -v`

Expected: ERROR because root `.env.example` or `.gitignore` does not exist.

- [ ] **Step 3: Add the minimal public repository files**

Create `.env.example`:

```dotenv
SILICONFLOW_API_KEY=
GROQ_API_KEY=
CLERK_PUBLISHABLE_KEY=
CLERK_JWKS_URL=
CLERK_ALLOWED_ORIGINS=http://127.0.0.1:8002,http://localhost:8002
```

Create `.gitignore`:

```gitignore
.env
.venv/
node_modules/
__pycache__/
*.py[cod]
*.log
code.zip
web_app/frontend/dist/
web_app/storage/app.sqlite3
web_app/storage/chroma/
data/chunks/
data/indexes/
data/chroma_manifests/
```

- [ ] **Step 4: Run the test and verify GREEN**

Run: `.\.venv\Scripts\python -m unittest tests.test_repository_contract -v`

Expected: one test passes.

- [ ] **Step 5: Initialize Git and commit the boundary**

```powershell
git init
git add .gitignore .env.example tests/test_repository_contract.py
git commit -m "chore: define public repository boundary"
```

Expected: `.env`, generated artifacts, caches, dependencies, and logs are absent from the commit.

### Task 2: One-command frontend and RAG setup

**Files:**
- Modify: `scripts/setup.ps1`
- Modify: `tests/test_repository_contract.py`

**Interfaces:**
- Consumes: `.env.example`, `requirements.txt`, `web_app/frontend/package-lock.json`, and `data/markdown`.
- Produces: `web_app/frontend/dist/index.html`, dense files, `lexical.sqlite3`, manifests, and a non-empty local Chroma collection.

- [ ] **Step 1: Add a failing setup-flow contract test**

Add to `RepositoryContractTests`:

```python
    def test_setup_builds_frontend_and_verifies_lexical_index(self):
        setup = (ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8")
        npm_ci = setup.index("npm ci")
        npm_build = setup.index("npm run build")
        rag_index = setup.index("-m scripts.RAG.indexing")

        self.assertLess(npm_ci, npm_build)
        self.assertLess(npm_build, rag_index)
        self.assertIn('Join-Path $FrontendDist "index.html"', setup)
        self.assertIn('Join-Path $IndexDir "lexical.sqlite3"', setup)
        self.assertIn('Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath', setup)
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.\.venv\Scripts\python -m unittest tests.test_repository_contract.RepositoryContractTests.test_setup_builds_frontend_and_verifies_lexical_index -v`

Expected: FAIL because `setup.ps1` does not run `npm ci`.

- [ ] **Step 3: Implement the minimal setup additions**

Add paths beside the existing root paths:

```powershell
$EnvExamplePath = Join-Path $Root ".env.example"
$FrontendDir = Join-Path $Root "web_app\frontend"
$FrontendDist = Join-Path $FrontendDir "dist"
```

Before environment creation, validate Node/npm and the template:

```powershell
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js LTS, then rerun setup.ps1."
}
Assert-ExistingFile $EnvExamplePath "Environment template"
```

Replace creation of an empty `.env` with:

```powershell
if (-not (Test-Path $EnvPath)) {
    Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
    Write-Host "Created .env from .env.example. Fill in credentials, then rerun setup.ps1."
}
```

After Python dependency installation and before `if (-not $SkipPipeline)`, build the frontend:

```powershell
Push-Location $FrontendDir
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
} finally {
    Pop-Location
}
Assert-ExistingFile (Join-Path $FrontendDist "index.html") "Frontend bundle"
```

After `scripts.RAG.indexing`, verify both generated indexes:

```powershell
Assert-ExistingFile (Join-Path $IndexDir "vectors.npy") "Dense vector file"
Assert-ExistingFile (Join-Path $IndexDir "lexical.sqlite3") "Lexical index"
```

- [ ] **Step 4: Verify PowerShell parsing and GREEN test**

Run:

```powershell
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path scripts\setup.ps1), [ref]$null, [ref]$errors) | Out-Null
if ($errors.Count) { $errors | Format-List; exit 1 }
.\.venv\Scripts\python -m unittest tests.test_repository_contract -v
```

Expected: PowerShell parser exits 0 and both repository contract tests pass.

- [ ] **Step 5: Commit the setup flow**

```powershell
git add scripts/setup.ps1 tests/test_repository_contract.py
git commit -m "feat: build frontend and RAG artifacts during setup"
```

### Task 3: Clone-to-run documentation and full verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the setup behavior from Task 2.
- Produces: the exact public user workflow and prerequisite documentation.

- [ ] **Step 1: Update README with the exact workflow**

Document these prerequisites and commands near the beginning of `README.md`:

````markdown
## Cài đặt từ Git

Yêu cầu: Windows PowerShell, Python 3, Node.js LTS và npm.

Sau khi clone repository, mở PowerShell tại thư mục gốc rồi chạy:

```powershell
Copy-Item .env.example .env
notepad .env
.\scripts\setup.ps1
.\scripts\run_webapp.ps1
```

`setup.ps1` cài Python package, chạy `npm ci`, build frontend, chunk tài liệu, tạo dense index và `lexical.sqlite3`, rồi đồng bộ Chroma local. Không chạy với `-SkipPipeline` trong lần cài đầy đủ đầu tiên.
````

- [ ] **Step 2: Run all local checks**

Run:

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
Push-Location web_app\frontend
npm run lint
npm run build
Pop-Location
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path scripts\setup.ps1), [ref]$null, [ref]$errors) | Out-Null
if ($errors.Count) { $errors | Format-List; exit 1 }
```

Expected: all Python tests pass, TypeScript exits 0, Vite build exits 0, and PowerShell reports no parse errors.

- [ ] **Step 3: Audit the public staging set**

Run:

```powershell
git add -A
git status --short --ignored
git check-ignore .env .venv web_app/frontend/node_modules web_app/frontend/dist data/indexes web_app/storage/app.sqlite3
git diff --cached --name-only
```

Expected: every sensitive/generated path is ignored, and the staged list contains source, public data, lock files, tests, and documentation only.

- [ ] **Step 4: Commit documentation and remaining public source**

```powershell
git commit -m "docs: document reproducible public setup"
```

- [ ] **Step 5: Perform the real setup before publishing**

Run from the repository root with valid `.env` credentials:

```powershell
.\scripts\setup.ps1
Test-Path web_app\frontend\dist\index.html
Test-Path data\indexes\local_rag\vectors.npy
Test-Path data\indexes\local_rag\lexical.sqlite3
Test-Path data\chroma_manifests\local_rag.json
```

Expected: setup exits 0 and all four `Test-Path` commands return `True`.
