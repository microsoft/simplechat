<#
.SYNOPSIS
    Performs a code-only SimpleChat container upgrade for the Azure CLI deployer.
.DESCRIPTION
    This PowerShell script builds a new container image in Azure Container Registry
    using ACR Tasks and updates an existing Azure App Service to pull that image.

    This is the Azure CLI deployer equivalent of an `azd deploy` style code-only
    rollout. It does not provision or change infrastructure resources beyond the
    target web app's container configuration.

    The script supports either:
        - explicit targeting with -ResourceGroupName and -WebAppName
        - derived targeting with -BaseName and -Environment to match deploy-simplechat.ps1

    The deployment model remains a container-based Azure App Service. Gunicorn
    startup continues to come from the container entrypoint.

.NOTES
    Author: Microsoft Federal
    Date: 2026-04-29
    Version: 1.0

    Prerequisites:
        - Azure CLI installed and authenticated.
        - Access to the target subscription, ACR, and App Service.
        - The target ACR already exists.
        - The target web app already exists and is configured for the SimpleChat container path.

    Azure Commercial login example:
        az cloud set --name AzureCloud
        az login --scope https://management.azure.com//.default
        az account set -s "<subscription-id>"

    Azure Government login example:
        az cloud set --name AzureUSGovernment
        az login --scope https://management.core.usgovcloudapi.net//.default
        az account set -s "<subscription-id>"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AcrName,

    [Parameter(Mandatory = $true)]
    [string]$ImageName,

    [string]$BaseName,

    [string]$Environment,

    [string]$ResourceGroupName,

    [string]$WebAppName,

    [string]$SubscriptionId,

    [ValidateSet("AzureCloud", "AzureUSGovernment", "Custom")]
    [string]$AzurePlatform = "AzureCloud",

    [string]$AzureCliCustomCloudName = "",

    [string]$DockerfilePath = "application/single_app/Dockerfile",

    [string]$BuildContextPath = "..\..",

    [switch]$SkipAcrBuild,

    [bool]$PublishLatestTag = $true,

    [bool]$RestartWebApp = $true,

    [string]$Slot
)

$PSModuleAutoloadingPreference = "All"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-AzureCliCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [switch]$AllowEmptyOutput
    )

    $output = & az @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $joined = $Arguments -join ' '
        throw "Azure CLI command failed: az $joined`n$output"
    }

    if ($output -is [array]) {
        $output = $output -join [Environment]::NewLine
    }

    if (-not $AllowEmptyOutput -and $null -eq $output) {
        return ""
    }

    return $output
}

function Ensure-AzureCliAuthenticated {
    if (-not (Get-Command "az" -ErrorAction SilentlyContinue)) {
        throw "Azure CLI is not installed. Please install it before running this script."
    }

    $expectedCloudName = switch ($AzurePlatform) {
        'AzureCloud' { 'AzureCloud' }
        'AzureUSGovernment' { 'AzureUSGovernment' }
        'Custom' { $AzureCliCustomCloudName }
        default { $null }
    }

    if ([string]::IsNullOrWhiteSpace($expectedCloudName)) {
        throw "Custom cloud usage requires -AzureCliCustomCloudName."
    }

    $currentCloudName = Invoke-AzureCliCommand -Arguments @('cloud', 'show', '--query', 'name', '--output', 'tsv')
    if ([string]::IsNullOrWhiteSpace($currentCloudName) -or $currentCloudName.Trim() -ne $expectedCloudName) {
        Write-Host "Switching Azure CLI cloud to '$expectedCloudName'..." -ForegroundColor Yellow
        Invoke-AzureCliCommand -Arguments @('cloud', 'set', '--name', $expectedCloudName) -AllowEmptyOutput | Out-Null
    }

    & az account show --output none 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI is not authenticated. Run 'az login' first and retry."
    }

    if (-not [string]::IsNullOrWhiteSpace($SubscriptionId)) {
        Write-Host "Setting active subscription to '$SubscriptionId'..." -ForegroundColor Yellow
        Invoke-AzureCliCommand -Arguments @('account', 'set', '--subscription', $SubscriptionId) -AllowEmptyOutput | Out-Null
    }
}

function Resolve-ContainerImageInfo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RequestedImageName
    )

    if ([string]::IsNullOrWhiteSpace($RequestedImageName)) {
        throw "ImageName must not be empty."
    }

    $lastSlashIndex = $RequestedImageName.LastIndexOf('/')
    $lastColonIndex = $RequestedImageName.LastIndexOf(':')

    if ($lastColonIndex -gt $lastSlashIndex) {
        $repository = $RequestedImageName.Substring(0, $lastColonIndex)
        $tag = $RequestedImageName.Substring($lastColonIndex + 1)
    } else {
        $repository = $RequestedImageName
        $tag = 'latest'
    }

    if ([string]::IsNullOrWhiteSpace($repository) -or [string]::IsNullOrWhiteSpace($tag)) {
        throw "ImageName must use 'repository' or 'repository:tag'. Current value: $RequestedImageName"
    }

    return [PSCustomObject]@{
        Repository = $repository
        Tag        = $tag
        FullName   = "$repository`:$tag"
    }
}

