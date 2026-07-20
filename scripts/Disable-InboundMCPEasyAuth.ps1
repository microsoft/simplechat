$tenantId = ''
$resourceGroup = ''
$appName = ''
$subscriptionId = ''
$resourceManagerEndpoint = ''
$preferredCloudName = ''
$simpleChatApiClientId = ''
$requiredDelegatedScope = 'DelegatedMcpServerAccess'
$requiredUserRoles = @('InboundMCPUserAccess')
$requiredAppRoles = @('InboundMCPAppAccess')
$requiredPaths = @(
    "/.well-known/oauth-protected-resource/mcp",
    "/api/mcp",
    "/api/mcp/health"
)

$placeholderValues = @(
    "<tenant-id>",
    "<resource-group-name>",
    "<app-service-name>",
    "<resource-manager-endpoint>",
    "<simplechat-api-client-id>",
    "<required-delegated-scope>",
    "<required-user-role>",
    "<required-app-role>"
)

foreach ($requiredValue in @($tenantId, $resourceGroup, $appName, $resourceManagerEndpoint)) {
    if ([string]::IsNullOrWhiteSpace($requiredValue) -or $placeholderValues -contains $requiredValue) {
        throw "Update the generated script placeholders before running it."
    }
}

function Normalize-Endpoint([string] $value) {
    if ($null -eq $value) {
        return ""
    }
    return $value.Trim().TrimEnd("/")
}

$resourceManagerEndpoint = Normalize-Endpoint $resourceManagerEndpoint
$cloudNameToSet = $preferredCloudName

if ([string]::IsNullOrWhiteSpace($cloudNameToSet)) {
    $registeredClouds = az cloud list -o json | ConvertFrom-Json
    $matchingClouds = @($registeredClouds | Where-Object {
        (Normalize-Endpoint $_.endpoints.resourceManager) -ieq $resourceManagerEndpoint
    })

    if ($matchingClouds.Count -eq 1) {
        $cloudNameToSet = $matchingClouds[0].name
    } elseif ($matchingClouds.Count -gt 1) {
        $matchingNames = ($matchingClouds | ForEach-Object { $_.name }) -join ", "
        throw "Multiple Azure CLI clouds match Resource Manager endpoint '$resourceManagerEndpoint': $matchingNames. Set `$preferredCloudName to the intended registered cloud name."
    } else {
        throw "No registered Azure CLI cloud matches Resource Manager endpoint '$resourceManagerEndpoint'. Register the custom cloud first, then rerun this script."
    }
}

$activeCloudName = az cloud show --query name -o tsv 2>$null
if ($LASTEXITCODE -ne 0 -or $activeCloudName -ne $cloudNameToSet) {
    az cloud set --name $cloudNameToSet
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to set Azure CLI cloud '$cloudNameToSet'."
    }
}

$activeResourceManagerEndpoint = Normalize-Endpoint (az cloud show --query endpoints.resourceManager -o tsv)
if ($activeResourceManagerEndpoint -ine $resourceManagerEndpoint) {
    throw "The active Azure CLI cloud Resource Manager endpoint '$activeResourceManagerEndpoint' does not match SimpleChat's endpoint '$resourceManagerEndpoint'."
}

$currentTenantId = az account show --query tenantId -o tsv 2>$null
if ($LASTEXITCODE -ne 0 -or $currentTenantId -ne $tenantId) {
    az login --tenant $tenantId
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI login failed for tenant '$tenantId'."
    }
}

if (-not [string]::IsNullOrWhiteSpace($subscriptionId)) {
    az account set --subscription $subscriptionId
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to select subscription '$subscriptionId'."
    }
}

