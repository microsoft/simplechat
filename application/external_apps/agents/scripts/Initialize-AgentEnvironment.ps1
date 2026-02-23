<#
.SYNOPSIS
    Prepares the Entra ID environment for the M365SCAgent declarative agent,
    then hands off to ATK (Agents Toolkit) for provisioning.

.DESCRIPTION
    This script complements the ATK 'provision' command by handling prerequisites
    that ATK cannot perform automatically:

      1. Validates Azure CLI login and tenant
      2. Creates or locates the client app registration for the agent
      3. Generates a client secret (or reuses an existing one)
      4. Locates the resource app registration (MCP server API)
      5. Resolves the MCP server URL
      6. Populates env/.env.<suffix>.user with the required values
      7. Optionally runs 'atk provision' automatically

    After this script completes, env/.env.<suffix>.user will contain the values
    ATK needs for the oauth/register action in m365agents.yml.

    Workflow:
      Initialize-AgentEnvironment.ps1  →  populates .env.dev.user
      atk provision                    →  reads .env.dev.user, registers OAuth, builds package

.PARAMETER AppName
    Base name for the agent's Entra app registration.
    Default: "simplechat-agent"

.PARAMETER Environment
    Environment suffix (matches ATK TEAMSFX_ENV). Default: "dev"

.PARAMETER ResourceAppId
    The app ID of the MCP server's API resource. If omitted, the script
    searches for it by display name using -ResourceAppName.

.PARAMETER ResourceAppName
    Display name pattern to search for the resource app registration.
    Used only if -ResourceAppId is not provided. Default: "simplechat"

.PARAMETER McpServerUrl
    Full URL to the MCP server /mcp endpoint. If omitted, the script
    prompts for it.

.PARAMETER SecretExpirationDays
    Days until the generated client secret expires. Default: 180

.PARAMETER SkipAtkProvision
    Do not run 'atk provision' after populating the env file.

.EXAMPLE
    .\Initialize-AgentEnvironment.ps1

    Interactively sets up with defaults (dev environment).

.EXAMPLE
    .\Initialize-AgentEnvironment.ps1 -McpServerUrl "https://my-mcp.azurecontainerapps.io/mcp" -ResourceAppId "00000000-0000-0000-0000-000000000000"

    Fully non-interactive setup with known values.

.NOTES
    Prerequisites:
    - Azure CLI installed and logged in to the target tenant
    - ATK (Agents Toolkit) VS Code extension installed (for atk provision)
    - The MCP server resource app registration must already exist in Entra ID
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$AppName = "simplechat-agent",

    [string]$Environment = "dev",

    [ValidatePattern('^$|^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$')]
    [string]$ResourceAppId = "",

    [string]$ResourceAppName = "simplechat",

    [string]$McpServerUrl = "",

    [int]$SecretExpirationDays = 180,

    [switch]$SkipAtkProvision
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvDir = Join-Path $ProjectRoot "env"
$EnvFile = Join-Path $EnvDir ".env.$Environment"
$EnvUserFile = Join-Path $EnvDir ".env.$Environment.user"

#region ── Helper Functions ───────────────────────────────────────────────────────

function Write-Step {
    param([string]$Number, [string]$Description)
    Write-Host "`n────────────────────────────────────────────────────────────" -ForegroundColor Cyan
    Write-Host "  Step ${Number}: $Description" -ForegroundColor Cyan
    Write-Host "────────────────────────────────────────────────────────────" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  OK: $Message" -ForegroundColor Green
}

function Write-Detail {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor Gray
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  WARN: $Message" -ForegroundColor Yellow
}

function Get-CloudEnvironment {
    try {
        $cloud = az cloud show --output json 2>$null | ConvertFrom-Json
        return $cloud.name
    }
    catch {
        return "AzureCloud"
    }
}

function Get-GraphEndpoint {
    param([string]$CloudName)
    switch ($CloudName) {
        "AzureUSGovernment" { return "https://graph.microsoft.us" }
        default { return "https://graph.microsoft.com" }
    }
}

function Get-LoginEndpoint {
    param([string]$CloudName)
    switch ($CloudName) {
        "AzureUSGovernment" { return "https://login.microsoftonline.us" }
        default { return "https://login.microsoftonline.com" }
    }
}

function Invoke-Graph {
    param(
        [string]$Method = "GET",
        [string]$Uri,
        [string]$Body = $null
    )
    $graphUrl = $script:GraphEndpoint
    $azArgs = @("rest", "--method", $Method, "--uri", "$graphUrl/$Uri", "--headers", "Content-Type=application/json", "--only-show-errors")
    if ($Body) {
        $azArgs += @("--body", $Body)
    }
    $result = az @azArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Graph API call failed ($Method $Uri): $result"
    }
    if ($result) {
        return $result | ConvertFrom-Json
    }
    return $null
}

