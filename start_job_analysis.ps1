$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Frontend = Join-Path $Root "frontend"
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

function Test-PortListening {
    param([int]$Port)

    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $connected = $async.AsyncWaitHandle.WaitOne(300)
        if ($connected) {
            $client.EndConnect($async)
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python was not found in PATH." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] npm was not found in PATH." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path (Join-Path $Frontend "package.json"))) {
    Write-Host "[ERROR] frontend\package.json was not found." -ForegroundColor Red
    Write-Host "Project root: $Root"
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating Python virtual environment at .venv..."
    Push-Location $Root
    python -m venv .venv
    $venvExit = $LASTEXITCODE
    Pop-Location
    if ($venvExit -ne 0 -or -not (Test-Path $VenvPython)) {
        Write-Host "[ERROR] Failed to create Python virtual environment." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

Write-Host "Checking backend dependencies..."
$backendDepsOk = $true
try {
    & $VenvPython -c "import fastapi, uvicorn, httpx, websocket, bs4, lxml, openai, anthropic, dotenv" 2>$null
    if ($LASTEXITCODE -ne 0) {
        $backendDepsOk = $false
    }
} catch {
    $backendDepsOk = $false
}

if (-not $backendDepsOk) {
    Write-Host "Installing backend dependencies into .venv from requirements.txt..."
    Push-Location $Root
    & $VenvPython -m pip install -r requirements.txt
    $pipExit = $LASTEXITCODE
    Pop-Location
    if ($pipExit -ne 0) {
        Write-Host "[ERROR] Backend dependency installation failed." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit $pipExit
    }
}

Write-Host "Checking frontend dependencies..."
$ngCmd = Join-Path $Frontend "node_modules\.bin\ng.cmd"
if (-not (Test-Path $ngCmd)) {
    Write-Host "Installing frontend dependencies with npm install..."
    Push-Location $Frontend
    npm install
    $npmExit = $LASTEXITCODE
    Pop-Location
    if ($npmExit -ne 0) {
        Write-Host "[ERROR] Frontend dependency installation failed." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit $npmExit
    }
}

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Host "[WARN] .env was not found. Copy .env.example to .env and fill in the LLM keys before running analysis." -ForegroundColor Yellow
}

Write-Host "Starting JobScope backend and frontend..."
Write-Host "Backend:  http://127.0.0.1:8000"
Write-Host "Frontend: http://127.0.0.1:4200"
Write-Host ""

if (Test-PortListening 8000) {
    Write-Host "Backend already running on 127.0.0.1:8000; reusing it."
} else {
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/k", "`"$VenvPython`" -m uvicorn web.app:app --host 127.0.0.1 --port 8000" `
        -WorkingDirectory $Root
}

if (Test-PortListening 4200) {
    Write-Host "Frontend already running on 127.0.0.1:4200; reusing it."
} else {
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/k", "npm start -- --host 127.0.0.1 --port 4200" `
        -WorkingDirectory $Frontend
}

Start-Sleep -Seconds 5
Start-Process "http://127.0.0.1:4200"

Write-Host "Started. Keep the two opened command windows running while using the app."
Start-Sleep -Seconds 1
