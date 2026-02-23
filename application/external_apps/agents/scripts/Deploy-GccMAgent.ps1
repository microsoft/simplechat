<#
.SYNOPSIS
    Deploys the M365SCAgent declarative Copilot agent to a GCC-M (Government Community Cloud - Moderate) tenant.

.DESCRIPTION
    This script automates the deployment of the M365SCAgent declarative agent to a GCC-M tenant.
    It handles:
      1. Entra ID prerequisites (redirect URIs, requiredResourceAccess, service principal, admin consent)
      2. Template variable substitution (manifest.json, declarativeAgent.json, ai-plugin.json)
      3. Configuration ID computation (Base64 of "{tenantId}##{registrationId}")
      4. App package creation (ZIP for Teams upload)
      5. Optional: Upload to Teams App Catalog via Graph API

    IMPORTANT: The OAuth client registration must be created MANUALLY in the
    "Developer Portal (GCC Beta)" Teams app BEFORE running this script.
    ATK's `oauth/register` action may not support GCC-M Dev Portal APIs.

.PARAMETER TenantId
    The GCC-M Entra tenant ID (GUID).

.PARAMETER ClientAppId
    The Entra app registration ID for the agent (client app). Must already exist in the GCC-M tenant.

.PARAMETER ResourceAppId
    The Entra app registration ID for the MCP resource/API (e.g., SimpleChat service principal).
    If not provided, the script reads M365SC_RESOURCE_APP_ID from env/.env.<suffix>.user.

.PARAMETER ClientSecret
    The client secret for the agent app registration.

.PARAMETER OAuthRegistrationId
    The registration ID from Developer Portal (GCC Beta) OAuth client registration.
    This is the GUID shown in the Dev Portal after creating the OAuth registration.

.PARAMETER McpServerUrl
    The URL of the MCP server endpoint.
    If not provided, reads MCP_SERVER_URL from env/.env.<suffix>.user.

.PARAMETER AppNameSuffix
    Suffix appended to the app name (e.g., "gccdev", "gcc-staging"). Default: "gccdev"

.PARAMETER Scope
    The OAuth scope for the resource API. Default: api://{ResourceAppId}/access_as_user

.PARAMETER SkipEntraSetup
    Skip the Entra ID prerequisite setup (useful if already configured).

.PARAMETER SkipPackageBuild
    Skip building the app package ZIP.

.PARAMETER Upload
    Opt-in: Upload the package to Teams App Catalog via Graph API. Off by default (manual upload recommended for GCC-M).

.PARAMETER OutputDir
    Output directory for the built package. Default: ./appPackage/build

