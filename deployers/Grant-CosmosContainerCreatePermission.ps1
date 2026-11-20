# Grant-CosmosContainerCreatePermission.ps1
<#
.SYNOPSIS
Lets the SimpleChat app's managed identity create missing Cosmos DB containers.

.DESCRIPTION
When SimpleChat runs with managed identity, Cosmos DB refuses to create containers
through its data-plane endpoint, whatever data-plane role the identity holds. On
startup the app then creates any missing container through Azure Resource Manager
instead, which needs an Azure role with
Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/write on the account.

The azd (Bicep) and Terraform deployers already give the identity Contributor on the
Cosmos account. Run this script for deployments that did not, or where Contributor
was removed. It:
1. Resolves the web app's system-assigned managed identity (or uses -PrincipalId).
2. Creates the custom role "SimpleChat Cosmos Container Creator <resource group>" if it
   does not exist. The role can read the account, its databases and containers, and
   create or update containers. It cannot read keys, items or account settings.
3. Assigns that role to the identity on the Cosmos account.

Use -UseBuiltInRole to assign the built-in "DocumentDB Account Contributor" role
instead of creating a custom role. That role is broader: it can manage the whole
account, including listing its keys.

.PARAMETER ResourceGroupName
Resource group that holds the Cosmos DB account.

.PARAMETER CosmosAccountName
Name of the Cosmos DB account.

.PARAMETER WebAppName
Name of the SimpleChat App Service whose system-assigned identity gets the role.

.PARAMETER WebAppResourceGroupName
Resource group of the App Service. Defaults to ResourceGroupName.

.PARAMETER PrincipalId
Object ID of the identity to grant, instead of looking it up from WebAppName. Use it
for a user-assigned identity.

.PARAMETER SubscriptionId
Subscription to work in. Defaults to the Azure CLI's current subscription.

.PARAMETER UseBuiltInRole
Assign "DocumentDB Account Contributor" instead of the narrower custom role.

.EXAMPLE
.\Grant-CosmosContainerCreatePermission.ps1 -ResourceGroupName "simplechat-prod-rg" -CosmosAccountName "simplechat-prod-cosmos" -WebAppName "simplechat-prod-app"

.EXAMPLE
.\Grant-CosmosContainerCreatePermission.ps1 -ResourceGroupName "simplechat-prod-rg" -CosmosAccountName "simplechat-prod-cosmos" -WebAppName "simplechat-prod-app" -WhatIf

Shows what would be created and assigned without changing anything.

.NOTES
- Requires the Azure CLI, signed in with `az login`.
- Creating the custom role needs Microsoft.Authorization/roleDefinitions/write on the
  resource group, and assigning it needs Microsoft.Authorization/roleAssignments/write
  on the Cosmos account (for example Owner, or User Access Administrator plus a role
  that can create role definitions).
- Restart the App Service afterwards so it retries creating any missing containers.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory = $true)]
    [string]$CosmosAccountName,

    [Parameter(Mandatory = $false)]
    [string]$WebAppName,

    [Parameter(Mandatory = $false)]
    [string]$WebAppResourceGroupName,

    [Parameter(Mandatory = $false)]
    [string]$PrincipalId,

    [Parameter(Mandatory = $false)]
    [string]$SubscriptionId,

    [switch]$UseBuiltInRole
)

$ErrorActionPreference = 'Stop'

$BuiltInRoleName = 'DocumentDB Account Contributor'
$CustomRoleActions = @(
    'Microsoft.DocumentDB/databaseAccounts/read'
    'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/read'
    'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/read'
    'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/write'
)

function Invoke-AzCli {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $output = & az @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "az $($Arguments -join ' ') failed: $($output | Out-String)"
    }
    return ($output | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n"
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'The Azure CLI (az) is not installed or not on PATH.'
}

if (-not $WebAppName -and -not $PrincipalId) {
    throw 'Pass -WebAppName to look up the app identity, or -PrincipalId to name it directly.'
}

if ($SubscriptionId) {
    Invoke-AzCli @('account', 'set', '--subscription', $SubscriptionId) | Out-Null
}
$SubscriptionId = Invoke-AzCli @('account', 'show', '--query', 'id', '-o', 'tsv')
Write-Host "Subscription: $SubscriptionId"

if (-not $WebAppResourceGroupName) {
    $WebAppResourceGroupName = $ResourceGroupName
}

