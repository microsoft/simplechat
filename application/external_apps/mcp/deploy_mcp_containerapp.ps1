# deploy_mcp_containerapp.ps1
# Build and deploy the MCP server to Azure Container Apps

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$SubscriptionId = "56013a89-2bdc-403e-9f7f-17da3c9d8ab4",

    [Parameter(Mandatory = $false)]
    [string]$ResourceGroup = "aaronba-simplechat-rg",

    [Parameter(Mandatory = $false)]
    [string]$Location = "",

    [Parameter(Mandatory = $false)]
    [string]$ContainerAppName = "gunger-simplechat-mcp",

    [Parameter(Mandatory = $false)]
    [string]$EnvironmentName = "aaronba-simplechat-v2-env",

    [Parameter(Mandatory = $false)]
    [string]$AcrName = "aaronbasimplechatacr",

    [Parameter(Mandatory = $false)]
    [string]$ImageName = "gunger-simplechat-mcp",

    [Parameter(Mandatory = $false)]
    [string]$ImageTag = "v1",

    [Parameter(Mandatory = $false)]
    [string]$SimpleChatBaseUrl = "",

    [Parameter(Mandatory = $false)]
    [bool]$SimpleChatVerifySsl = $true,

    [Parameter(Mandatory = $false)]
    [string]$Cpu = "0.5",

    [Parameter(Mandatory = $false)]
    [string]$Memory = "1.0Gi"
)

$ErrorActionPreference = "Stop"

function Test-AzCliAvailable {
    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        Write-Error "Azure CLI (az) not found. Install it from https://aka.ms/azure-cli and retry."
        exit 1
    }
}

function Invoke-AzCli([string[]]$Arguments) {
    return & az @Arguments
}

function Initialize-AzLogin {
    try {
        Invoke-AzCli @("account", "show", "--only-show-errors") | Out-Null
    } catch {
        Write-Host "Logging into Azure..."
        Invoke-AzCli @("login", "--use-device-code") | Out-Null
    }
}

function Get-ResourceGroupLocation([string]$rgName) {
    $rgLocation = Invoke-AzCli @("group", "show", "--name", $rgName, "--query", "location", "-o", "tsv", "--only-show-errors")
    if (-not $rgLocation) {
        Write-Error "Resource group not found: $rgName"
        exit 1
    }
    return $rgLocation
}

function Get-ValidatedAcrName([string]$requestedName) {
    if ($requestedName) {
        return $requestedName.ToLower()
    }

    Write-Error "ACR name is required. Set -AcrName to an existing registry."
    exit 1
}

function Get-EnvFileSettings([string]$envFilePath) {
    if (-not (Test-Path $envFilePath)) {
        Write-Error "Env file not found: $envFilePath"
        exit 1
    }

    $settings = @{}
    $lines = Get-Content -Path $envFilePath -ErrorAction Stop
    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -ne 2) {
            continue
        }
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($key) {
            $settings[$key] = $value
        }
    }

    return $settings
}

function Get-SecretName([string]$keyName) {
    return $keyName.ToLower().Replace("_", "-")
}

function Initialize-ContainerAppExtension {
    $extensions = Invoke-AzCli @("extension", "list", "--query", "[].name", "-o", "tsv", "--only-show-errors")
    if ($extensions -notcontains "containerapp") {
        Write-Host "Installing Azure Container Apps extension..."
        Invoke-AzCli @("extension", "add", "--name", "containerapp", "--only-show-errors") | Out-Null
    }
}

Test-AzCliAvailable
Initialize-AzLogin
Initialize-ContainerAppExtension

Invoke-AzCli @("account", "set", "--subscription", $SubscriptionId, "--only-show-errors") | Out-Null

if (-not $Location) {
    $Location = Get-ResourceGroupLocation -rgName $ResourceGroup
}

$AcrName = Get-ValidatedAcrName -requestedName $AcrName

Write-Host "Using resource group: $ResourceGroup"
Write-Host "Location: $Location"
Write-Host "Container App: $ContainerAppName"
Write-Host "Container Apps Environment: $EnvironmentName"
Write-Host "ACR: $AcrName"

$rgCheck = Invoke-AzCli @("group", "show", "--name", $ResourceGroup, "--only-show-errors", "--query", "name", "-o", "tsv")
if (-not $rgCheck) {
    Write-Error "Resource group not found: $ResourceGroup"
    exit 1
}

$acrExists = Invoke-AzCli @("acr", "show", "--name", $AcrName, "--resource-group", $ResourceGroup, "--only-show-errors", "--query", "name", "-o", "tsv") 2>$null
if (-not $acrExists) {
    Write-Error "ACR not found: $AcrName"
    exit 1
}