.EXAMPLE
    .\Deploy-GccMAgent.ps1 `
        -TenantId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
        -ClientAppId "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy" `
        -ClientSecret "your-secret-here" `
        -OAuthRegistrationId "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"

    ResourceAppId is read from env/.env.gccdev.user (M365SC_RESOURCE_APP_ID).
    To override, pass -ResourceAppId explicitly.

.NOTES
    Prerequisites:
    - Azure CLI (`az`) installed and logged in to the GCC-M tenant
    - PowerShell 7+ recommended
    - OAuth client registration already created in Developer Portal (GCC Beta)
    - Client app registration exists in GCC-M Entra ID
    - Resource app (or its service principal) exists in GCC-M Entra ID
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$')]
    [string]$TenantId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$')]
    [string]$ClientAppId,

    [ValidatePattern('^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$')]
    [string]$ResourceAppId = "",

    [Parameter(Mandatory = $true)]
    [string]$ClientSecret,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$')]
    [string]$OAuthRegistrationId,

    [string]$McpServerUrl = "",

    [string]$AppNameSuffix = "gccdev",

    [string]$Scope = "",

    [switch]$SkipEntraSetup,

    [switch]$SkipPackageBuild,

    [switch]$Upload,

    [string]$OutputDir = ""
)

#region ── Configuration ──────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AppPackageDir = Join-Path $ProjectRoot "appPackage"
$EnvDir = Join-Path $ProjectRoot "env"

if (-not $OutputDir) {
    $OutputDir = Join-Path $AppPackageDir "build"
}

# ── Resolve ResourceAppId from env file if not provided ──
if (-not $ResourceAppId) {
    $envUserFile = Join-Path $EnvDir ".env.$AppNameSuffix.user"
    if (Test-Path $envUserFile) {
        $envUserContent = Get-Content $envUserFile -Raw
        $match = [regex]::Match($envUserContent, 'M365SC_RESOURCE_APP_ID=([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})')
        if ($match.Success) {
            $ResourceAppId = $match.Groups[1].Value
            Write-Host "  Resolved ResourceAppId from $envUserFile" -ForegroundColor Cyan
        }
    }
    if (-not $ResourceAppId) {
        Write-Host "  ERROR: ResourceAppId not provided and M365SC_RESOURCE_APP_ID not found in $envUserFile" -ForegroundColor Red
        Write-Host "  Either pass -ResourceAppId or add M365SC_RESOURCE_APP_ID=<guid> to $envUserFile" -ForegroundColor Red
        exit 1
    }
}

if (-not $Scope) {
    $Scope = "api://$ResourceAppId/access_as_user"
}

# ── Resolve McpServerUrl from env file if not provided ──
if (-not $McpServerUrl) {
    $envUserFile = Join-Path $EnvDir ".env.$AppNameSuffix.user"
    if (Test-Path $envUserFile) {
        $envUserContent = Get-Content $envUserFile -Raw
        $match = [regex]::Match($envUserContent, 'MCP_SERVER_URL=(.+)')
        if ($match.Success) {
            $McpServerUrl = $match.Groups[1].Value.Trim()
            Write-Host "  Resolved McpServerUrl from $envUserFile" -ForegroundColor Cyan
        }
    }
    if (-not $McpServerUrl) {
        Write-Host "  ERROR: McpServerUrl not provided and MCP_SERVER_URL not found in $envUserFile" -ForegroundColor Red
        Write-Host "  Either pass -McpServerUrl or add MCP_SERVER_URL=<url> to $envUserFile" -ForegroundColor Red
        exit 1
    }
}

# GCC-M endpoints (same as commercial for GCC-M; differs for GCC-H)
$LoginEndpoint = "https://login.microsoftonline.com"
$GraphEndpoint = "https://graph.microsoft.com"

# Configuration ID = Base64("{tenantId}##{registrationId}")
$ConfigurationIdRaw = "$TenantId##$OAuthRegistrationId"
$ConfigurationId = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($ConfigurationIdRaw))

# GCC-M redirect URIs for Teams/M365 Copilot
# Note: GCC-M Teams uses teams.cloud.microsoft (same domain for GCC-M)
$RedirectUris = @(
    "https://teams.microsoft.com/api/platform/v1.0/oAuthRedirect",
    "https://teams.microsoft.com/api/platform/v1.0/oAuthConsentRedirect",
    "https://m365.cloud.microsoft/api/platform/v1.0/oAuthRedirect",
    "https://m365.cloud.microsoft/api/platform/v1.0/oAuthConsentRedirect",
    "https://teams.cloud.microsoft/api/platform/v1.0/oAuthRedirect",
    "https://teams.cloud.microsoft/api/platform/v1.0/oAuthConsentRedirect"
)
#endregion

#region ── Helper Functions ───────────────────────────────────────────────────────
function Write-StepHeader {
    param([string]$Step, [string]$Description)
    Write-Host "`n╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║  $Step" -ForegroundColor Cyan
    Write-Host "║  $Description" -ForegroundColor DarkCyan
    Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "  ✓ $Message" -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "  ℹ $Message" -ForegroundColor Yellow
}

function Write-Detail {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor Gray
}

function Confirm-Continue {
    param([string]$Prompt = "Continue?")
    $response = Read-Host "  $Prompt (Y/n)"
    if ($response -and $response -notin @('y', 'Y', 'yes', 'Yes', '')) {
        Write-Host "  Aborted by user." -ForegroundColor Red
        exit 1
    }
}

