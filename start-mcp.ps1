$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Job Assistant ChatGPT App MCP Launcher ===" -ForegroundColor Cyan
Write-Host ""

# Root folder of this repository
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "Repository root: $Root" -ForegroundColor DarkGray

# Current implementation uses the Node Apps SDK wrapper as the ChatGPT-facing MCP server.
# The Python server.py can still be used as a plain MCP/backend runner, but it does not reliably render ChatGPT UI widgets.
$AppsSdkDir = Join-Path $Root "apps-sdk"
$PackageJson = Join-Path $AppsSdkDir "package.json"
$NodeServer = Join-Path $AppsSdkDir "src\server.mjs"
$EnvFile = Join-Path $Root ".env"

function Import-DotEnvFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return
    }

    Write-Host "Loading environment variables from .env..." -ForegroundColor Yellow

    Get-Content $Path | ForEach-Object {
        $Line = $_.Trim()

        if (-not $Line) {
            return
        }

        if ($Line.StartsWith("#")) {
            return
        }

        $EqualsIndex = $Line.IndexOf("=")
        if ($EqualsIndex -lt 1) {
            return
        }

        $Name = $Line.Substring(0, $EqualsIndex).Trim()
        $Value = $Line.Substring($EqualsIndex + 1).Trim()

        $Value = $Value.Trim('"').Trim("'")

        if ($Name) {
            # Process-level environment variable. It is inherited by child PowerShell/npm/node processes,
            # but it does not permanently modify the user's Windows environment.
            [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
        }
    }
}

if (-not (Test-Path $AppsSdkDir)) {
    Write-Host "ERROR: apps-sdk folder not found." -ForegroundColor Red
    Write-Host "Create the Apps SDK wrapper files first:" -ForegroundColor Yellow
    Write-Host "  apps-sdk\package.json" -ForegroundColor White
    Write-Host "  apps-sdk\src\server.mjs" -ForegroundColor White
    Write-Host "  apps-sdk\widgets\test_runner_widget.html" -ForegroundColor White
    exit 1
}

if (-not (Test-Path $PackageJson)) {
    Write-Host "ERROR: apps-sdk\package.json not found." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $NodeServer)) {
    Write-Host "ERROR: apps-sdk\src\server.mjs not found." -ForegroundColor Red
    exit 1
}

# Load all variables from .env into this launcher process.
# Child windows inherit these process-level variables automatically.
Import-DotEnvFile -Path $EnvFile

if (-not $env:JOB_ASSISTANT_PROJECT_ROOT) {
    Write-Host "ERROR: JOB_ASSISTANT_PROJECT_ROOT is not set." -ForegroundColor Red
    Write-Host "Add it to .env in this repository, for example:" -ForegroundColor Yellow
    Write-Host "JOB_ASSISTANT_PROJECT_ROOT=D:\projects_py\job-assistant" -ForegroundColor White
    exit 1
}

Write-Host "Target Job Assistant project: $env:JOB_ASSISTANT_PROJECT_ROOT" -ForegroundColor DarkGray

# Check Node.js and npm
$NodeCmd = Get-Command node -ErrorAction SilentlyContinue
$NpmCmd = Get-Command npm -ErrorAction SilentlyContinue

if ($null -eq $NodeCmd -or $null -eq $NpmCmd) {
    Write-Host "ERROR: Node.js/npm not found." -ForegroundColor Red
    Write-Host "Install Node.js LTS first, then reopen PowerShell:" -ForegroundColor Yellow
    Write-Host "winget install OpenJS.NodeJS.LTS" -ForegroundColor White
    exit 1
}

Write-Host "Node: $(& node --version)" -ForegroundColor Green
Write-Host "npm:  $(& npm --version)" -ForegroundColor Green

# Install Apps SDK dependencies if needed
$NodeModules = Join-Path $AppsSdkDir "node_modules"
if (-not (Test-Path $NodeModules)) {
    Write-Host "Installing Apps SDK dependencies..." -ForegroundColor Yellow
    Push-Location $AppsSdkDir
    npm install
    Pop-Location
} else {
    Write-Host "Apps SDK dependencies already installed." -ForegroundColor Green
}

# Check ngrok
Write-Host "Checking ngrok..." -ForegroundColor Yellow
$NgrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue

if ($null -eq $NgrokCmd) {
    Write-Host "ngrok not found. Trying to install with winget..." -ForegroundColor Yellow

    $WingetCmd = Get-Command winget -ErrorAction SilentlyContinue
    if ($null -eq $WingetCmd) {
        Write-Host "ERROR: winget not found. Install ngrok manually: https://ngrok.com/download" -ForegroundColor Red
        exit 1
    }

    winget install ngrok.ngrok --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "ngrok found: $($NgrokCmd.Source)" -ForegroundColor Green
}

try {
    ngrok version
} catch {
    Write-Host "WARNING: Could not check ngrok version." -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "If ngrok says authentication failed, run once:" -ForegroundColor Yellow
Write-Host "ngrok config add-authtoken YOUR_NGROK_AUTHTOKEN" -ForegroundColor White
Write-Host ""

# Start ChatGPT-facing Node Apps SDK MCP server in separate PowerShell window.
# No manual `$env:...` assignment is injected here. The child process inherits variables loaded from .env.
Write-Host "Starting ChatGPT Apps SDK MCP server in a new PowerShell window..." -ForegroundColor Green

$AppsSdkDirForChild = $AppsSdkDir.Replace("'", "''")
$ServerCommand = @"
Set-Location '$AppsSdkDirForChild'
npm run dev
"@

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    $ServerCommand
)

# Give server time to start
Start-Sleep -Seconds 4

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
        Write-Host "============================================================" -ForegroundColor Cyan
        Write-Host "COPY THIS CHATGPT APP MCP URL:" -ForegroundColor Green
        Write-Host ""
        Write-Host $McpUrl -ForegroundColor White
        Write-Host ""
        Write-Host "Use this URL in ChatGPT. Then ask:" -ForegroundColor Yellow
        Write-Host "  Open test runner widget" -ForegroundColor White
        Write-Host "============================================================" -ForegroundColor Cyan
        Write-Host ""

        $McpUrl | Set-Clipboard
        Write-Host "ChatGPT MCP URL copied to clipboard." -ForegroundColor Green
    } else {
        Write-Host "Could not find HTTPS tunnel in ngrok API." -ForegroundColor Red
    }
} catch {
    Write-Host "Could not read ngrok tunnel URL from http://127.0.0.1:4040/api/tunnels" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}

Write-Host ""
Write-Host "The ChatGPT-facing Node Apps SDK MCP server and ngrok are running in separate PowerShell windows." -ForegroundColor DarkGray
Write-Host "Keep those windows open while using ChatGPT." -ForegroundColor DarkGray
Write-Host ""
Write-Host "Press Ctrl+C here to stop this launcher window." -ForegroundColor DarkGray

while ($true) {
    Start-Sleep -Seconds 3600
}