function Resolve-TargetNames {
    if (-not [string]::IsNullOrWhiteSpace($ResourceGroupName) -and -not [string]::IsNullOrWhiteSpace($WebAppName)) {
        return [PSCustomObject]@{
            ResourceGroupName = $ResourceGroupName
            WebAppName        = $WebAppName
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($ResourceGroupName) -or -not [string]::IsNullOrWhiteSpace($WebAppName)) {
        throw "Specify either both -ResourceGroupName and -WebAppName, or both -BaseName and -Environment."
    }

    if ([string]::IsNullOrWhiteSpace($BaseName) -or [string]::IsNullOrWhiteSpace($Environment)) {
        throw "Specify either both -ResourceGroupName and -WebAppName, or both -BaseName and -Environment."
    }

    return [PSCustomObject]@{
        ResourceGroupName = "sc-$($BaseName)-$($Environment)-rg".ToLower()
        WebAppName        = "$($BaseName)-$($Environment)-app".ToLower()
    }
}

function Get-AcrConnectionInfo {
    $registryInfoRaw = Invoke-AzureCliCommand -Arguments @('acr', 'show', '--name', $AcrName, '--query', '{loginServer:loginServer,adminUserEnabled:adminUserEnabled}', '--output', 'json')
    $registryInfo = $registryInfoRaw | ConvertFrom-Json

    if ([string]::IsNullOrWhiteSpace($registryInfo.loginServer)) {
        throw "Unable to resolve the login server for ACR '$AcrName'."
    }

    if (-not $registryInfo.adminUserEnabled) {
        Write-Host "Enabling ACR admin user on '$AcrName' to match the Azure CLI deployer flow..." -ForegroundColor Yellow
        Invoke-AzureCliCommand -Arguments @('acr', 'update', '--name', $AcrName, '--admin-enabled', 'true') -AllowEmptyOutput | Out-Null
    }

    return [PSCustomObject]@{
        LoginServer = $registryInfo.loginServer
        RegistryUrl = "https://$($registryInfo.loginServer)"
    }
}

function Invoke-AcrContainerBuild {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$ContainerImageInfo
    )

    $resolvedContextPath = Resolve-Path -Path (Join-Path $PSScriptRoot $BuildContextPath) -ErrorAction Stop
    $dockerfileFullPath = Join-Path $resolvedContextPath $DockerfilePath

    if (-not (Test-Path -Path $dockerfileFullPath)) {
        throw "Dockerfile not found at '$dockerfileFullPath'."
    }

    $arguments = @(
        'acr', 'build',
        '--registry', $AcrName,
        '--file', $DockerfilePath,
        '--image', $ContainerImageInfo.FullName
    )

    if ($PublishLatestTag -and $ContainerImageInfo.Tag -ne 'latest') {
        $arguments += @('--image', "$($ContainerImageInfo.Repository):latest")
    }

    $arguments += $resolvedContextPath.Path

    Write-Host "`n=====> Building image in Azure Container Registry..." -ForegroundColor Cyan
    Write-Host "Registry: $AcrName"
    Write-Host "Image: $($ContainerImageInfo.FullName)"
    Write-Host "Dockerfile: $DockerfilePath"
    Write-Host "Build context: $($resolvedContextPath.Path)"

    Invoke-AzureCliCommand -Arguments $arguments -AllowEmptyOutput | Out-Null
}

function Ensure-WebAppExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedResourceGroupName,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedWebAppName
    )

    $queryArgs = @('webapp', 'show', '--resource-group', $ResolvedResourceGroupName, '--name', $ResolvedWebAppName)
    if (-not [string]::IsNullOrWhiteSpace($Slot)) {
        $queryArgs += @('--slot', $Slot)
    }
    $queryArgs += @('--query', '{name:name,defaultHostName:defaultHostName,state:state}', '--output', 'json')

    $webAppRaw = Invoke-AzureCliCommand -Arguments $queryArgs
    return $webAppRaw | ConvertFrom-Json
}

