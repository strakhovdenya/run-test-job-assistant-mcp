$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Run Test Job Assistant MCP Launcher ===" -ForegroundColor Cyan
Write-Host ""

# Root folder of this script
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "MCP root: $Root" -ForegroundColor DarkGray

# Paths
$VenvDir = Join-Path $Root ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$ActivatePs1 = Join-Path $VenvDir "Scripts\Activate.ps1"
$Requirements = Join-Path $Root "requirements.txt"
$ServerPy = Join-Path $Root "server.py"

# Check server.py
if (-not (Test-Path $ServerPy)) {
    Write-Host "ERROR: server.py not found in $Root" -ForegroundColor Red
    exit 1
}

# Create venv if missing
if (-not (Test-Path $PythonExe)) {
    Write-Host "Creating Python virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
} else {
    Write-Host "Virtual environment already exists." -ForegroundColor Green
}

# Activate venv
Write-Host "Activating venv..." -ForegroundColor Yellow
. $ActivatePs1

# Upgrade pip
Write-Host "Upgrading pip..." -ForegroundColor Yellow
& $PythonExe -m pip install --upgrade pip

# Install dependencies
if (Test-Path $Requirements) {
    Write-Host "Installing requirements.txt..." -ForegroundColor Yellow
    & $PythonExe -m pip install -r $Requirements
} else {
    Write-Host "requirements.txt not found. Installing basic MCP dependencies..." -ForegroundColor Yellow
    & $PythonExe -m pip install "mcp[cli]" pytest
}

# Check ngrok
Write-Host "Checking ngrok..." -ForegroundColor Yellow

$ngrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue

if ($null -eq $ngrokCmd) {
    Write-Host "ngrok not found. Trying to install with winget..." -ForegroundColor Yellow

    $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue

    if ($null -eq $wingetCmd) {
        Write-Host "ERROR: winget not found. Install ngrok manually: https://ngrok.com/download" -ForegroundColor Red
        exit 1
    }

    winget install ngrok.ngrok --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "ngrok found: $($ngrokCmd.Source)" -ForegroundColor Green

    Write-Host "Trying to update ngrok..." -ForegroundColor Yellow
    try {
        ngrok update
    } catch {
        Write-Host "ngrok update failed or not needed. Continuing..." -ForegroundColor DarkYellow
    }
}

# Show ngrok version
try {
    ngrok version
} catch {
    Write-Host "WARNING: Could not check ngrok version." -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "If ngrok says authentication failed, run once:" -ForegroundColor Yellow
Write-Host "ngrok config add-authtoken YOUR_NGROK_AUTHTOKEN" -ForegroundColor White
Write-Host ""

# Start MCP server in separate PowerShell window
Write-Host "Starting MCP server in a new PowerShell window..." -ForegroundColor Green

$ServerCommand = @"
cd "$Root"
. ".\.venv\Scripts\Activate.ps1"
python server.py
"@

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    $ServerCommand
)

# Give MCP server time to start
Start-Sleep -Seconds 3

# Start ngrok in separate PowerShell window
Write-Host "Starting ngrok tunnel for http://localhost:8000 ..." -ForegroundColor Green

$NgrokCommand = @"
ngrok http 8000
"@

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    $NgrokCommand
)

# Give ngrok time to start
Start-Sleep -Seconds 5

# Read ngrok public URL from local API
try {
    $Tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels"

    $HttpsTunnel = $Tunnels.tunnels | Where-Object {
        $_.public_url -like "https://*"
    } | Select-Object -First 1

    if ($null -ne $HttpsTunnel) {
        $McpUrl = "$($HttpsTunnel.public_url)/mcp"

        Write-Host ""
        Write-Host "==============================================" -ForegroundColor Cyan
        Write-Host "COPY THIS MCP URL INTO CHATGPT:" -ForegroundColor Green
        Write-Host ""
        Write-Host $McpUrl -ForegroundColor White
        Write-Host ""
        Write-Host "==============================================" -ForegroundColor Cyan
        Write-Host ""

        # Copy URL to clipboard
        $McpUrl | Set-Clipboard
        Write-Host "MCP URL copied to clipboard." -ForegroundColor Green
    } else {
        Write-Host "Could not find HTTPS tunnel in ngrok API." -ForegroundColor Red
    }
} catch {
    Write-Host "Could not read ngrok tunnel URL from http://127.0.0.1:4040/api/tunnels" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}

Write-Host ""
Write-Host "MCP server and ngrok are running in separate PowerShell windows." -ForegroundColor DarkGray
Write-Host "Keep those windows open while using ChatGPT MCP." -ForegroundColor DarkGray
Write-Host ""
Write-Host "Press Ctrl+C here to stop this launcher window." -ForegroundColor DarkGray

while ($true) {
    Start-Sleep -Seconds 3600
}