function Test-AzCliLoggedIn {
    try {
        $account = az account show 2>&1 | ConvertFrom-Json
        if ($account.tenantId -ne $TenantId) {
            Write-Warning "  Azure CLI is logged in to tenant $($account.tenantId), but target is $TenantId"
            Write-Info "Run: az login --tenant $TenantId"
            Confirm-Continue "Continue anyway?"
        }
        return $true
    }
    catch {
        Write-Warning "  Azure CLI is not logged in. Run: az login --tenant $TenantId"
        return $false
    }
}

function Invoke-GraphApi {
    param(
        [string]$Method = "GET",
        [string]$Uri,
        [string]$Body = $null
    )
    $azArgs = @("rest", "--method", $Method, "--uri", "$GraphEndpoint/$Uri", "--headers", "Content-Type=application/json")
    if ($Body) {
        # Write body to temp file to avoid shell escaping issues on Windows
        $bodyFile = [System.IO.Path]::GetTempFileName()
        $Body | Set-Content -Path $bodyFile -Encoding UTF8 -NoNewline
        $azArgs += @("--body", "@$bodyFile")
    }
    try {
        $result = az @azArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Graph API call failed: $result"
        }
        if ($result) {
            return $result | ConvertFrom-Json
        }
        return $null
    }
    finally {
        if ($bodyFile -and (Test-Path $bodyFile)) {
            Remove-Item $bodyFile -Force -ErrorAction SilentlyContinue
        }
    }
}
#endregion

#region ── Display Configuration ──────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Magenta
Write-Host "  M365SCAgent → GCC-M Deployment Script" -ForegroundColor Magenta
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Magenta
Write-Host ""
Write-Detail "Tenant ID:              $TenantId"
Write-Detail "Client App ID:          $ClientAppId"
Write-Detail "Resource App ID:        $ResourceAppId"
Write-Detail "OAuth Registration ID:  $OAuthRegistrationId"
Write-Detail "Configuration ID:       $ConfigurationId"
Write-Detail "  (decoded):            $ConfigurationIdRaw"
Write-Detail "MCP Server URL:         $McpServerUrl"
Write-Detail "App Name Suffix:        $AppNameSuffix"
Write-Detail "Scope:                  $Scope"
Write-Detail "Login Endpoint:         $LoginEndpoint"
Write-Detail "Graph Endpoint:         $GraphEndpoint"
Write-Detail "Output Directory:       $OutputDir"
Write-Host ""

Confirm-Continue "Proceed with these settings?"
#endregion

