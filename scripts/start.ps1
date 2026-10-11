# PowerShell Startup Script for RDR2 Mobile Controller
param (
    [switch]$Mock = $false,
    [int]$Port = 8000,
    [string]$Pin = ""
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "      RDR2 Mobile Controller - Windows Host Launcher       " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check Python
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "[ERROR] Python is not found in PATH. Please install Python 3.11+." -ForegroundColor Red
    exit 1
}

$pyVer = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "[INFO] Detected Python version: $pyVer" -ForegroundColor Green

# 2. Check Dependencies
Write-Host "[INFO] Verifying core packages..." -ForegroundColor Yellow
python -c "import fastapi, uvicorn, websockets, pytest" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Installing required dependencies from requirements.txt..." -ForegroundColor Yellow
    pip install -r (Join-Path $PSScriptRoot "..\requirements.txt")
}

# 3. Check ViGEmBus Driver Status
Write-Host "[INFO] Checking Windows Virtual Gamepad Driver (ViGEmBus)..." -ForegroundColor Yellow
$driverStatus = python -c "from gamepad.windows_adapter import WindowsGamepadAdapter; a = WindowsGamepadAdapter(); res = a.initialize(); print('READY' if res else a.status.value)"

if ($driverStatus -eq "READY") {
    Write-Host "[SUCCESS] Virtual Xbox 360 Gamepad Driver is operational!" -ForegroundColor Green
} else {
    Write-Host "[WARNING] ViGEmBus driver not active ($driverStatus)." -ForegroundColor Yellow
    Write-Host "          To control real Windows games like RDR2, install ViGEmBus 1.22.0 from:" -ForegroundColor Yellow
    Write-Host "          https://github.com/nefarius/ViGEmBus/releases/latest" -ForegroundColor Cyan
    if (-not $Mock) {
        Write-Host "          Launching in mock/diagnostic fallback mode." -ForegroundColor Yellow
    }
}

# 4. Display Network IP Addresses
Write-Host "`n[NETWORK] Available Local IP Addresses for your Android Phone:" -ForegroundColor Cyan
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notlike "*Loopback*" -and $_.IPAddress -notlike "169.254*" } | ForEach-Object {
    Write-Host ("  -> http://{0}:{1} ({2})" -f $_.IPAddress, $Port, $_.InterfaceAlias) -ForegroundColor White
}

# 5. Check for Port Conflicts
$existingConn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
if ($existingConn) {
    $procId = $existingConn.OwningProcess
    $procName = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
    Write-Host "`n[ERROR] Port $Port is already in use by process PID $procId ($procName)." -ForegroundColor Red
    Write-Host "        Please stop the conflicting process or choose another port with -Port <number>." -ForegroundColor Yellow
    exit 1
}

# 6. Launch Server
$serverArgs = @("server.py", "--host", "0.0.0.0", "--port", "$Port")
if ($Mock) { $serverArgs += "--mock" }
if ($Pin) { $serverArgs += @("--pin", $Pin) }

Write-Host "`n[STARTING] Launching controller server... Press Ctrl+C to terminate." -ForegroundColor Green
Set-Location (Join-Path $PSScriptRoot "..")
python @serverArgs
