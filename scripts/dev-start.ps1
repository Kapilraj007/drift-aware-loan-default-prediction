[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run scripts\dev-setup.ps1 first."
}

& $python scripts/check_db.py --pooled
if ($LASTEXITCODE -ne 0) {
    throw "Database readiness failed. Fix the reported issue before starting."
}

$logDirectory = Join-Path $root ".tmp\dev-logs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$apiOut = Join-Path $logDirectory "api.stdout.log"
$apiErr = Join-Path $logDirectory "api.stderr.log"
$webOut = Join-Path $logDirectory "frontend.stdout.log"
$webErr = Join-Path $logDirectory "frontend.stderr.log"

$api = $null
$web = $null
try {
    $api = Start-Process -FilePath $python -ArgumentList @(
        "-m", "uvicorn", "backend.app.main:create_app", "--factory",
        "--host", "127.0.0.1", "--port", "8000", "--workers", "1"
    ) -WorkingDirectory $root -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr

    $web = Start-Process -FilePath "npm.cmd" -ArgumentList @(
        "run", "dev", "--", "--host", "127.0.0.1"
    ) -WorkingDirectory (Join-Path $root "frontend") -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput $webOut -RedirectStandardError $webErr

    Write-Host "API:      http://127.0.0.1:8000" -ForegroundColor Green
    Write-Host "Frontend: http://127.0.0.1:5173" -ForegroundColor Green
    Write-Host "Logs:     $logDirectory"
    Write-Host "Press Ctrl+C to stop both processes."

    while (-not $api.HasExited -and -not $web.HasExited) {
        Start-Sleep -Seconds 1
    }
    if ($api.HasExited -and $api.ExitCode -ne 0) {
        throw "API exited with code $($api.ExitCode). See $apiErr."
    }
    if ($web.HasExited -and $web.ExitCode -ne 0) {
        throw "Frontend exited with code $($web.ExitCode). See $webErr."
    }
} finally {
    foreach ($process in @($api, $web)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        }
    }
}
