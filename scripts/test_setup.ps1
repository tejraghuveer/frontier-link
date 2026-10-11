# PowerShell Test & Verification Setup Script
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "      RDR2 Mobile Controller - Environment & Test Runner   " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Run Pytest Suite
Write-Host "`n[1/3] Executing Automated Pytest Suite..." -ForegroundColor Yellow
Set-Location (Join-Path $PSScriptRoot "..")
python -m pytest tests/ -v

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[PASS] All automated unit and integration tests passed!" -ForegroundColor Green
} else {
    Write-Host "`n[FAIL] Some automated tests failed. Review log above." -ForegroundColor Red
}

# 2. Check Node.js for Frontend Syntax
Write-Host "`n[2/3] Checking Frontend JavaScript Syntax..." -ForegroundColor Yellow
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    node --check static\app.js
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[PASS] static/app.js passed Node.js syntax verification." -ForegroundColor Green
    } else {
        Write-Host "[FAIL] Syntax error in static/app.js." -ForegroundColor Red
    }
} else {
    Write-Host "[BLOCKED] Node.js not installed on PATH; syntax check skipped." -ForegroundColor Yellow
}

# 3. Check Windows Firewall
Write-Host "`n[3/3] Checking Windows Firewall on Port 8000..." -ForegroundColor Yellow
$rule = Get-NetFirewallRule -DisplayName "*Controller*" -ErrorAction SilentlyContinue
if ($rule) {
    Write-Host "[INFO] Firewall rule exists for Controller." -ForegroundColor Green
} else {
    Write-Host "[NOTICE] To allow your Android phone to connect over Wi-Fi, ensure Windows Firewall permits port 8000 on Private Networks." -ForegroundColor Yellow
    Write-Host "Command to open port 8000 (Admin PowerShell):" -ForegroundColor Cyan
    Write-Host "  New-NetFirewallRule -DisplayName 'RDR2 Controller Port 8000' -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow -Profile Private" -ForegroundColor White
}

Write-Host "`n[DONE] Environment verification complete." -ForegroundColor Cyan