if (-not $PrincipalId) {
    $PrincipalId = Invoke-AzCli @(
        'webapp', 'identity', 'show',
        '--resource-group', $WebAppResourceGroupName,
        '--name', $WebAppName,
        '--query', 'principalId', '-o', 'tsv'
    )
    if (-not $PrincipalId) {
        throw "App Service '$WebAppName' has no system-assigned managed identity. Enable one, or pass -PrincipalId."
    }
}
Write-Host "Managed identity principal ID: $PrincipalId"

$cosmosAccountId = Invoke-AzCli @(
    'cosmosdb', 'show',
    '--resource-group', $ResourceGroupName,
    '--name', $CosmosAccountName,
    '--query', 'id', '-o', 'tsv'
)
$resourceGroupId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroupName"
Write-Host "Cosmos DB account: $cosmosAccountId"

if ($UseBuiltInRole) {
    $roleName = $BuiltInRoleName
    $roleId = Invoke-AzCli @('role', 'definition', 'list', '--name', $roleName, '--query', '[0].id', '-o', 'tsv')
}
else {
    $roleName = "SimpleChat Cosmos Container Creator $ResourceGroupName"
    $roleId = Invoke-AzCli @(
        'role', 'definition', 'list',
        '--name', $roleName,
        '--scope', $resourceGroupId,
        '--query', '[0].id', '-o', 'tsv'
    )

    if ($roleId) {
        Write-Host "Custom role '$roleName' already exists."
    }
    elseif ($PSCmdlet.ShouldProcess($resourceGroupId, "Create custom role '$roleName'")) {
        $roleDefinition = @{
            Name             = $roleName
            IsCustom         = $true
            Description      = 'Lets SimpleChat create missing Cosmos DB SQL containers through Azure Resource Manager. Grants no key, item or account-settings access.'
            Actions          = $CustomRoleActions
            NotActions       = @()
            DataActions      = @()
            NotDataActions   = @()
            AssignableScopes = @($resourceGroupId)
        }
        $roleFile = Join-Path ([System.IO.Path]::GetTempPath()) "simplechat-cosmos-container-role-$([guid]::NewGuid()).json"
        try {
            $roleDefinition | ConvertTo-Json -Depth 5 | Set-Content -Path $roleFile -Encoding utf8
            $roleId = Invoke-AzCli @('role', 'definition', 'create', '--role-definition', "@$roleFile", '--query', 'id', '-o', 'tsv')
        }
        finally {
            Remove-Item -Path $roleFile -Force -ErrorAction SilentlyContinue
        }
        Write-Host "Created custom role '$roleName'."
    }
}

if (-not $roleId -and -not $WhatIfPreference) {
    throw "Could not resolve the role '$roleName'."
}

$existingAssignment = Invoke-AzCli @(
    'role', 'assignment', 'list',
    '--assignee', $PrincipalId,
    '--scope', $cosmosAccountId,
    '--query', "[?roleDefinitionName=='$roleName'] | [0].id", '-o', 'tsv'
)

if ($existingAssignment) {
    Write-Host "The identity already has '$roleName' on the Cosmos account."
}
elseif ($PSCmdlet.ShouldProcess($cosmosAccountId, "Assign '$roleName' to principal $PrincipalId")) {
    # A newly created role definition can take a minute to replicate.
    $maxAttempts = 6
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            Invoke-AzCli @(
                'role', 'assignment', 'create',
                '--assignee-object-id', $PrincipalId,
                '--assignee-principal-type', 'ServicePrincipal',
                '--role', $roleId,
                '--scope', $cosmosAccountId
            ) | Out-Null
            break
        }
        catch {
            if ($attempt -eq $maxAttempts -or $_.Exception.Message -notmatch 'RoleDefinitionDoesNotExist|does not exist') {
                throw
            }
            Write-Host "Role definition not visible yet; retrying in 15 seconds ($attempt/$maxAttempts)..."
            Start-Sleep -Seconds 15
        }
    }
    Write-Host "Assigned '$roleName' to the identity on the Cosmos account."
}

Write-Host ''
Write-Host 'Done. Role assignments can take a few minutes to take effect.'
if ($WebAppName) {
    Write-Host "Restart the app so it creates any missing containers:"
    Write-Host "  az webapp restart --resource-group $WebAppResourceGroupName --name $WebAppName"
}