#region ── PHASE 1: Entra ID Prerequisites ────────────────────────────────────────
if (-not $SkipEntraSetup) {
    Write-StepHeader "PHASE 1: Entra ID Prerequisites" "Setting up redirect URIs, permissions, service principal, and consent"

    if (-not (Test-AzCliLoggedIn)) {
        Write-Host "  Please log in to Azure CLI and re-run." -ForegroundColor Red
        exit 1
    }

    # ── Step 1a: Add redirect URIs to the client app ──
    Write-StepHeader "Step 1a" "Add redirect URIs to client app registration"

    Write-Info "Fetching current app registration for $ClientAppId..."
    $app = Invoke-GraphApi -Uri "v1.0/applications?`$filter=appId eq '$ClientAppId'&`$select=id,appId,displayName,web"
    if (-not $app.value -or $app.value.Count -eq 0) {
        Write-Host "  ERROR: App registration with appId $ClientAppId not found in tenant." -ForegroundColor Red
        Write-Host "  Make sure the app exists in the GCC-M tenant." -ForegroundColor Red
        exit 1
    }

    $appObjectId = $app.value[0].id
    $appDisplayName = $app.value[0].displayName
    Write-Success "Found app: $appDisplayName (objectId: $appObjectId)"

    $existingRedirects = @()
    if ($app.value[0].web -and $app.value[0].web.redirectUris) {
        $existingRedirects = @($app.value[0].web.redirectUris)
    }

    $newRedirects = @($RedirectUris | Where-Object { $_ -notin $existingRedirects })
    if ($newRedirects.Count -gt 0) {
        Write-Info "Adding $($newRedirects.Count) new redirect URIs..."
        foreach ($uri in $newRedirects) { Write-Detail $uri }

        $allRedirects = @($existingRedirects) + @($newRedirects) | Select-Object -Unique
        $redirectBody = @{
            web = @{
                redirectUris = $allRedirects
            }
        } | ConvertTo-Json -Depth 5 -Compress

        if ($PSCmdlet.ShouldProcess("App $ClientAppId", "Add redirect URIs")) {
            Invoke-GraphApi -Method "PATCH" -Uri "v1.0/applications/$appObjectId" -Body $redirectBody
            Write-Success "Redirect URIs updated."
        }
    }
    else {
        Write-Success "All redirect URIs already present."
    }

    # ── Step 1b: Ensure service principal exists for resource app ──
    Write-StepHeader "Step 1b" "Ensure service principal for resource app"

    $sp = Invoke-GraphApi -Uri "v1.0/servicePrincipals?`$filter=appId eq '$ResourceAppId'&`$select=id,appId,displayName,oauth2PermissionScopes"

    if (-not $sp.value -or $sp.value.Count -eq 0) {
        Write-Info "Service principal not found for $ResourceAppId. Creating..."
        $spBody = @{ appId = $ResourceAppId } | ConvertTo-Json -Compress
        if ($PSCmdlet.ShouldProcess("Resource app $ResourceAppId", "Create service principal")) {
            $spResult = Invoke-GraphApi -Method "POST" -Uri "v1.0/servicePrincipals" -Body $spBody
            $resourceSpId = $spResult.id
            Write-Success "Created service principal: $resourceSpId"
        }
    }
    else {
        $resourceSpId = $sp.value[0].id
        $resourceSpName = $sp.value[0].displayName
        Write-Success "Service principal exists: $resourceSpName ($resourceSpId)"
    }

    # Find the scope ID for access_as_user
    $scopeName = ($Scope -split '/')[-1]  # Extract 'access_as_user' from full scope URI
    $sp = Invoke-GraphApi -Uri "v1.0/servicePrincipals?`$filter=appId eq '$ResourceAppId'&`$select=id,oauth2PermissionScopes"
    $scopeId = $null
    if ($sp.value[0].oauth2PermissionScopes) {
        $scopeObj = $sp.value[0].oauth2PermissionScopes | Where-Object { $_.value -eq $scopeName }
        if ($scopeObj) {
            $scopeId = $scopeObj.id
            Write-Success "Found scope '$scopeName' with ID: $scopeId"
        }
    }
    if (-not $scopeId) {
        Write-Warning "  Could not find scope '$scopeName' on resource app. Admin consent step may fail."
        Write-Info "You may need to define the scope on the resource app registration first."
    }

    # ── Step 1c: Set requiredResourceAccess on client app ──
    Write-StepHeader "Step 1c" "Set requiredResourceAccess on client app"

    if ($scopeId) {
        $rraBody = @{
            requiredResourceAccess = @(
                @{
                    resourceAppId = $ResourceAppId
                    resourceAccess = @(
                        @{
                            id   = $scopeId
                            type = "Scope"
                        }
                    )
                }
            )
        } | ConvertTo-Json -Depth 5 -Compress

        if ($PSCmdlet.ShouldProcess("App $ClientAppId", "Set requiredResourceAccess")) {
            Invoke-GraphApi -Method "PATCH" -Uri "v1.0/applications/$appObjectId" -Body $rraBody
            Write-Success "requiredResourceAccess configured."
        }
    }
    else {
        Write-Info "Skipping requiredResourceAccess (scope ID not found)."
    }

    # ── Step 1d: Create admin consent grant ──
    Write-StepHeader "Step 1d" "Create admin consent grant (oauth2PermissionGrants)"

    # Get client service principal ID
    $clientSp = Invoke-GraphApi -Uri "v1.0/servicePrincipals?`$filter=appId eq '$ClientAppId'&`$select=id"

    if (-not $clientSp.value -or $clientSp.value.Count -eq 0) {
        Write-Info "Client service principal not found. Creating..."
        $clientSpBody = @{ appId = $ClientAppId } | ConvertTo-Json -Compress
        if ($PSCmdlet.ShouldProcess("Client app $ClientAppId", "Create service principal")) {
            $clientSpResult = Invoke-GraphApi -Method "POST" -Uri "v1.0/servicePrincipals" -Body $clientSpBody
            $clientSpId = $clientSpResult.id
            Write-Success "Created client service principal: $clientSpId"
        }
    }
    else {
        $clientSpId = $clientSp.value[0].id
        Write-Success "Client service principal: $clientSpId"
    }

    if ($scopeId -and $clientSpId -and $resourceSpId) {
        # Check for existing grant
        $existingGrants = Invoke-GraphApi -Uri "v1.0/oauth2PermissionGrants?`$filter=clientId eq '$clientSpId' and resourceId eq '$resourceSpId'"

        if ($existingGrants.value -and $existingGrants.value.Count -gt 0) {
            $existingGrant = $existingGrants.value[0]
            Write-Info "Existing grant found (scope: $($existingGrant.scope)). Updating to include '$scopeName'..."

            $existingScopes = if ($existingGrant.scope) { $existingGrant.scope.Trim() } else { "" }
            if ($existingScopes -notmatch "\b$scopeName\b") {
                $newScopes = "$existingScopes $scopeName".Trim()
                $updateBody = @{ scope = $newScopes } | ConvertTo-Json -Compress
                if ($PSCmdlet.ShouldProcess("Grant $($existingGrant.id)", "Update consent scope")) {
                    Invoke-GraphApi -Method "PATCH" -Uri "v1.0/oauth2PermissionGrants/$($existingGrant.id)" -Body $updateBody
                    Write-Success "Updated grant scope to: $newScopes"
                }
            }
            else {
                Write-Success "Grant already includes scope '$scopeName'."
            }
        }
        else {
            Write-Info "Creating new admin consent grant (AllPrincipals)..."
            $grantBody = @{
                clientId    = $clientSpId
                consentType = "AllPrincipals"
                resourceId  = $resourceSpId
                scope       = $scopeName
            } | ConvertTo-Json -Compress

            if ($PSCmdlet.ShouldProcess("Consent grant", "Create AllPrincipals grant for $scopeName")) {
                Invoke-GraphApi -Method "POST" -Uri "v1.0/oauth2PermissionGrants" -Body $grantBody
                Write-Success "Admin consent grant created for scope '$scopeName'."
            }
        }
    }
    else {
        Write-Info "Skipping admin consent (missing scope, client SP, or resource SP)."
    }

    Write-Host ""
    Write-Success "Phase 1 complete: Entra ID prerequisites configured."
}
else {
    Write-Info "Skipping Entra ID setup (SkipEntraSetup flag set)."
}
#endregion

