[CmdletBinding()]
param(
    [int]$Rows = 20000,
    [switch]$ArtifactsOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run scripts\dev-setup.ps1 first."
}

$arguments = @((Join-Path $PSScriptRoot "prepare_demo.py"), "--rows", $Rows)
if ($ArtifactsOnly) {
    $arguments += "--artifacts-only"
}
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Demo preparation failed with exit code $LASTEXITCODE."
}
