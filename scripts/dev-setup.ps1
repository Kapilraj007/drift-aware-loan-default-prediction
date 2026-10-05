[CmdletBinding()]
param(
    [int]$DemoRows = 20000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Checked {
    param([string]$Label, [scriptblock]$Command)
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    throw "Created .env from .env.example. Add the three Neon URLs and a 32+ character JWT secret, then rerun this command."
}
if (-not (Test-Path -LiteralPath "frontend\.env.local")) {
    Copy-Item -LiteralPath "frontend\.env.example" -Destination "frontend\.env.local"
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Invoke-Checked "Creating Python 3.12 virtual environment" { py -3.12 -m venv .venv }
}
$python = Join-Path $root ".venv\Scripts\python.exe"

Invoke-Checked "Installing Python development dependencies" {
    & $python -m pip install -r requirements-dev.txt
}
Invoke-Checked "Installing this project in editable mode" {
    & $python -m pip install --no-deps -e .
}
Invoke-Checked "Installing frontend dependencies" {
    Push-Location frontend
    try { npm ci } finally { Pop-Location }
}
Invoke-Checked "Applying Alembic migrations through the direct Neon URL" {
    & $python -m alembic upgrade head
}
Invoke-Checked "Checking direct and pooled Neon connectivity" {
    & $python scripts/check_db.py --pooled
}
Invoke-Checked "Preparing and seeding the synthetic showcase" {
    & $python scripts/prepare_demo.py --rows $DemoRows
}
Invoke-Checked "Exporting OpenAPI and generating frontend types" {
    & $python scripts/export_openapi.py
    if ($LASTEXITCODE -eq 0) {
        Push-Location frontend
        try { npm run generate:openapi } finally { Pop-Location }
    }
}
Invoke-Checked "Running Python lint" { & $python -m ruff check . }
Invoke-Checked "Running frontend checks" {
    Push-Location frontend
    try {
        npm run lint
        if ($LASTEXITCODE -eq 0) { npm run test -- --run }
        if ($LASTEXITCODE -eq 0) { npm run build }
    } finally { Pop-Location }
}

Write-Host "Setup complete. Start the showcase with scripts\dev-start.ps1." -ForegroundColor Green