function Update-WebAppContainerImage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedResourceGroupName,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedWebAppName,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$AcrConnectionInfo,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ContainerImageInfo
    )

    $acrUsername = Invoke-AzureCliCommand -Arguments @('acr', 'credential', 'show', '--name', $AcrName, '--query', 'username', '--output', 'tsv')
    $acrPassword = Invoke-AzureCliCommand -Arguments @('acr', 'credential', 'show', '--name', $AcrName, '--query', 'passwords[0].value', '--output', 'tsv')
    $expectedImageName = "$($AcrConnectionInfo.LoginServer)/$($ContainerImageInfo.FullName)"

    $arguments = @(
        'webapp', 'config', 'container', 'set',
        '--name', $ResolvedWebAppName,
        '--resource-group', $ResolvedResourceGroupName,
        '--container-image-name', $expectedImageName,
        '--container-registry-url', $AcrConnectionInfo.RegistryUrl,
        '--container-registry-user', $acrUsername.Trim(),
        '--container-registry-password', $acrPassword.Trim()
    )

    if (-not [string]::IsNullOrWhiteSpace($Slot)) {
        $arguments += @('--slot', $Slot)
    }

    Write-Host "`n=====> Updating App Service container settings..." -ForegroundColor Cyan
    Invoke-AzureCliCommand -Arguments $arguments -AllowEmptyOutput | Out-Null

    return $expectedImageName
}

function Confirm-WebAppContainerImage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedResourceGroupName,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedWebAppName,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedImageName
    )

    $arguments = @(
        'webapp', 'config', 'container', 'show',
        '--name', $ResolvedWebAppName,
        '--resource-group', $ResolvedResourceGroupName,
        '--query', '{image:DOCKER_CUSTOM_IMAGE_NAME,registry:DOCKER_REGISTRY_SERVER_URL}',
        '--output', 'json'
    )

    if (-not [string]::IsNullOrWhiteSpace($Slot)) {
        $arguments += @('--slot', $Slot)
    }

    $containerStateRaw = Invoke-AzureCliCommand -Arguments $arguments
    $containerState = $containerStateRaw | ConvertFrom-Json

    if ($containerState.image -ne $ExpectedImageName) {
        throw "Web app container configuration did not update to '$ExpectedImageName'. Current value: '$($containerState.image)'"
    }
}

function Restart-WebAppIfRequested {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedResourceGroupName,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedWebAppName
    )

    if (-not $RestartWebApp) {
        return
    }

    $arguments = @(
        'webapp', 'restart',
        '--name', $ResolvedWebAppName,
        '--resource-group', $ResolvedResourceGroupName
    )

    if (-not [string]::IsNullOrWhiteSpace($Slot)) {
        $arguments += @('--slot', $Slot)
    }

    Write-Host "`n=====> Restarting App Service..." -ForegroundColor Cyan
    Invoke-AzureCliCommand -Arguments $arguments -AllowEmptyOutput | Out-Null
}

Write-Host "`nSimpleChat Upgrade Executing" -ForegroundColor Green
Write-Host "This script performs a code-only container rollout for the Azure CLI deployer." -ForegroundColor Green

Ensure-AzureCliAuthenticated

$targetNames = Resolve-TargetNames
$containerImageInfo = Resolve-ContainerImageInfo -RequestedImageName $ImageName
$acrConnectionInfo = Get-AcrConnectionInfo
$webApp = Ensure-WebAppExists -ResolvedResourceGroupName $targetNames.ResourceGroupName -ResolvedWebAppName $targetNames.WebAppName

if (-not $SkipAcrBuild) {
    Invoke-AcrContainerBuild -ContainerImageInfo $containerImageInfo
} else {
    Write-Host "Skipping ACR build because -SkipAcrBuild was specified." -ForegroundColor Yellow
}

$expectedImageName = Update-WebAppContainerImage -ResolvedResourceGroupName $targetNames.ResourceGroupName -ResolvedWebAppName $targetNames.WebAppName -AcrConnectionInfo $acrConnectionInfo -ContainerImageInfo $containerImageInfo
Confirm-WebAppContainerImage -ResolvedResourceGroupName $targetNames.ResourceGroupName -ResolvedWebAppName $targetNames.WebAppName -ExpectedImageName $expectedImageName
Restart-WebAppIfRequested -ResolvedResourceGroupName $targetNames.ResourceGroupName -ResolvedWebAppName $targetNames.WebAppName

$slotSuffix = if ([string]::IsNullOrWhiteSpace($Slot)) { '' } else { " (slot: $Slot)" }
Write-Host "`nUpgrade complete.$slotSuffix" -ForegroundColor Green
Write-Host "Resource Group: $($targetNames.ResourceGroupName)"
Write-Host "Web App: $($targetNames.WebAppName)"
Write-Host "Image: $expectedImageName"
Write-Host "Default Hostname: $($webApp.defaultHostName)"