#region ── PHASE 2: Build App Package ─────────────────────────────────────────────
if (-not $SkipPackageBuild) {
    Write-StepHeader "PHASE 2: Build App Package" "Substituting templates and creating ZIP"

    # Ensure output directory exists
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
        Write-Success "Created output directory: $OutputDir"
    }

    # Create a temp build directory
    $buildTemp = Join-Path $OutputDir "temp_gcc_build"
    if (Test-Path $buildTemp) {
        Remove-Item -Recurse -Force $buildTemp
    }
    New-Item -ItemType Directory -Path $buildTemp -Force | Out-Null

    # ── Generate a new Teams App ID (or reuse if env file exists) ──
    $envFilePath = Join-Path $EnvDir ".env.$AppNameSuffix"
    $teamsAppId = [Guid]::NewGuid().ToString()

    if (Test-Path $envFilePath) {
        Write-Info "Found existing env file: $envFilePath"
        $envContent = Get-Content $envFilePath -Raw
        $match = [regex]::Match($envContent, 'TEAMS_APP_ID=(.+)')
        if ($match.Success -and $match.Groups[1].Value.Trim()) {
            $teamsAppId = $match.Groups[1].Value.Trim()
            Write-Success "Reusing existing TEAMS_APP_ID: $teamsAppId"
        }
    }
    else {
        Write-Info "Generated new TEAMS_APP_ID: $teamsAppId"
    }

    # ── Step 2a: Process manifest.json ──
    Write-StepHeader "Step 2a" "Process manifest.json"

    $manifestTemplate = Get-Content (Join-Path $AppPackageDir "manifest.json") -Raw
    $manifestResolved = $manifestTemplate `
        -replace '\$\{\{TEAMS_APP_ID\}\}', $teamsAppId `
        -replace '\$\{\{APP_NAME_SUFFIX\}\}', $AppNameSuffix

    $manifestResolved | Set-Content (Join-Path $buildTemp "manifest.json") -Encoding UTF8
    Write-Success "manifest.json → TEAMS_APP_ID=$teamsAppId, APP_NAME_SUFFIX=$AppNameSuffix"

    # ── Step 2b: Process declarativeAgent.json ──
    Write-StepHeader "Step 2b" "Process declarativeAgent.json"

    $agentTemplate = Get-Content (Join-Path $AppPackageDir "declarativeAgent.json") -Raw
    # The template uses $[file('instruction.txt')] — ATK resolves this at build time.
    # We need to inline the instruction.txt content.
    $instructionText = Get-Content (Join-Path $AppPackageDir "instruction.txt") -Raw
    # Escape for JSON embedding (the instruction text needs to be a valid JSON string value)
    $instructionEscaped = $instructionText.Trim() `
        -replace '\\', '\\' `
        -replace '"', '\"' `
        -replace "`r`n", '\n' `
        -replace "`n", '\n' `
        -replace "`t", '\t'

    # Replace the $[file('instruction.txt')] template with the actual content
    $agentResolved = $agentTemplate -replace '\$\[file\(''instruction\.txt''\)\]', $instructionEscaped
    # Also replace any ${{APP_NAME_SUFFIX}} in the agent name
    $agentResolved = $agentResolved -replace '\$\{\{APP_NAME_SUFFIX\}\}', $AppNameSuffix

    $agentResolved | Set-Content (Join-Path $buildTemp "declarativeAgent.json") -Encoding UTF8
    Write-Success "declarativeAgent.json → instructions inlined from instruction.txt"

    # ── Step 2c: Process ai-plugin.json ──
    Write-StepHeader "Step 2c" "Process ai-plugin.json"

    $pluginTemplate = Get-Content (Join-Path $AppPackageDir "ai-plugin.json") -Raw
    $pluginResolved = $pluginTemplate `
        -replace '\$\{\{MCP_DA_AUTH_ID_SIMPLECHAT\}\}', $ConfigurationId `
        -replace '\$\{\{APP_NAME_SUFFIX\}\}', $AppNameSuffix `
        -replace '\$\{\{MCP_SERVER_URL\}\}', $McpServerUrl

    $pluginResolved | Set-Content (Join-Path $buildTemp "ai-plugin.json") -Encoding UTF8
    Write-Success "ai-plugin.json → MCP_DA_AUTH_ID_SIMPLECHAT=$ConfigurationId, MCP_SERVER_URL=$McpServerUrl"

    # ── Step 2d: Copy icon files ──
    Write-StepHeader "Step 2d" "Copy icon files"

    Copy-Item (Join-Path $AppPackageDir "color.png") (Join-Path $buildTemp "color.png") -Force
    Copy-Item (Join-Path $AppPackageDir "outline.png") (Join-Path $buildTemp "outline.png") -Force
    Write-Success "Copied color.png and outline.png"

    # ── Step 2e: Copy instruction.txt (Teams may need it alongside declarativeAgent.json) ──
    Copy-Item (Join-Path $AppPackageDir "instruction.txt") (Join-Path $buildTemp "instruction.txt") -Force
    Write-Success "Copied instruction.txt"

    # ── Step 2f: Create ZIP package ──
    Write-StepHeader "Step 2f" "Create ZIP package"

    $zipFileName = "appPackage.$AppNameSuffix.zip"
    $zipPath = Join-Path $OutputDir $zipFileName

    if (Test-Path $zipPath) {
        Remove-Item $zipPath -Force
    }

    # Use .NET compression to create the ZIP
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($buildTemp, $zipPath)

    Write-Success "Package created: $zipPath"
    Write-Detail "Package size: $([math]::Round((Get-Item $zipPath).Length / 1KB, 1)) KB"

    # List package contents
    Write-Info "Package contents:"
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    foreach ($entry in $zip.Entries) {
        Write-Detail "  $($entry.FullName) ($([math]::Round($entry.Length / 1KB, 1)) KB)"
    }
    $zip.Dispose()

    # Clean up temp directory
    Remove-Item -Recurse -Force $buildTemp
    Write-Success "Cleaned up temp build directory."

    # ── Step 2g: Write/update env file ──
    Write-StepHeader "Step 2g" "Write environment file"

    $envContent = @"
# This file includes environment variables for the GCC-M deployment.
# Generated by Deploy-GccMAgent.ps1 on $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

# Built-in environment variables
TEAMSFX_ENV=$AppNameSuffix
APP_NAME_SUFFIX=$AppNameSuffix

# Teams App ID (generated or reused)
TEAMS_APP_ID=$teamsAppId

# GCC-M Tenant
TEAMS_APP_TENANT_ID=$TenantId

# OAuth Configuration ID = Base64("{TenantId}##{OAuthRegistrationId}")
MCP_DA_AUTH_ID_SIMPLECHAT=$ConfigurationId

# Entra App Registrations
CLIENT_APP_ID=$ClientAppId
OAUTH_REGISTRATION_ID=$OAuthRegistrationId
"@

    $envContent | Set-Content $envFilePath -Encoding UTF8
    Write-Success "Environment file written: $envFilePath"

    # Write user secrets file (gitignored)
    $envUserFilePath = Join-Path $EnvDir ".env.$AppNameSuffix.user"
    $envUserContent = @"
# This file includes secret environment variables for the GCC-M deployment.
# This file is gitignored. DO NOT commit this file.
# Generated by Deploy-GccMAgent.ps1 on $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

M365SC_CLIENT_SECRET=$ClientSecret
M365SC_RESOURCE_APP_ID=$ResourceAppId
MCP_SERVER_URL=$McpServerUrl
"@
    $envUserContent | Set-Content $envUserFilePath -Encoding UTF8
    Write-Success "User secrets file written: $envUserFilePath"

    Write-Host ""
    Write-Success "Phase 2 complete: App package built."
}
else {
    Write-Info "Skipping package build (SkipPackageBuild flag set)."
}
#endregion

#region ── PHASE 3: Upload to Teams App Catalog ───────────────────────────────────
if ($Upload) {
    Write-StepHeader "PHASE 3: Upload to Teams App Catalog" "Registering app via Graph API"

    if (-not (Test-AzCliLoggedIn)) {
        Write-Host "  Please log in to Azure CLI and re-run." -ForegroundColor Red
        exit 1
    }

    $zipPath = Join-Path $OutputDir "appPackage.$AppNameSuffix.zip"
    if (-not (Test-Path $zipPath)) {
        Write-Host "  ERROR: Package not found at $zipPath. Run without -SkipPackageBuild first." -ForegroundColor Red
        exit 1
    }

    Write-Info "Uploading app package to Teams App Catalog..."
    Write-Info "NOTE: This uses the Graph API /appCatalogs/teamsApps endpoint."
    Write-Info "For GCC-M, this may require Teams Admin permissions."
    Write-Host ""
    Confirm-Continue "Upload package to Teams App Catalog?"

    try {
        # Check if app already exists in catalog
        $existingApps = Invoke-GraphApi -Uri "v1.0/appCatalogs/teamsApps?`$filter=externalId eq '$teamsAppId'"

        if ($existingApps.value -and $existingApps.value.Count -gt 0) {
            $catalogAppId = $existingApps.value[0].id
            Write-Info "App already exists in catalog (ID: $catalogAppId). Updating..."

            # Update existing app
            # For update, we use PUT with the zip content
            az rest --method PUT `
                --uri "$GraphEndpoint/v1.0/appCatalogs/teamsApps/$catalogAppId/appDefinitions" `
                --headers "Content-Type=application/zip" `
                --body "@$zipPath" 2>&1

            if ($LASTEXITCODE -eq 0) {
                Write-Success "App updated in Teams catalog."
            }
            else {
                Write-Warning "  Update via Graph API may have failed. Consider manual upload."
            }
        }
        else {
            Write-Info "Uploading new app to catalog..."

            # For new app upload, POST the zip file
            az rest --method POST `
                --uri "$GraphEndpoint/v1.0/appCatalogs/teamsApps" `
                --headers "Content-Type=application/zip" `
                --body "@$zipPath" 2>&1

            if ($LASTEXITCODE -eq 0) {
                Write-Success "App uploaded to Teams catalog."
            }
            else {
                Write-Warning "  Upload via Graph API may have failed. Consider manual upload."
            }
        }
    }
    catch {
        Write-Host "  ERROR during upload: $_" -ForegroundColor Red
        Write-Info "You can manually upload the package through Teams Admin Center."
    }
}
else {
    Write-StepHeader "PHASE 3: Manual Upload Required" "Automatic upload skipped"
    Write-Info "The app package has been built but NOT uploaded to Teams."
    Write-Info "To deploy manually:"
    Write-Host ""
    Write-Detail "Option A: Teams Admin Center"
    Write-Detail "  1. Go to https://admin.teams.microsoft.com/policies/manage-apps"
    Write-Detail "  2. Click 'Upload new app' → 'Upload'"
    Write-Detail "  3. Select: $OutputDir\appPackage.$AppNameSuffix.zip"
    Write-Host ""
    Write-Detail "Option B: Developer Portal (GCC Beta) in Teams"
    Write-Detail "  1. Open Teams at https://teams.cloud.microsoft"
    Write-Detail "  2. Search for 'Developer Portal (GCC Beta)' app"
    Write-Detail "  3. Go to Apps → Import app → Upload ZIP"
    Write-Detail "  4. Select: $OutputDir\appPackage.$AppNameSuffix.zip"
    Write-Host ""
    Write-Detail "Option C: Use this script with -Upload"
    Write-Detail "  Requires Azure CLI logged in with Teams Admin permissions."
}
#endregion

