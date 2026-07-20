param(
    [string]$InputDir = "data\markdown",
    [string]$Collection = "local_rag",
    [ValidateSet("siliconflow", "ollama")]
    [string]$EmbeddingBackend = "siliconflow",
    [string]$EmbeddingModel = "Qwen/Qwen3-Embedding-4B",
    [int]$EmbeddingDimension = 2048,
    [int]$EmbeddingBatchSize = 16,
    [int]$UpsertBatchSize = 128,
    [int]$ChunkTargetWords = 1000,
    [int]$ChunkOverlapWords = 200,
    [int]$MaxSectionWords = 1000,
    [switch]$SkipVenv,
    [switch]$SkipPipeline
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$ChunksPath = Join-Path $Root "data\chunks\$Collection.chunks.jsonl"
$StatsPath = Join-Path $Root "data\chunks\$Collection.chunks.stats.json"
$IndexDir = Join-Path $Root "data\indexes\$Collection"
$PersistPath = Join-Path $Root "web_app\storage\chroma"
$ManifestPath = Join-Path $Root "data\chroma_manifests\$Collection.json"
$EnvPath = Join-Path $Root ".env"
$EnvExamplePath = Join-Path $Root ".env.example"
$FrontendDir = Join-Path $Root "web_app\frontend"
$FrontendDist = Join-Path $FrontendDir "dist"

function Set-EnvDefault([string]$Name, [string]$Value) {
    if (Test-Path $EnvPath) {
        $pattern = "^\s*$([regex]::Escape($Name))\s*="
        if (Select-String -LiteralPath $EnvPath -Pattern $pattern -Quiet) {
            return
        }
    }
    Add-Content -LiteralPath $EnvPath -Encoding UTF8 -Value "$Name=$Value"
}

function Get-ConfiguredEnvValue([string]$Name) {
    $shellValue = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($shellValue)) {
        return $shellValue
    }

    if (-not (Test-Path $EnvPath)) {
        return $null
    }

    $pattern = "^\s*$([regex]::Escape($Name))\s*=(.*)$"
    $match = Select-String -LiteralPath $EnvPath -Pattern $pattern | Select-Object -First 1
    if (-not $match) {
        return $null
    }

    return $match.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
}

function Assert-ConfiguredEnvValue([string]$Name) {
    $value = Get-ConfiguredEnvValue $Name
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Set $Name in .env or current shell, then rerun setup.ps1."
    }
}

function Assert-ExistingFile([string]$PathValue, [string]$Label) {
    if (-not (Test-Path -LiteralPath $PathValue -PathType Leaf)) {
        throw "$Label was not created: $PathValue"
    }
    if ((Get-Item -LiteralPath $PathValue).Length -le 0) {
        throw "$Label is empty: $PathValue"
    }
}

function Assert-ExistingDirectory([string]$PathValue, [string]$Label) {
    if (-not (Test-Path -LiteralPath $PathValue -PathType Container)) {
        throw "$Label was not created: $PathValue"
    }
}

function Test-LocalChromaCollection([string]$PersistPathValue, [string]$CollectionName) {
    $env:SETUP_CHROMA_PERSIST_PATH = $PersistPathValue
    $env:SETUP_CHROMA_COLLECTION = $CollectionName
    try {
        @'
import os
from pathlib import Path

import chromadb

persist_path = Path(os.environ["SETUP_CHROMA_PERSIST_PATH"])
collection_name = os.environ["SETUP_CHROMA_COLLECTION"]
if not persist_path.exists():
    raise SystemExit(f"Chroma persist directory was not created: {persist_path}")

client = chromadb.PersistentClient(path=str(persist_path))
collection = client.get_collection(collection_name)
count = int(collection.count())
if count <= 0:
    raise SystemExit(f"Chroma collection '{collection_name}' is empty.")

print(f"Local Chroma collection '{collection_name}' is ready with {count} records.")
'@ | & $Python
        if ($LASTEXITCODE -ne 0) {
            throw "Local Chroma verification failed."
        }
    } finally {
        Remove-Item Env:\SETUP_CHROMA_PERSIST_PATH -ErrorAction SilentlyContinue
        Remove-Item Env:\SETUP_CHROMA_COLLECTION -ErrorAction SilentlyContinue
    }
}