#endregion

#region ── Banner ─────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host "  M365SCAgent — Initialize Agent Environment" -ForegroundColor Magenta
Write-Host "  Prepares prerequisites for ATK provision" -ForegroundColor DarkMagenta
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host ""

#endregion

#region ── Step 1: Validate Azure CLI ─────────────────────────────────────────────

Write-Step "1" "Validate Azure CLI login"

try {
    $account = az account show --output json 2>$null | ConvertFrom-Json
    $tenantId = $account.tenantId
    $cloudName = Get-CloudEnvironment
    $script:GraphEndpoint = Get-GraphEndpoint -CloudName $cloudName
    $loginEndpoint = Get-LoginEndpoint -CloudName $cloudName

    Write-Ok "Logged in to tenant: $tenantId"
    Write-Detail "Cloud: $cloudName"
    Write-Detail "Graph: $script:GraphEndpoint"
}
catch {
    Write-Host "  ERROR: Azure CLI is not logged in." -ForegroundColor Red
    Write-Host "  Run: az login" -ForegroundColor Red
    exit 1
}

# Cross-check with .env.dev if TEAMS_APP_TENANT_ID is already set
if (Test-Path $EnvFile) {
    $envContent = Get-Content $EnvFile -Raw
    $match = [regex]::Match($envContent, 'TEAMS_APP_TENANT_ID=(.+)')
    if ($match.Success -and $match.Groups[1].Value.Trim()) {
        $envTenantId = $match.Groups[1].Value.Trim()
        if ($envTenantId -ne $tenantId) {
            Write-Warn "Azure CLI tenant ($tenantId) differs from .env.$Environment tenant ($envTenantId)"
            $response = Read-Host "  Continue with CLI tenant $tenantId? (Y/n)"
            if ($response -and $response -notin @('y', 'Y', 'yes', '')) {
                exit 1
            }
        }
    }
}

#endregion

#region ── Step 2: Create or locate client app registration ───────────────────────

Write-Step "2" "Create or locate client app registration"

$clientAppRegName = "$AppName-$Environment-ar"
Write-Detail "Looking for: $clientAppRegName"

$existingApp = az ad app list --display-name $clientAppRegName --output json --only-show-errors | ConvertFrom-Json

if ($existingApp -and $existingApp.Count -gt 0) {
    $clientApp = $existingApp[0]
    $clientAppId = $clientApp.appId
    Write-Ok "Found existing app: $clientAppRegName (appId: $clientAppId)"
}
else {
    Write-Detail "Not found. Creating new app registration: $clientAppRegName"

    if ($PSCmdlet.ShouldProcess($clientAppRegName, "Create app registration")) {
        $clientApp = az ad app create `
            --display-name $clientAppRegName `
            --sign-in-audience AzureADMyOrg `
            --output json --only-show-errors | ConvertFrom-Json

        if (-not $clientApp) {
            throw "Failed to create app registration: $clientAppRegName"
        }

        $clientAppId = $clientApp.appId
        Write-Ok "Created app: $clientAppRegName (appId: $clientAppId)"

        # Create service principal
        Write-Detail "Creating service principal..."
        az ad sp create --id $clientAppId --only-show-errors | Out-Null
        Write-Ok "Service principal created"
    }
    else {
        # WhatIf mode — use placeholder so downstream steps don't break
        $clientAppId = "<will-be-created>"
        $clientSecret = "<will-be-created>"
    }
}

#endregion

#region ── Step 3: Generate client secret ─────────────────────────────────────────

Write-Step "3" "Generate client secret"

# Check if there's already a secret in the env user file
$existingSecret = ""
if (Test-Path $EnvUserFile) {
    $userContent = Get-Content $EnvUserFile -Raw
    $secretMatch = [regex]::Match($userContent, 'M365SC_CLIENT_SECRET=(.+)')
    if ($secretMatch.Success -and $secretMatch.Groups[1].Value.Trim()) {
        $existingSecret = $secretMatch.Groups[1].Value.Trim()
    }
}

if ($existingSecret) {
    Write-Ok "Client secret already exists in .env.$Environment.user — reusing"
    Write-Detail "(To regenerate, clear M365SC_CLIENT_SECRET in the file and re-run)"
    $clientSecret = $existingSecret
}
else {
    $expirationDate = (Get-Date).AddDays($SecretExpirationDays).ToString("yyyy-MM-dd")
    Write-Detail "Generating secret expiring $expirationDate..."

    if ($PSCmdlet.ShouldProcess($clientAppRegName, "Generate client secret")) {
        $clientSecret = az ad app credential reset `
            --id $clientAppId `
            --append `
            --end-date $expirationDate `
            --query password `
            --output tsv --only-show-errors

        if (-not $clientSecret) {
            throw "Failed to generate client secret"
        }

        Write-Ok "Client secret generated (expires $expirationDate)"
    }
}

