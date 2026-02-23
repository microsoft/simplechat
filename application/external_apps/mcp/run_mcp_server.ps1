# run_mcp_server.ps1
# Start MCP server with streamable HTTP transport

$ErrorActionPreference = "Continue"

$mcpRoot = $PSScriptRoot
$appRoot = Resolve-Path (Join-Path $mcpRoot "..\..\single_app")
$venvPython = Join-Path $appRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Python venv not found: $venvPython"
    exit 1
}

$logDir = Join-Path $mcpRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}
$stdoutLog = Join-Path $logDir "mcp_stdout.log"

Set-Location -Path $mcpRoot
$env:FASTMCP_HOST = "0.0.0.0"
$env:FASTMCP_PORT = "8000"

$existingListener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($existingListener) {
    Write-Host "MCP server already running on port 8000."
    exit 0
}

# Start detached so the script can exit while the server keeps running.
$stderrLog = Join-Path $logDir "mcp_stderr.log"

$proc = Start-Process -FilePath $venvPython -ArgumentList @("server_minimal.py") -WorkingDirectory $mcpRoot -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -WindowStyle Hidden -PassThru

Write-Host "Started MCP server (PID $($proc.Id)) on http://localhost:8000/mcp"
