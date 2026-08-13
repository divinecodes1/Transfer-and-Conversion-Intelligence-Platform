# =============================================================================
# Transfer & Conversion Intelligence Platform :: one-command demonstration.
#
#   .\scripts\demo.ps1
#
# Brings the whole platform up, seeded, in a browser. Ctrl+C stops everything.
#
# Written because showing this used to take six commands across three terminals
# (pg-up, pg-build, sso-up, api, agent, web) plus a Keycloak cold start and a
# manual entitlement grant. Nobody senior sits through that, and a demo that is
# hard to start is a demo that does not happen.
#
# Two deliberate simplifications for a room:
#
#   * TRANSFEROPS_AUTH=demo. No Keycloak, no sign-in, no 40-second JVM start.
#     The console's identity switcher then shows RBAC *better* than logging in
#     would -- switch from admin to manager.auto and the same screen drops from
#     260 projects to one portfolio, in three seconds, without leaving the page.
#
#   * Only PostgreSQL starts. Mailpit, Qdrant, Prometheus and Grafana are not
#     needed to tell the story and each one is start-up time.
#
# Demo mode accepts an unauthenticated identity header, so this binds to
# localhost only and must never be used for a deployed URL. The AWS deployment
# runs auth_mode = "enforce"; scripts/deploy-aws-student.sh is that path.
# =============================================================================
[CmdletBinding()]
param(
    [switch]$SkipSeed,   # reuse the warehouse from a previous run
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Info($m) { Write-Host "    $m" -ForegroundColor Gray }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

# The interpreter that has the dependencies. Prefer a local virtualenv over
# whatever `python` resolves to on PATH -- on Windows that is frequently the
# Store stub, which has none of them.
$python = Get-ChildItem -Path $root -Directory -Filter '*intel*platform*' -ErrorAction SilentlyContinue |
          ForEach-Object { Join-Path $_.FullName 'Scripts\python.exe' } |
          Where-Object { Test-Path $_ } |
          Select-Object -First 1
if (-not $python) { $python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python) { Die "No Python found. Create a virtualenv and pip install -r requirements.txt" }

$started = @()   # child processes to clean up on exit

try {
    Step "Checking prerequisites"
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { Die "Docker Desktop is not running." }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Die "npm is not installed." }
    Info "docker, npm, python"

    Step "Starting PostgreSQL"
    docker compose up -d postgres | Out-Null

    # Compose reports the container as running before the database accepts
    # connections. Poll the health check rather than sleeping a fixed guess.
    Info "waiting for the database to accept connections"
    $ready = $false
    foreach ($attempt in 1..60) {
        $state = docker inspect --format '{{.State.Health.Status}}' `
                 (docker compose ps -q postgres) 2>$null
        if ($state -eq 'healthy') { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { Die "PostgreSQL did not become healthy." }
    Info "ready"

    $dsn = 'postgresql://app:dev@localhost:5432/transferops'
    $env:TRANSFEROPS_DSN = $dsn
    $env:TRANSFEROPS_API_DSN = 'postgresql://transferops_reader:reader@localhost:5432/transferops'
    $env:TRANSFEROPS_AUDIT_DSN = 'postgresql://transferops_auditor:auditor@localhost:5432/transferops'
    $env:TRANSFEROPS_AI_DSN = 'postgresql://transferops_ai:ai@localhost:5432/transferops'
    $env:TRANSFEROPS_READER_PASSWORD = 'reader'
    $env:TRANSFEROPS_AUDITOR_PASSWORD = 'auditor'
    $env:TRANSFEROPS_AI_PASSWORD = 'ai'
    $env:TRANSFEROPS_AUTH = 'demo'
    # No key required. Every AI surface still answers; the narratives are
    # composed from the governed figures rather than generated.
    $env:TRANSFEROPS_AI_PROVIDER = 'mock'

    if (-not $SkipSeed) {
        Step "Building the warehouse"
        & $python etl/generate_data.py
        if ($LASTEXITCODE -ne 0) { Die "Data generation failed." }
        & $python etl/run.py --engine postgres --dsn $dsn
        if ($LASTEXITCODE -ne 0) { Die "Warehouse load failed -- a data-quality gate did not pass." }
    } else {
        Info "reusing the existing warehouse (-SkipSeed)"
    }

    Step "Starting the services"
    $started += Start-Process -PassThru -WindowStyle Hidden -FilePath $python `
        -ArgumentList '-m','uvicorn','api.main:app','--host','127.0.0.1','--port','8000'
    Info "analytics API   http://127.0.0.1:8000/docs"

    $started += Start-Process -PassThru -WindowStyle Hidden -FilePath $python `
        -ArgumentList '-m','uvicorn','agent.app:app','--host','127.0.0.1','--port','8100'
    Info "assistant       http://127.0.0.1:8100"

    if (-not (Test-Path 'web/node_modules')) {
        Step "Installing console dependencies (first run only)"
        Push-Location web; npm ci; Pop-Location
    }

    Step "Opening the console"
    # Vite runs in the FOREGROUND so Ctrl+C ends the whole demo and the finally
    # block below can stop the services it started.
    $env:VITE_TRANSFEROPS_AUTH = 'demo'
    $env:VITE_TRANSFEROPS_API = 'http://127.0.0.1:8000'
    $env:VITE_TRANSFEROPS_AGENT = 'http://127.0.0.1:8100'

    if (-not $NoBrowser) {
        Start-Job -ScriptBlock {
            Start-Sleep -Seconds 4; Start-Process 'http://localhost:5173'
        } | Out-Null
    }

    Write-Host @"

  ------------------------------------------------------------------
  Console        http://localhost:5173
  API docs       http://127.0.0.1:8000/docs

  Five minutes, in order:

    1  Overview        on-time rate, cycle time, the AI brief
    2  Readiness       worst first; qualification is the constraint
    3  Projects        open T-002 -> 77.15% readiness, limited by qualification
    4  Similar         what happened to comparable completed transfers
    5  Identity menu   switch admin -> manager.auto
                       the same screen drops to one portfolio, enforced
                       by row-level security in the database, not the UI

  Every panel footer states the metric definition, the filters applied
  and the data vintage that produced the number.

  Ctrl+C to stop everything.
  ------------------------------------------------------------------

"@ -ForegroundColor White

    Push-Location web
    npm run dev
    Pop-Location
}
finally {
    Step "Stopping"
    foreach ($p in $started) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    Info "services stopped. PostgreSQL is still running:  docker compose down"
}