#endregion

#region ── Step 4: Locate resource app registration (MCP API) ─────────────────────

Write-Step "4" "Locate resource app registration (MCP server API)"

if (-not $ResourceAppId) {
    Write-Detail "Searching for resource app by name pattern: *$ResourceAppName*"

    $resourceApps = az ad app list --display-name $ResourceAppName --output json --only-show-errors | ConvertFrom-Json

    if ($resourceApps -and $resourceApps.Count -gt 0) {
        if ($resourceApps.Count -eq 1) {
            $ResourceAppId = $resourceApps[0].appId
            Write-Ok "Found: $($resourceApps[0].displayName) (appId: $ResourceAppId)"
        }
        else {
            Write-Host ""
            Write-Host "  Multiple apps found matching '$ResourceAppName':" -ForegroundColor Yellow
            for ($i = 0; $i -lt $resourceApps.Count; $i++) {
                Write-Host "    [$i] $($resourceApps[$i].displayName) — $($resourceApps[$i].appId)" -ForegroundColor White
            }
            $selection = Read-Host "  Enter number to select (or paste an appId directly)"

            if ($selection -match '^[0-9]+$' -and [int]$selection -lt $resourceApps.Count) {
                $ResourceAppId = $resourceApps[[int]$selection].appId
            }
            elseif ($selection -match '^[0-9a-fA-F]{8}-') {
                $ResourceAppId = $selection.Trim()
            }
            else {
                Write-Host "  Invalid selection." -ForegroundColor Red
                exit 1
            }
            Write-Ok "Selected resource app: $ResourceAppId"
        }
    }
    else {
        Write-Warn "No app registrations found matching '$ResourceAppName'."
        if ($WhatIfPreference) {
            Write-Detail "(WhatIf mode — skipping interactive prompt, using placeholder)"
            $ResourceAppId = "00000000-0000-0000-0000-000000000000"
        }
        else {
            $ResourceAppId = Read-Host "  Enter the Resource App ID (MCP server API) manually"
            if (-not $ResourceAppId) {
                Write-Host "  ERROR: Resource App ID is required." -ForegroundColor Red
                exit 1
            }
        }
    }
}
else {
    Write-Ok "Using provided Resource App ID: $ResourceAppId"
}

# Verify the resource app exists and check for access_as_user scope
if ($WhatIfPreference) {
    Write-Detail "(WhatIf mode — skipping resource app verification)"
}
else {
    Write-Detail "Verifying resource app and checking scopes..."
    $resourceSp = Invoke-Graph -Uri "v1.0/servicePrincipals?`$filter=appId eq '$ResourceAppId'&`$select=id,displayName,oauth2PermissionScopes"

    if (-not $resourceSp.value -or $resourceSp.value.Count -eq 0) {
        Write-Warn "Service principal not found for resource app $ResourceAppId."
        if ($PSCmdlet.ShouldProcess($ResourceAppId, "Create service principal for resource app")) {
            $spBody = @{ appId = $ResourceAppId } | ConvertTo-Json -Compress
            Invoke-Graph -Method "POST" -Uri "v1.0/servicePrincipals" -Body $spBody | Out-Null
            Write-Ok "Service principal created for resource app."
        }
    }
    else {
        $resourceSpName = $resourceSp.value[0].displayName
        Write-Ok "Resource app verified: $resourceSpName"

        # Check for access_as_user scope
        $scopes = $resourceSp.value[0].oauth2PermissionScopes
        if ($scopes) {
            $accessScope = $scopes | Where-Object { $_.value -eq "access_as_user" }
            if ($accessScope) {
                Write-Ok "Scope 'access_as_user' found on resource app"
            }
            else {
                Write-Warn "Scope 'access_as_user' NOT found on resource app."
                Write-Detail "You may need to add this scope in the Azure Portal under:"
                Write-Detail "  App registrations > $resourceSpName > Expose an API > Add a scope"
            }
        }
    }
}

#endregion

#region ── Step 5: Resolve MCP server URL ─────────────────────────────────────────

Write-Step "5" "Resolve MCP server URL"

if (-not $McpServerUrl) {
    # Try reading from the MCP project's env file
    $mcpEnvPath = Join-Path $ProjectRoot ".." "mcp" ".env"
    if (Test-Path $mcpEnvPath) {
        $mcpEnvContent = Get-Content $mcpEnvPath -Raw
        # Look for the deployed URL (not localhost)
        $urlMatch = [regex]::Match($mcpEnvContent, 'SIMPLECHAT_BASE_URL=(https?://[^\s]+)')
        if ($urlMatch.Success) {
            Write-Detail "Found candidate from MCP .env: $($urlMatch.Groups[1].Value)"
        }
    }

    if ($WhatIfPreference) {
        Write-Detail "(WhatIf mode — skipping interactive prompt, using placeholder)"
        $McpServerUrl = "<will-be-provided>"
    }
    else {
        $McpServerUrl = Read-Host "  Enter the MCP server URL (e.g. https://your-mcp.azurecontainerapps.io/mcp)"
        if (-not $McpServerUrl) {
            Write-Host "  ERROR: MCP server URL is required." -ForegroundColor Red
            exit 1
        }
    }
}