$hasSimpleChatApiClientId = -not [string]::IsNullOrWhiteSpace($simpleChatApiClientId) -and $placeholderValues -notcontains $simpleChatApiClientId
$hasRequiredDelegatedScope = -not [string]::IsNullOrWhiteSpace($requiredDelegatedScope) -and $placeholderValues -notcontains $requiredDelegatedScope
$requiredUserRolesToCheck = @($requiredUserRoles | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $placeholderValues -notcontains $_ })
$requiredAppRolesToCheck = @($requiredAppRoles | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $placeholderValues -notcontains $_ })
if ($hasSimpleChatApiClientId -and ($hasRequiredDelegatedScope -or $requiredUserRolesToCheck.Count -gt 0 -or $requiredAppRolesToCheck.Count -gt 0)) {
    Write-Host "Checking that the SimpleChat API app registration exposes inbound MCP scope and role requirements..."
    $apiApplicationJson = az ad app show --id $simpleChatApiClientId -o json 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($apiApplicationJson)) {
        $apiApplication = $apiApplicationJson | ConvertFrom-Json
        if ($hasRequiredDelegatedScope) {
            $matchingScopes = @($apiApplication.api.oauth2PermissionScopes | Where-Object {
                $_.value -eq $requiredDelegatedScope -and ($_.isEnabled -eq $true -or $_.isEnabled -eq "true")
            })
            if ($matchingScopes.Count -eq 0) {
                throw "The SimpleChat API app registration '$simpleChatApiClientId' does not expose enabled delegated scope '$requiredDelegatedScope'. Add the scope under Expose an API or update the Inbound MCP required delegated scope setting."
            }
        }
        foreach ($requiredUserRole in $requiredUserRolesToCheck) {
            $matchingUserRoles = @($apiApplication.appRoles | Where-Object {
                $_.value -eq $requiredUserRole -and ($_.isEnabled -eq $true -or $_.isEnabled -eq "true") -and @($_.allowedMemberTypes) -contains "User"
            })
            if ($matchingUserRoles.Count -eq 0) {
                throw "The SimpleChat API app registration '$simpleChatApiClientId' does not expose enabled user-assignable app role '$requiredUserRole'. Add the role under App roles or update the Inbound MCP required delegated user roles setting."
            }
        }
        foreach ($requiredAppRole in $requiredAppRolesToCheck) {
            $matchingAppRoles = @($apiApplication.appRoles | Where-Object {
                $_.value -eq $requiredAppRole -and ($_.isEnabled -eq $true -or $_.isEnabled -eq "true") -and @($_.allowedMemberTypes) -contains "Application"
            })
            if ($matchingAppRoles.Count -eq 0) {
                throw "The SimpleChat API app registration '$simpleChatApiClientId' does not expose enabled application app role '$requiredAppRole'. Add the role under App roles or update the Inbound MCP required app-only roles setting."
            }
        }
    } else {
        Write-Warning "Could not inspect the SimpleChat API app registration for inbound MCP scope and roles. Continue only if you already confirmed they exist and are enabled."
    }
}

$siteId = az webapp show --resource-group $resourceGroup --name $appName --query id -o tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($siteId)) {
    throw "Could not resolve App Service '$appName' in resource group '$resourceGroup'."
}

$authSettingsUrl = "$resourceManagerEndpoint$siteId/config/authsettingsV2?api-version=2023-12-01"
$rawCurrent = az rest --method get --url $authSettingsUrl
if ($LASTEXITCODE -ne 0) {
    throw "Failed to read authsettingsV2."
}

$current = $rawCurrent | ConvertFrom-Json

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = Join-Path (Get-Location) "simplechat-authsettingsV2-backup-$timestamp.json"
$current | ConvertTo-Json -Depth 100 | Set-Content -Path $backupPath -Encoding utf8
Write-Host "Backed up current authsettingsV2 to $backupPath"

if (-not $current.properties.globalValidation) {
    $current.properties | Add-Member -NotePropertyName globalValidation -NotePropertyValue ([pscustomobject]@{})
}

if (-not ($current.properties.globalValidation.PSObject.Properties.Name -contains "excludedPaths")) {
    $current.properties.globalValidation | Add-Member -NotePropertyName excludedPaths -NotePropertyValue @()
}

$excludedPaths = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($path in @($current.properties.globalValidation.excludedPaths)) {
    if (-not [string]::IsNullOrWhiteSpace($path)) {
        [void]$excludedPaths.Add($path)
    }
}
foreach ($path in $requiredPaths) {
    [void]$excludedPaths.Add($path)
}

$current.properties.globalValidation.excludedPaths = @($excludedPaths)
$bodyPath = Join-Path ([System.IO.Path]::GetTempPath()) "simplechat-authsettingsV2-$timestamp.json"
$current | ConvertTo-Json -Depth 100 | Set-Content -Path $bodyPath -Encoding utf8
az rest --method put --url $authSettingsUrl --headers "Content-Type=application/json" --body "@$bodyPath"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to update authsettingsV2. Backup remains at $backupPath."
}

Write-Host "Updated authsettingsV2 excludedPaths for inbound MCP. Backup remains at $backupPath."
