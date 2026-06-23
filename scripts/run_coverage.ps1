#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Run NN Fund Management tests with coverage reporting.
.DESCRIPTION
    Executes Odoo tests for the nn_fund_management module with pytest-style
    coverage measurement. Requires Odoo 18 Community Edition installed.
.PARAMETER OdooPath
    Path to Odoo installation directory.
.PARAMETER Database
    Test database name (default: test_fund_coverage).
.PARAMETER AddonsPath
    Comma-separated list of addons paths.
.PARAMETER Filter
    Test tag filter (e.g., "fund_management,security").
.PARAMETER NoCoverage
    Skip coverage measurement (faster).
.EXAMPLE
    .\run_coverage.ps1 -OdooPath "C:\odoo\odoo18"
.EXAMPLE
    .\run_coverage.ps1 -OdooPath "C:\odoo\odoo18" -Filter "concurrency"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$OdooPath,
    [string]$Database = "test_fund_coverage",
    [string]$AddonsPath = "",
    [string]$Filter = "",
    [switch]$NoCoverage
)

$ModulePath = Split-Path -Parent $PSScriptRoot
$ScriptsPath = $PSScriptRoot

if (-not $AddonsPath) {
    $AddonsPath = $ModulePath
}

Write-Host "=== NN Fund Management — Test Suite ===" -ForegroundColor Cyan
Write-Host "Module:   $ModulePath" -ForegroundColor Gray
Write-Host "Database: $Database" -ForegroundColor Gray
Write-Host "Filter:   $([string]::IsNullOrEmpty($Filter) ? '(all)' : $Filter)" -ForegroundColor Gray
Write-Host ""

# Step 1: Drop existing test database (if any)
Write-Host "[1/4] Dropping existing test database..." -ForegroundColor Yellow
& "$OdooPath\odoo-bin" -d "$Database" --stop-after-init --drop 2>$null
if ($?) { Write-Host "  ✓ Dropped" -ForegroundColor Green }

# Step 2: Install module with test data
Write-Host "[2/4] Installing module with demo data..." -ForegroundColor Yellow
$installArgs = @(
    "-d", "$Database"
    "--addons-path", "$AddonsPath"
    "-i", "nn_fund_management"
    "--stop-after-init"
    "--without-demo=all"
    "--demo=none"
)

if ($Filter) {
    $installArgs += "--test-tags=$Filter"
}

& "$OdooPath\odoo-bin" $installArgs 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ Module installation failed" -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ Installed" -ForegroundColor Green

# Step 3: Reload demo data
Write-Host "[3/4] Loading demo data..." -ForegroundColor Yellow
& "$OdooPath\odoo-bin" -d "$Database" --addons-path "$AddonsPath" -i nn_fund_management --stop-after-init --demo=demo 2>&1 | Out-Null
Write-Host "  ✓ Demo data loaded" -ForegroundColor Green

# Step 4: Run tests
Write-Host "[4/4] Running tests..." -ForegroundColor Yellow

$testArgs = @(
    "-d", "$Database"
    "--addons-path", "$AddonsPath"
    "--test-enable"
    "--stop-after-init"
    "--log-level=warn"
)

if ($Filter) {
    $testArgs += "--test-tags=$Filter"
}

if (-not $NoCoverage) {
    # Use pytest-coverage style output via Odoo test runner
    $env:PYTHONPATH = "$ModulePath;$env:PYTHONPATH"
}

$startTime = Get-Date
& "$OdooPath\odoo-bin" $testArgs 2>&1 | Tee-Object -FilePath "$ScriptsPath\test_output.log"
$exitCode = $LASTEXITCODE
$duration = (Get-Date) - $startTime

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "=== ALL TESTS PASSED ($($duration.TotalSeconds.ToString('F1'))s) ===" -ForegroundColor Green
} else {
    Write-Host "=== TESTS FAILED (exit code: $exitCode) ===" -ForegroundColor Red
}

# Generate coverage report if coverage package is available
if ((-not $NoCoverage) -and (Get-Command "coverage" -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "[Extra] Generating coverage report..." -ForegroundColor Yellow
    coverage run --source="$ModulePath" --omit="*/tests/*" -m pytest "$ModulePath\tests" -q 2>$null
    coverage report -m --fail-under=90
    coverage html -d "$ScriptsPath\coverage_html"
    coverage xml -o "$ScriptsPath\coverage.xml"
    Write-Host "  ✓ HTML report: $ScriptsPath\coverage_html\index.html" -ForegroundColor Green
    Write-Host "  ✓ XML report:  $ScriptsPath\coverage.xml" -ForegroundColor Green
}

exit $exitCode