# Validate URL format
if ($McpServerUrl -notmatch '^https?://') {
    Write-Host "  ERROR: MCP server URL must start with http:// or https://" -ForegroundColor Red
    exit 1
}

Write-Ok "MCP server URL: $McpServerUrl"

#endregion

#region ── Step 6: Write env/.env.<suffix>.user ───────────────────────────────────

Write-Step "6" "Write environment file"

$envUserContent = @"
# ============================================================
# env/.env.$Environment.user — Agent secrets (gitignored)
# ============================================================
# Generated by Initialize-AgentEnvironment.ps1 on $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
# These values are consumed by ATK during 'atk provision'.
# ============================================================

# Entra tenant ID
TEAMS_APP_TENANT_ID=$tenantId

# Client app registration for the agent OAuth flow
M365SC_CLIENT_APP_ID=$clientAppId

# Client secret for that app registration
M365SC_CLIENT_SECRET=$clientSecret

# Resource app ID (MCP server API — used in scope: api://<id>/access_as_user)
M365SC_RESOURCE_APP_ID=$ResourceAppId

# Full URL to the MCP server endpoint
MCP_SERVER_URL=$McpServerUrl

# ATK populates this during 'atk provision' via oauth/register
MCP_DA_AUTH_ID_SIMPLECHAT=
"@

if ($PSCmdlet.ShouldProcess($EnvUserFile, "Write environment variables")) {
    $envUserContent | Set-Content $EnvUserFile -Encoding UTF8
    Write-Ok "Written: $EnvUserFile"
}

#endregion

#region ── Summary ────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Environment Ready for ATK Provision" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Detail "Tenant ID:           $tenantId"
Write-Detail "Client App ID:       $clientAppId"
Write-Detail "Client App Name:     $clientAppRegName"
Write-Detail "Resource App ID:     $ResourceAppId"
Write-Detail "MCP Server URL:      $McpServerUrl"
Write-Detail "Secret Expires:      $((Get-Date).AddDays($SecretExpirationDays).ToString('yyyy-MM-dd'))"
Write-Detail "Env File:            $EnvUserFile"
Write-Host ""

#endregion

#region ── Step 7: Optionally run ATK provision ───────────────────────────────────

if (-not $SkipAtkProvision) {
    Write-Step "7" "Run ATK provision"

    # Check if atk CLI is available
    $atkAvailable = Get-Command "teamsapp" -ErrorAction SilentlyContinue
    if (-not $atkAvailable) {
        $atkAvailable = Get-Command "teamsfx" -ErrorAction SilentlyContinue
    }

    if ($atkAvailable) {
        Write-Detail "ATK CLI found: $($atkAvailable.Source)"
        $response = Read-Host "  Run 'atk provision' now? (Y/n)"
        if (-not $response -or $response -in @('y', 'Y', 'yes')) {
            Write-Detail "Running ATK provision..."
            Push-Location $ProjectRoot
            try {
                & $atkAvailable.Name provision --env $Environment
            }
            finally {
                Pop-Location
            }
        }
        else {
            Write-Detail "Skipped. Run manually:"
            Write-Host ""
            Write-Host "  cd $ProjectRoot" -ForegroundColor White
            Write-Host "  atk provision --env $Environment" -ForegroundColor White
        }
    }
    else {
        Write-Warn "ATK CLI not found in PATH."
        Write-Detail "To provision, use one of these options:"
        Write-Host ""
        Write-Host "  Option A: VS Code Agents Toolkit sidebar → Provision" -ForegroundColor White
        Write-Host "  Option B: Install ATK CLI and run:" -ForegroundColor White
        Write-Host "            cd $ProjectRoot" -ForegroundColor Gray
        Write-Host "            teamsapp provision --env $Environment" -ForegroundColor Gray
    }
}
else {
    Write-Host ""
    Write-Detail "Skipped ATK provision (use -SkipAtkProvision to suppress this)."
    Write-Detail "Next step — run ATK provision:"
    Write-Host ""
    Write-Host "  VS Code: Agents Toolkit sidebar → Provision" -ForegroundColor White
    Write-Host "  CLI:     cd $ProjectRoot && teamsapp provision --env $Environment" -ForegroundColor White
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host "  Done." -ForegroundColor Magenta
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host ""

#endregion
