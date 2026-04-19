#!/usr/bin/env pwsh
# Local CI runner — replaces GitHub Actions CI while Actions is disabled.
#
# Runs the same checks the deleted .github/workflows/ci.yml used to run,
# plus a few that weren't in CI but should be (frontend build).
#
# Usage:
#     # From repo root, in PowerShell:
#     .\scripts\run_ci_locally.ps1
#
#     # Or skip expensive checks:
#     .\scripts\run_ci_locally.ps1 -SkipFrontend
#     .\scripts\run_ci_locally.ps1 -SkipSlow
#
#     # As a pre-push hook (optional):
#     # Copy to .git\hooks\pre-push.ps1 and wrap in a .cmd shim.
#
# Exit codes:
#   0 — all checks passed
#   1 — at least one check failed (see summary)
#   2 — environment issue (missing deps, wrong cwd)
#
# Why this exists:
#   GitHub Actions was disabled to conserve spend until walk-forward
#   validation proves live edge (per April 2026 pivot). Running the
#   same checks locally gives the same safety net. Once ARCIS is
#   proven profitable, Actions can be re-enabled and this script
#   becomes the pre-push hook instead of the primary CI.

param(
    [switch]$SkipFrontend,
    [switch]$SkipSlow,
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$ScriptStart = Get-Date

# ── Environment checks ──────────────────────────────────────────────────

if (-not (Test-Path "src") -or -not (Test-Path "tests") -or -not (Test-Path "requirements.txt")) {
    Write-Host "ERROR: must run from repo root (expected src/, tests/, requirements.txt)" -ForegroundColor Red
    exit 2
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "ERROR: python not found in PATH" -ForegroundColor Red
    exit 2
}

# Track each check's result
$checks = @()

function Add-Check {
    param($Name, $Passed, $DurationSec, $Detail = "")
    $script:checks += [PSCustomObject]@{
        Name = $Name
        Passed = $Passed
        DurationSec = [math]::Round($DurationSec, 1)
        Detail = $Detail
    }
}

function Run-Check {
    param(
        [string]$Name,
        [scriptblock]$Command,
        [switch]$AllowFail
    )
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    $start = Get-Date
    & $Command
    $exitCode = $LASTEXITCODE
    $duration = (Get-Date) - $start
    $passed = ($exitCode -eq 0)

    if ($passed) {
        Write-Host "  ✓ passed in $([math]::Round($duration.TotalSeconds, 1))s" -ForegroundColor Green
    } else {
        Write-Host "  ✗ FAILED (exit $exitCode) in $([math]::Round($duration.TotalSeconds, 1))s" -ForegroundColor Red
    }
    Add-Check -Name $Name -Passed $passed -DurationSec $duration.TotalSeconds
    return $passed
}

# ── 1. Dependency check ─────────────────────────────────────────────────

Write-Host "`n=== Dependency sanity ===" -ForegroundColor Cyan
$depStart = Get-Date
$pytestOk = $false
$asyncioOk = $false
try {
    python -c "import pytest" 2>&1 | Out-Null
    $pytestOk = ($LASTEXITCODE -eq 0)
    python -c "import pytest_asyncio" 2>&1 | Out-Null
    $asyncioOk = ($LASTEXITCODE -eq 0)
} catch {}

if (-not $pytestOk) {
    Write-Host "  ✗ pytest not installed. Run: pip install pytest pytest-timeout pytest-asyncio" -ForegroundColor Red
    Add-Check -Name "deps" -Passed $false -DurationSec ((Get-Date) - $depStart).TotalSeconds -Detail "pytest missing"
    exit 2
}
if (-not $asyncioOk) {
    Write-Host "  ✗ pytest-asyncio not installed (needed by test_walkforward_routes.py)." -ForegroundColor Yellow
    Write-Host "    Run: pip install pytest-asyncio" -ForegroundColor Yellow
    Add-Check -Name "deps" -Passed $false -DurationSec ((Get-Date) - $depStart).TotalSeconds -Detail "pytest-asyncio missing"
    # Non-fatal — continue but this will cause walkforward route tests to fail
} else {
    Write-Host "  ✓ pytest + pytest-asyncio installed" -ForegroundColor Green
    Add-Check -Name "deps" -Passed $true -DurationSec ((Get-Date) - $depStart).TotalSeconds
}

# ── 2. Repo structure guardrails ────────────────────────────────────────

Run-Check -Name "repo structure" -Command {
    python -m pytest tests/test_repo_structure.py -v --tb=short
} | Out-Null

# ── 3. Full test suite ──────────────────────────────────────────────────
# Uses same -x --timeout=60 as the old CI

$pytestFlags = @("-x", "-q", "--timeout=60")
if ($SkipSlow) {
    # Skip known-slow tests by node id
    $pytestFlags += "--ignore=tests/platform/test_lazy_prices_e2e.py"
}

Run-Check -Name "full pytest" -Command {
    python -m pytest tests/ @pytestFlags
} | Out-Null

# ── 4. Test count floor ─────────────────────────────────────────────────
# Old CI enforced ≥1339. With v0.26.0 additions we should be well above.
# Floor bumped to 1500 to reflect current baseline while leaving headroom.

$countStart = Get-Date
Write-Host "`n=== Test count floor ===" -ForegroundColor Cyan
# Count "def test_" occurrences across tests/ (matches old CI grep)
$testCount = (Get-ChildItem -Path tests -Filter "test_*.py" -Recurse |
              ForEach-Object { Select-String -Path $_.FullName -Pattern "def test_" } |
              Measure-Object).Count
$floor = 1500
$countPassed = ($testCount -ge $floor)
if ($countPassed) {
    Write-Host "  ✓ $testCount tests (floor: $floor)" -ForegroundColor Green
} else {
    Write-Host "  ✗ $testCount tests — below floor of $floor" -ForegroundColor Red
}
Add-Check -Name "test count" -Passed $countPassed -DurationSec ((Get-Date) - $countStart).TotalSeconds -Detail "$testCount tests"

# ── 5. Frontend build ───────────────────────────────────────────────────
# Old CI ran this as a separate job. Optional to skip for speed.

if (-not $SkipFrontend) {
    if (Test-Path "frontend/package.json") {
        Run-Check -Name "frontend build" -Command {
            Push-Location frontend
            try {
                npm run build 2>&1
            } finally {
                Pop-Location
            }
        } | Out-Null
    } else {
        Write-Host "`n=== frontend build (skipped — no frontend/package.json) ===" -ForegroundColor DarkGray
    }
}

# ── 6. Doc drift check ──────────────────────────────────────────────────
# Your memory #22 rule: scripts/verify_docs.py checks drift in MASTER.md

if (Test-Path "scripts/verify_docs.py") {
    Run-Check -Name "doc drift" -Command {
        python scripts/verify_docs.py
    } | Out-Null
}

# ── Summary ─────────────────────────────────────────────────────────────

$totalDuration = (Get-Date) - $ScriptStart
Write-Host "`n"
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "LOCAL CI SUMMARY" -ForegroundColor Cyan
Write-Host ("=" * 60) -ForegroundColor Cyan

$passed = ($checks | Where-Object { $_.Passed }).Count
$failed = ($checks | Where-Object { -not $_.Passed }).Count

foreach ($check in $checks) {
    $icon = if ($check.Passed) { "✓" } else { "✗" }
    $color = if ($check.Passed) { "Green" } else { "Red" }
    $detail = if ($check.Detail) { " ($($check.Detail))" } else { "" }
    Write-Host ("  {0} {1,-24} {2,6:F1}s{3}" -f $icon, $check.Name, $check.DurationSec, $detail) -ForegroundColor $color
}

Write-Host ""
Write-Host ("Total: {0} passed, {1} failed in {2:F1}s" -f $passed, $failed, $totalDuration.TotalSeconds)

if ($failed -gt 0) {
    Write-Host "`nLocal CI FAILED — do not push." -ForegroundColor Red
    exit 1
} else {
    Write-Host "`nLocal CI passed — safe to push." -ForegroundColor Green
    exit 0
}