$envExists = Invoke-AzCli @("containerapp", "env", "show", "--name", $EnvironmentName, "--resource-group", $ResourceGroup, "--only-show-errors", "--query", "name", "-o", "tsv") 2>$null
if (-not $envExists) {
    Write-Error "Container Apps environment not found: $EnvironmentName"
    exit 1
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $scriptRoot

# Prefer .env.azure for cloud deployments, fall back to .env for local values
$envFilePath = Join-Path $scriptRoot ".env.azure"
if (-not (Test-Path $envFilePath)) {
    $envFilePath = Join-Path $scriptRoot ".env"
    Write-Host "Using local .env (no .env.azure found)"
} else {
    Write-Host "Using .env.azure for cloud deployment"
}
$envSettings = Get-EnvFileSettings -envFilePath $envFilePath

if (-not $SimpleChatBaseUrl) {
    if ($envSettings.ContainsKey("SIMPLECHAT_BASE_URL")) {
        $SimpleChatBaseUrl = $envSettings["SIMPLECHAT_BASE_URL"]
    } else {
        Write-Error "SIMPLECHAT_BASE_URL is required. Set it in .env or pass -SimpleChatBaseUrl."
        exit 1
    }
}

if ($envSettings.ContainsKey("SIMPLECHAT_VERIFY_SSL")) {
    $SimpleChatVerifySsl = $envSettings["SIMPLECHAT_VERIFY_SSL"].ToLower() -in @("1", "true", "yes", "y", "on")
}

$imageTag = "${ImageName}:${ImageTag}"
Write-Host "Building image in ACR: $imageTag"
Invoke-AzCli @("acr", "build", "--registry", $AcrName, "--image", $imageTag, ".", "--no-logs", "--only-show-errors") | Out-Null

$acrLoginServer = Invoke-AzCli @("acr", "show", "--name", $AcrName, "--resource-group", $ResourceGroup, "--query", "loginServer", "-o", "tsv", "--only-show-errors")
$acrCreds = (Invoke-AzCli @("acr", "credential", "show", "--name", $AcrName, "--query", "{username:username,password:passwords[0].value}", "-o", "json", "--only-show-errors")) | ConvertFrom-Json

$containerImage = "$acrLoginServer/$imageTag"

$appExists = Invoke-AzCli @("containerapp", "show", "--name", $ContainerAppName, "--resource-group", $ResourceGroup, "--only-show-errors", "--query", "name", "-o", "tsv") 2>$null
if (-not $appExists) {
    Write-Host "Creating Container App: $ContainerAppName"
    $secrets = @()
    $envVars = @()
    $hasBaseUrl = $false
    $hasVerifySsl = $false
    foreach ($entry in $envSettings.GetEnumerator()) {
        $secretName = Get-SecretName -keyName $entry.Key
        $secrets += "{0}={1}" -f $secretName, $entry.Value
        $envVars += "{0}=secretref:{1}" -f $entry.Key, $secretName
        if ($entry.Key -eq "SIMPLECHAT_BASE_URL") {
            $hasBaseUrl = $true
        }
        if ($entry.Key -eq "SIMPLECHAT_VERIFY_SSL") {
            $hasVerifySsl = $true
        }
    }
    if (-not $hasBaseUrl) {
        $envVars += "SIMPLECHAT_BASE_URL=$SimpleChatBaseUrl"
    }
    if (-not $hasVerifySsl) {
        $envVars += "SIMPLECHAT_VERIFY_SSL=$SimpleChatVerifySsl"
    }
    $envVars += "FASTMCP_HOST=0.0.0.0"
    $envVars += "FASTMCP_PORT=8000"
    $createArgs = @(
        "containerapp", "create",
        "--name", $ContainerAppName,
        "--resource-group", $ResourceGroup,
        "--environment", $EnvironmentName,
        "--image", $containerImage,
        "--registry-server", $acrLoginServer,
        "--registry-username", $acrCreds.username,
        "--registry-password", $acrCreds.password,
        "--ingress", "external",
        "--target-port", "8000",
        "--transport", "auto",
        "--cpu", $Cpu,
        "--memory", $Memory,
        "--min-replicas", "1",
        "--max-replicas", "1",
        "--secrets"
    ) + $secrets + @(
        "--env-vars"
    ) + $envVars + @(
        "--only-show-errors"
    )
    Invoke-AzCli $createArgs | Out-Null
} else {
    Write-Host "Updating Container App: $ContainerAppName"
    $secrets = @()
    $envVars = @()
    $hasBaseUrl = $false
    $hasVerifySsl = $false
    foreach ($entry in $envSettings.GetEnumerator()) {
        $secretName = Get-SecretName -keyName $entry.Key
        $secrets += "{0}={1}" -f $secretName, $entry.Value
        $envVars += "{0}=secretref:{1}" -f $entry.Key, $secretName
        if ($entry.Key -eq "SIMPLECHAT_BASE_URL") {
            $hasBaseUrl = $true
        }
        if ($entry.Key -eq "SIMPLECHAT_VERIFY_SSL") {
            $hasVerifySsl = $true
        }
    }
    if (-not $hasBaseUrl) {
        $envVars += "SIMPLECHAT_BASE_URL=$SimpleChatBaseUrl"
    }
    if (-not $hasVerifySsl) {
        $envVars += "SIMPLECHAT_VERIFY_SSL=$SimpleChatVerifySsl"
    }
    $envVars += "FASTMCP_HOST=0.0.0.0"
    $envVars += "FASTMCP_PORT=8000"
    $secretArgs = @(
        "containerapp", "secret", "set",
        "--name", $ContainerAppName,
        "--resource-group", $ResourceGroup,
        "--secrets"
    ) + $secrets + @(
        "--only-show-errors"
    )
    Invoke-AzCli $secretArgs | Out-Null

    $updateArgs = @(
        "containerapp", "update",
        "--name", $ContainerAppName,
        "--resource-group", $ResourceGroup,
        "--image", $containerImage,
        "--cpu", $Cpu,
        "--memory", $Memory,
        "--set-env-vars"
    ) + $envVars + @(
        "--only-show-errors"
    )
    Invoke-AzCli $updateArgs | Out-Null
}

$appUrl = Invoke-AzCli @("containerapp", "show", "--name", $ContainerAppName, "--resource-group", $ResourceGroup, "--query", "properties.configuration.ingress.fqdn", "-o", "tsv", "--only-show-errors")
Write-Host "Deployment complete."
Write-Host "MCP Server URL: https://$appUrl"