#region ── Summary ────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host "  Deployment Summary" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host ""
Write-Detail "Target Tenant:          $TenantId"
Write-Detail "Teams App ID:           $teamsAppId"
Write-Detail "Configuration ID:       $ConfigurationId"
Write-Detail "App Package:            $OutputDir\appPackage.$AppNameSuffix.zip"
Write-Detail "Env File:               $envFilePath"
Write-Host ""

if (-not $SkipEntraSetup) {
    Write-Success "Entra ID:      Configured (redirect URIs, permissions, consent)"
}
if (-not $SkipPackageBuild) {
    Write-Success "App Package:   Built"
}
if (-not $Upload) {
    Write-Info "Upload:        Manual upload required (see instructions above)"
}
else {
    Write-Success "Upload:        Attempted via Graph API"
}

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkCyan
Write-Host "  IMPORTANT REMINDERS" -ForegroundColor DarkCyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkCyan
Write-Host ""
Write-Detail "1. OAuth registration must exist in Developer Portal (GCC Beta)"
Write-Detail "   Registration Name: simplechat"
Write-Detail "   Registration ID:   $OAuthRegistrationId"
Write-Host ""
Write-Detail "2. The Configuration ID ties the tenant to the OAuth registration:"
Write-Detail "   Base64('$TenantId##$OAuthRegistrationId')"
Write-Detail "   = $ConfigurationId"
Write-Host ""
Write-Detail "3. Redirect URIs on BOTH client and resource app registrations"
Write-Detail "   should include the Teams/M365 OAuth redirect endpoints."
Write-Host ""
Write-Detail "4. Cross-cloud note: If MCP server is in commercial Azure and the"
Write-Detail "   agent is in GCC-M, token validation must accept GCC-M tokens."
Write-Detail "   The MCP server issuer validation may need updating."
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Magenta
Write-Host "  Done." -ForegroundColor Magenta
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Magenta
#endregion
