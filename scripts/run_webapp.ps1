param(
    [int]$Port = 8002,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Không tìm thấy môi trường ảo. Hãy chạy .\scripts\setup.ps1 trước."
}

Set-Location $Root
$args = @("-m", "uvicorn", "web_app.backend.main:app", "--host", "127.0.0.1", "--port", "$Port")
if ($Reload) {
    $args += "--reload"
}

& $Python @args