Set-Location $Root
New-Item -ItemType Directory -Force -Path "data\chunks", "data\indexes", "data\chroma_manifests", "web_app\storage" | Out-Null

if (-not $SkipVenv) {
    if (-not (Test-Path $Python)) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            py -3 -m venv (Join-Path $Root ".venv")
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            python -m venv (Join-Path $Root ".venv")
        } else {
            throw "Python 3 was not found. Install Python 3, then rerun setup.ps1."
        }
    }
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r (Join-Path $Root "requirements.txt")
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js LTS, then rerun setup.ps1."
}
Assert-ExistingFile $EnvExamplePath "Environment template"

if (-not (Test-Path $EnvPath)) {
    Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
    Write-Host "Created .env from .env.example. Fill in credentials, then rerun setup.ps1."
}

Set-EnvDefault "SILICONFLOW_API_KEY" ""
Set-EnvDefault "GROQ_API_KEY" ""

Push-Location $FrontendDir
try {
    npm ci
    if ($LASTEXITCODE -ne 0) {
        throw "npm ci failed."
    }
    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend build failed."
    }
} finally {
    Pop-Location
}
Assert-ExistingFile (Join-Path $FrontendDist "index.html") "Frontend bundle"

if (-not $SkipPipeline) {
    Assert-ConfiguredEnvValue "GROQ_API_KEY"
    if ($EmbeddingBackend -eq "siliconflow") {
        Assert-ConfiguredEnvValue "SILICONFLOW_API_KEY"
    }
    Assert-ExistingDirectory (Join-Path $Root $InputDir) "Markdown input directory"

    & $Python -m scripts.RAG.chunking `
        --input-dir (Join-Path $Root $InputDir) `
        --output $ChunksPath `
        --stats-output $StatsPath `
        --chunk-target-words $ChunkTargetWords `
        --chunk-overlap-words $ChunkOverlapWords `
        --max-section-words $MaxSectionWords

    & $Python -m scripts.RAG.indexing `
        --chunks $ChunksPath `
        --index-dir $IndexDir `
        --embedding-backend $EmbeddingBackend `
        --embedding-model-name $EmbeddingModel `
        --embedding-dimension $EmbeddingDimension `
        --embedding-batch-size $EmbeddingBatchSize

    & $Python -m scripts.RAG.vectordatabase build `
        --mode local `
        --collection $Collection `
        --chunks (Join-Path $IndexDir "chunks.jsonl") `
        --vectors (Join-Path $IndexDir "vectors.npy") `
        --source-manifest (Join-Path $IndexDir "manifest.json") `
        --persist-path $PersistPath `
        --embedding-backend $EmbeddingBackend `
        --embedding-model-name $EmbeddingModel `
        --embedding-dimension $EmbeddingDimension `
        --embedding-batch-size $EmbeddingBatchSize `
        --upsert-batch-size $UpsertBatchSize `
        --recreate `
        --manifest-output $ManifestPath

    Assert-ExistingFile $ChunksPath "Chunk file"
    Assert-ExistingFile (Join-Path $IndexDir "chunks.jsonl") "Index chunk store"
    Assert-ExistingFile (Join-Path $IndexDir "vectors.npy") "Dense vector file"
    Assert-ExistingFile (Join-Path $IndexDir "lexical.sqlite3") "Lexical index"
    Assert-ExistingFile (Join-Path $IndexDir "manifest.json") "Index manifest"
    Assert-ExistingDirectory $PersistPath "Chroma persist directory"
    Assert-ExistingFile $ManifestPath "Chroma manifest"
    Test-LocalChromaCollection $PersistPath $Collection
}

Write-Host ""
Write-Host "Setup finished. Start the app with:"
Write-Host "  .\scripts\run_webapp.ps1"
