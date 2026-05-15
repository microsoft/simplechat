<#
.SYNOPSIS
    Creates or updates GitHub Actions Azure OIDC and staging UI test configuration.

.DESCRIPTION
    This script prepares a SimpleChat repository for a protected staging GitHub Actions
    workflow. It creates an Entra app registration and service principal for GitHub
    OIDC, adds a federated credential for a GitHub Environment, optionally grants
    Azure RBAC for azd up/deploy, optionally assigns a UI test principal to the
    SimpleChat Enterprise App, and writes the required GitHub Environment variables
    and secrets when the GitHub CLI is installed and authenticated.

.PARAMETER GitHubRepository
    GitHub repository in owner/name format. If omitted, the script attempts to read
    the origin remote from the current git repository.

.PARAMETER GitHubEnvironment
    GitHub Environment name. Defaults to Staging.

.PARAMETER AzdEnvironmentName
    Azure Developer CLI environment name. Defaults to staging.

.PARAMETER AppName
    SimpleChat deployment app name. Defaults to simplechat.

.PARAMETER AzureLocation
    Azure location for azd environment creation or workflow fallback variables.
    If omitted, the current azd environment value or Azure CLI default is used.

.PARAMETER CiAppRegistrationName
    Display name for the GitHub Actions OIDC app registration. Defaults to
    "<AppName>-<AzdEnvironmentName>-github-actions".

.PARAMETER RoleAssignmentScope
    Azure RBAC scope for the GitHub Actions service principal. Defaults to the
    current subscription because the SimpleChat Bicep entrypoint is subscription-scoped.
    Use a resource group scope for deploy-only workflows against existing infrastructure.

.PARAMETER PlaywrightWorkspaceName
    Optional Microsoft Playwright Workspaces resource name. Defaults to
    "<AppName>-<AzdEnvironmentName>-pw".

.PARAMETER PlaywrightWorkspaceLocation
    Azure region for the Playwright workspace. Playwright Workspaces currently
    supports a smaller region set than App Service; defaults to eastus.

.PARAMETER PlaywrightWorkspaceResourceGroupName
    Optional resource group for the Playwright workspace. Defaults to
    "<AppName>-<AzdEnvironmentName>-rg" so it lives beside the staging app.

.PARAMETER SkipPlaywrightWorkspace
    Do not create or configure Microsoft Playwright Workspaces.

.PARAMETER AppServiceResourceGroupName
    Optional App Service resource group name used when enabling CI bearer session auth.
    Defaults to the azd var_rgName output or "<AppName>-<AzdEnvironmentName>-rg".

.PARAMETER AppServiceName
    Optional App Service name used when enabling CI bearer session auth. Defaults to
    the azd var_webService output or "<AppName>-<AzdEnvironmentName>-app".

.PARAMETER SkipCiBearerSessionAuth
    Do not configure the staging app to accept GitHub Actions app-only bearer
    tokens through the guarded /ci-auth/session endpoint.

.PARAMETER SkipRoleAssignments
    Do not create Azure role assignments for the GitHub Actions service principal.

.PARAMETER SkipGitHubConfiguration
    Do not write GitHub Environment variables or secrets.

.PARAMETER ForceFederatedCredentialUpdate
    Recreate the GitHub OIDC federated credential if it already exists.

.PARAMETER AzdEnvironmentValuesPath
    Optional path to an azd .env file to store in GitHub as AZD_ENV_FILE_B64. If not
    supplied, the script runs `azd env get-values -e <AzdEnvironmentName>`.

.PARAMETER UiStorageStatePath
    Optional Playwright storage_state JSON file for a signed-in staging user.

.PARAMETER AdminUiStorageStatePath
    Optional Playwright storage_state JSON file for a signed-in staging admin.

.PARAMETER SimpleChatUiBaseUrl
    Optional staging base URL. Defaults to the standard App Service hostname for
    <AppName>-<AzdEnvironmentName>-app in the current Azure cloud.

.PARAMETER EnterpriseAppClientId
    Optional SimpleChat Enterprise App client ID. When supplied with UiTestPrincipalObjectId,
    the script assigns the principal to the requested app role using Microsoft Graph.

.PARAMETER UiTestPrincipalObjectId
    Optional Entra user or group object ID for the UI test browser identity.

.PARAMETER UiTestAppRoleValue
    SimpleChat app role value to assign to UiTestPrincipalObjectId. Defaults to User.

.EXAMPLE
    .\Initialize-GitHubActionsStaging.ps1 -GitHubRepository microsoft/simplechat -AzdEnvironmentName staging -AppName simplechat -UiStorageStatePath .\ui-storage-state.json

.EXAMPLE
    .\Initialize-GitHubActionsStaging.ps1 -SkipGitHubConfiguration

.NOTES
    - Requires Azure CLI and Azure Developer CLI.
    - GitHub secret/variable writes require GitHub CLI (`gh`) and `gh auth login`.
    - The workflow uses OIDC, so no Azure client secret is stored in GitHub.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$GitHubRepository,

    [Parameter(Mandatory = $false)]
    [string]$GitHubEnvironment = "Staging",

    [Parameter(Mandatory = $false)]
    [string]$AzdEnvironmentName = "staging",

    [Parameter(Mandatory = $false)]
    [string]$AppName = "simplechat",

    [Parameter(Mandatory = $false)]
    [string]$AzureLocation,

    [Parameter(Mandatory = $false)]
    [string]$CiAppRegistrationName,

    [Parameter(Mandatory = $false)]
    [string]$RoleAssignmentScope,

    [Parameter(Mandatory = $false)]
    [string]$PlaywrightWorkspaceName,

    [Parameter(Mandatory = $false)]
    [string]$PlaywrightWorkspaceLocation = "eastus",

    [Parameter(Mandatory = $false)]
    [string]$PlaywrightWorkspaceResourceGroupName,

    [Parameter(Mandatory = $false)]
    [switch]$SkipPlaywrightWorkspace,

    [Parameter(Mandatory = $false)]
    [string]$AppServiceResourceGroupName,

    [Parameter(Mandatory = $false)]
    [string]$AppServiceName,

    [Parameter(Mandatory = $false)]
    [switch]$SkipCiBearerSessionAuth,

    [Parameter(Mandatory = $false)]
    [switch]$SkipRoleAssignments,

    [Parameter(Mandatory = $false)]
    [switch]$SkipGitHubConfiguration,

    [Parameter(Mandatory = $false)]
    [switch]$ForceFederatedCredentialUpdate,

    [Parameter(Mandatory = $false)]
    [string]$AzdEnvironmentValuesPath,

    [Parameter(Mandatory = $false)]
    [string]$UiStorageStatePath,

    [Parameter(Mandatory = $false)]
    [string]$AdminUiStorageStatePath,

    [Parameter(Mandatory = $false)]
    [string]$SimpleChatUiBaseUrl,

    [Parameter(Mandatory = $false)]
    [string]$EnterpriseAppClientId,

    [Parameter(Mandatory = $false)]
    [string]$UiTestPrincipalObjectId,

    [Parameter(Mandatory = $false)]
    [string]$UiTestAppRoleValue = "User"
)

$ErrorActionPreference = "Stop"
$GitHubSecretLimit = 48000

function Write-InfoMessage {
    param([string]$Message)
    Write-Host "INFO: $Message" -ForegroundColor Cyan
}

function Write-SuccessMessage {
    param([string]$Message)
    Write-Host "SUCCESS: $Message" -ForegroundColor Green
}

function Write-WarningMessage {
    param([string]$Message)
    Write-Host "WARNING: $Message" -ForegroundColor Yellow
}

function Write-ErrorMessage {
    param([string]$Message)
    Write-Host "ERROR: $Message" -ForegroundColor Red
}

function Get-CommandOutputText {
    param($CommandOutput)

    if ($null -eq $CommandOutput) {
        return ""
    }

    return (($CommandOutput | Out-String).Trim())
}

function Test-CommandAvailable {
    param([string]$CommandName)
    return ($null -ne (Get-Command $CommandName -ErrorAction SilentlyContinue))
}

function Invoke-AzureCliJson {
    param(
        [string]$Description,
        [scriptblock]$Command
    )

    Write-InfoMessage $Description
    $output = & $Command 2>&1
    $exitCode = $LASTEXITCODE
    $outputText = Get-CommandOutputText -CommandOutput $output

    if ($exitCode -ne 0) {
        throw "$Description failed. Azure CLI returned: $outputText"
    }

    if ([string]::IsNullOrWhiteSpace($outputText)) {
        return $null
    }

    return ($outputText | ConvertFrom-Json)
}

function Invoke-AzureCliText {
    param(
        [string]$Description,
        [scriptblock]$Command
    )

    Write-InfoMessage $Description
    $output = & $Command 2>&1
    $exitCode = $LASTEXITCODE
    $outputText = Get-CommandOutputText -CommandOutput $output

    if ($exitCode -ne 0) {
        throw "$Description failed. Azure CLI returned: $outputText"
    }

    return $outputText
}

function Resolve-GitHubRepository {
    param([string]$RequestedRepository)

    if (-not [string]::IsNullOrWhiteSpace($RequestedRepository)) {
        return $RequestedRepository.Trim()
    }

    if (-not (Test-CommandAvailable -CommandName "git")) {
        throw "GitHubRepository is required because git is not available to inspect the origin remote."
    }

    $remoteUrl = git remote get-url origin 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($remoteUrl)) {
        throw "GitHubRepository is required because the origin remote could not be resolved."
    }

    $trimmedUrl = $remoteUrl.Trim()
    if ($trimmedUrl -match "github\.com[:/](?<owner>[^/]+)/(?<repo>[^/.]+)(\.git)?$") {
        return "$($Matches.owner)/$($Matches.repo)"
    }

    throw "Could not parse GitHub owner/repository from origin remote '$trimmedUrl'."
}

function Get-CurrentAzureAccount {
    if (-not (Test-CommandAvailable -CommandName "az")) {
        throw "Azure CLI is required. Install Azure CLI and run az login before this script."
    }

    return Invoke-AzureCliJson -Description "Reading current Azure CLI account" -Command {
        az account show --query "{subscriptionId:id, tenantId:tenantId, user:user.name}" -o json
    }
}

function Resolve-AzureLocation {
    param([string]$RequestedLocation)

    if (-not [string]::IsNullOrWhiteSpace($RequestedLocation)) {
        return $RequestedLocation.Trim()
    }

    if (Test-CommandAvailable -CommandName "azd") {
        $azdLocation = azd env get-value AZURE_LOCATION -e $AzdEnvironmentName --cwd $PSScriptRoot 2>$null
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($azdLocation)) {
            return $azdLocation.Trim('"').Trim()
        }
    }

    $defaultLocation = az configure --list-defaults --query "[?name=='location'].value | [0]" -o tsv 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($defaultLocation)) {
        return $defaultLocation.Trim()
    }

    throw "AzureLocation is required because no azd or Azure CLI default location could be resolved."
}

function Get-AzdEnvironmentValue {
    param([string]$Name)

    if (-not (Test-CommandAvailable -CommandName "azd")) {
        return $null
    }

    $value = azd env get-value $Name -e $AzdEnvironmentName --cwd $PSScriptRoot 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($value)) {
        return $value.Trim('"').Trim()
    }

    return $null
}

function Resolve-EnterpriseAppClientId {
    param([string]$RequestedClientId)

    if (-not [string]::IsNullOrWhiteSpace($RequestedClientId)) {
        return $RequestedClientId.Trim()
    }

    return Get-AzdEnvironmentValue -Name "ENTERPRISE_APP_CLIENT_ID"
}

function Resolve-AppServiceResourceGroupName {
    param([string]$RequestedResourceGroupName)

    if (-not [string]::IsNullOrWhiteSpace($RequestedResourceGroupName)) {
        return $RequestedResourceGroupName.Trim()
    }

    $azdValue = Get-AzdEnvironmentValue -Name "var_rgName"
    if (-not [string]::IsNullOrWhiteSpace($azdValue)) {
        return $azdValue
    }

    return "$AppName-$AzdEnvironmentName-rg".ToLowerInvariant()
}

function Resolve-AppServiceName {
    param([string]$RequestedAppServiceName)

    if (-not [string]::IsNullOrWhiteSpace($RequestedAppServiceName)) {
        return $RequestedAppServiceName.Trim()
    }

    $azdValue = Get-AzdEnvironmentValue -Name "var_webService"
    if (-not [string]::IsNullOrWhiteSpace($azdValue)) {
        return $azdValue
    }

    return "$AppName-$AzdEnvironmentName-app".ToLowerInvariant()
}

function Get-AppServiceDomainSuffix {
    $suffix = az cloud show --query "suffixes.appServiceDomain" -o tsv 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($suffix)) {
        return $suffix.Trim().TrimStart('.')
    }

    return "azurewebsites.net"
}

function Resolve-SimpleChatBaseUrl {
    param([string]$RequestedBaseUrl)

    if (-not [string]::IsNullOrWhiteSpace($RequestedBaseUrl)) {
        return $RequestedBaseUrl.TrimEnd('/')
    }

    $suffix = Get-AppServiceDomainSuffix
    $hostName = ("{0}-{1}-app.{2}" -f $AppName, $AzdEnvironmentName, $suffix).ToLowerInvariant()
    return "https://$hostName"
}

function Get-SafeFederatedCredentialName {
    param(
        [string]$Repository,
        [string]$EnvironmentName
    )

    $safeName = ("github-$Repository-$EnvironmentName" -replace "[^A-Za-z0-9_-]", "-").Trim('-')
    if ($safeName.Length -gt 120) {
        return $safeName.Substring(0, 120).Trim('-')
    }

    return $safeName
}

function Initialize-CiApplication {
    param(
        [string]$DisplayName,
        [string]$Repository,
        [string]$EnvironmentName
    )

    $existingApp = Invoke-AzureCliJson -Description "Checking GitHub Actions app registration '$DisplayName'" -Command {
        az ad app list --display-name $DisplayName --query "[0]" -o json
    }

    if ($null -eq $existingApp) {
        $existingApp = Invoke-AzureCliJson -Description "Creating GitHub Actions app registration '$DisplayName'" -Command {
            az ad app create --display-name $DisplayName --query "{appId:appId,id:id,displayName:displayName}" -o json
        }
    }
    else {
        Write-SuccessMessage "App registration already exists: $($existingApp.appId)"
    }

    $appId = $existingApp.appId
    $appObjectId = $existingApp.id

    $existingServicePrincipal = Invoke-AzureCliJson -Description "Checking service principal for '$appId'" -Command {
        az ad sp list --filter "appId eq '$appId'" --query "[0]" -o json
    }

    if ($null -eq $existingServicePrincipal) {
        $existingServicePrincipal = Invoke-AzureCliJson -Description "Creating service principal for '$appId'" -Command {
            az ad sp create --id $appId --query "{id:id,appId:appId,displayName:displayName}" -o json
        }
    }
    else {
        Write-SuccessMessage "Service principal already exists: $($existingServicePrincipal.id)"
    }

    $credentialName = Get-SafeFederatedCredentialName -Repository $Repository -EnvironmentName $EnvironmentName
    $subject = "repo:${Repository}:environment:${EnvironmentName}"
    $existingCredential = Invoke-AzureCliJson -Description "Checking federated credential '$credentialName'" -Command {
        az ad app federated-credential list --id $appId --query "[?name=='$credentialName'] | [0]" -o json
    }

    if ($null -ne $existingCredential -and $ForceFederatedCredentialUpdate) {
        Invoke-AzureCliText -Description "Deleting existing federated credential '$credentialName'" -Command {
            az ad app federated-credential delete --id $appId --federated-credential-id $credentialName --only-show-errors
        } | Out-Null
        $existingCredential = $null
    }

    if ($null -eq $existingCredential) {
        $credentialPayload = [ordered]@{
            name = $credentialName
            issuer = "https://token.actions.githubusercontent.com"
            subject = $subject
            audiences = @("api://AzureADTokenExchange")
            description = "GitHub Actions OIDC for $Repository environment $EnvironmentName"
        }

        $tempCredentialFile = New-TemporaryFile
        try {
            $credentialPayload | ConvertTo-Json -Depth 5 | Set-Content -Path $tempCredentialFile -Encoding utf8
            Invoke-AzureCliJson -Description "Creating federated credential '$credentialName'" -Command {
                az ad app federated-credential create --id $appId --parameters $tempCredentialFile --query "{name:name,subject:subject}" -o json
            } | Out-Null
        }
        finally {
            Remove-Item -Path $tempCredentialFile -Force -ErrorAction SilentlyContinue
        }
    }
    else {
        Write-SuccessMessage "Federated credential already exists for subject '$subject'"
    }

    return [PSCustomObject]@{
        ClientId = $appId
        AppObjectId = $appObjectId
        ServicePrincipalObjectId = $existingServicePrincipal.id
        FederatedCredentialSubject = $subject
    }
}

function Set-CiRoleAssignment {
    param(
        [string]$PrincipalObjectId,
        [string]$RoleName,
        [string]$Scope
    )

    $existingAssignment = Invoke-AzureCliJson -Description "Checking '$RoleName' role assignment at '$Scope'" -Command {
        az role assignment list --assignee-object-id $PrincipalObjectId --role $RoleName --scope $Scope --query "[0]" -o json
    }

    if ($null -ne $existingAssignment) {
        Write-SuccessMessage "Role assignment already exists: $RoleName"
        return
    }

    Invoke-AzureCliJson -Description "Assigning '$RoleName' at '$Scope'" -Command {
        az role assignment create --assignee-object-id $PrincipalObjectId --assignee-principal-type ServicePrincipal --role $RoleName --scope $Scope --query "{id:id,roleDefinitionName:roleDefinitionName}" -o json
    } | Out-Null
}

function Get-AzureManagementEndpoint {
    $endpoint = az cloud show --query "endpoints.resourceManager" -o tsv 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($endpoint)) {
        return $endpoint.TrimEnd('/')
    }

    return "https://management.azure.com"
}

function Set-PlaywrightWorkspace {
    param(
        [string]$SubscriptionId,
        [string]$ResourceGroupName,
        [string]$WorkspaceName,
        [string]$Location
    )

    $resourceManagerEndpoint = Get-AzureManagementEndpoint
    $workspaceUrl = "$resourceManagerEndpoint/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroupName/providers/Microsoft.LoadTestService/playwrightWorkspaces/$WorkspaceName`?api-version=2025-09-01"
    $workspacePayload = [ordered]@{
        location = $Location
        tags = [ordered]@{
            app = $AppName
            environment = $AzdEnvironmentName
            purpose = "ui-tests"
        }
        properties = @{}
    }

    $tempBody = New-TemporaryFile
    try {
        $workspacePayload | ConvertTo-Json -Depth 5 -Compress | Set-Content -Path $tempBody -Encoding utf8
        $workspace = Invoke-AzureCliJson -Description "Creating or updating Playwright workspace '$WorkspaceName'" -Command {
            az rest --method put --url $workspaceUrl --headers "Content-Type=application/json" --body "@$tempBody" -o json
        }
    }
    finally {
        Remove-Item -Path $tempBody -Force -ErrorAction SilentlyContinue
    }

    if ($null -eq $workspace -or [string]::IsNullOrWhiteSpace($workspace.properties.dataplaneUri)) {
        throw "Playwright workspace '$WorkspaceName' did not return a service endpoint."
    }

    return [PSCustomObject]@{
        Name = $workspace.name
        ResourceId = $workspace.id
        ServiceUrl = $workspace.properties.dataplaneUri
        WorkspaceId = $workspace.properties.workspaceId
        ProvisioningState = $workspace.properties.provisioningState
    }
}

function Get-GraphResourceUrl {
    $graphResource = az cloud show --query "endpoints.microsoftGraphResourceId" -o tsv 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($graphResource)) {
        return $graphResource.TrimEnd('/')
    }

    return "https://graph.microsoft.com"
}

function Set-EnterpriseAppAssignment {
    param(
        [string]$EnterpriseClientId,
        [string]$PrincipalObjectId,
        [string]$AppRoleValue
    )

    if ([string]::IsNullOrWhiteSpace($EnterpriseClientId) -or [string]::IsNullOrWhiteSpace($PrincipalObjectId)) {
        return
    }

    $enterpriseServicePrincipal = Invoke-AzureCliJson -Description "Resolving SimpleChat Enterprise App service principal" -Command {
        az ad sp show --id $EnterpriseClientId --query "{id:id,appId:appId,displayName:displayName,appRoles:appRoles}" -o json
    }

    $appRoleId = "00000000-0000-0000-0000-000000000000"
    $matchingRole = $enterpriseServicePrincipal.appRoles | Where-Object { $_.value -eq $AppRoleValue -and $_.isEnabled -eq $true } | Select-Object -First 1
    if ($null -ne $matchingRole) {
        $appRoleId = $matchingRole.id
    }
    else {
        Write-WarningMessage "App role '$AppRoleValue' was not found. Assigning the default access role."
    }

    $graphResource = Get-GraphResourceUrl
    $assignmentsUrl = "$graphResource/v1.0/servicePrincipals/$($enterpriseServicePrincipal.id)/appRoleAssignedTo"
    $assignments = Invoke-AzureCliJson -Description "Checking existing Enterprise App assignments" -Command {
        az rest --method get --url $assignmentsUrl --query "value" -o json
    }

    $existingAssignment = $assignments | Where-Object { $_.principalId -eq $PrincipalObjectId -and $_.appRoleId -eq $appRoleId } | Select-Object -First 1
    if ($null -ne $existingAssignment) {
        Write-SuccessMessage "UI test principal is already assigned to the Enterprise App role '$AppRoleValue'."
        return
    }

    $assignmentPayload = [ordered]@{
        principalId = $PrincipalObjectId
        resourceId = $enterpriseServicePrincipal.id
        appRoleId = $appRoleId
    } | ConvertTo-Json

    $tempBody = New-TemporaryFile
    try {
        $assignmentPayload | Set-Content -Path $tempBody -Encoding utf8
        Invoke-AzureCliJson -Description "Assigning Enterprise App role '$AppRoleValue'" -Command {
            az rest --method post --url $assignmentsUrl --headers "Content-Type=application/json" --body "@$tempBody" -o json
        } | Out-Null
    }
    finally {
        Remove-Item -Path $tempBody -Force -ErrorAction SilentlyContinue
    }
}

function Set-EnterpriseAppRoleApplicationMemberType {
    param(
        [string]$EnterpriseClientId,
        [string]$AppRoleValue
    )

    if ([string]::IsNullOrWhiteSpace($EnterpriseClientId)) {
        return
    }

    $enterpriseApp = Invoke-AzureCliJson -Description "Resolving SimpleChat app registration roles" -Command {
        az ad app show --id $EnterpriseClientId --query "{id:id,appId:appId,appRoles:appRoles}" -o json
    }

    $roles = @($enterpriseApp.appRoles)
    $matchingRole = $roles | Where-Object { $_.value -eq $AppRoleValue -and $_.isEnabled -eq $true } | Select-Object -First 1
    if ($null -eq $matchingRole) {
        throw "App role '$AppRoleValue' was not found on Enterprise App client ID '$EnterpriseClientId'."
    }

    $memberTypes = @($matchingRole.allowedMemberTypes)
    if ($memberTypes -contains "Application") {
        Write-SuccessMessage "App role '$AppRoleValue' already allows application assignments."
        return
    }

    $matchingRole.allowedMemberTypes = @($memberTypes + "Application" | Select-Object -Unique)

    $tempBody = New-TemporaryFile
    try {
        $graphResource = Get-GraphResourceUrl
        $appUrl = "$graphResource/v1.0/applications/$($enterpriseApp.id)"
        [ordered]@{ appRoles = $roles } | ConvertTo-Json -Depth 10 | Set-Content -Path $tempBody -Encoding utf8
        Invoke-AzureCliJson -Description "Allowing application assignments for Enterprise App role '$AppRoleValue'" -Command {
            az rest --method patch --url $appUrl --headers "Content-Type=application/json" --body "@$tempBody" -o json
        } | Out-Null
    }
    finally {
        Remove-Item -Path $tempBody -Force -ErrorAction SilentlyContinue
    }
}

function Set-EnterpriseAppIdentifierUri {
    param([string]$EnterpriseClientId)

    if ([string]::IsNullOrWhiteSpace($EnterpriseClientId)) {
        return
    }

    $enterpriseApp = Invoke-AzureCliJson -Description "Resolving SimpleChat app registration identifier URI" -Command {
        az ad app show --id $EnterpriseClientId --query "{id:id,appId:appId,identifierUris:identifierUris}" -o json
    }

    $expectedIdentifierUri = "api://$EnterpriseClientId"
    $identifierUris = @($enterpriseApp.identifierUris)
    if ($identifierUris -contains $expectedIdentifierUri) {
        Write-SuccessMessage "Enterprise App identifier URI already exists: $expectedIdentifierUri"
        return
    }

    $updatedIdentifierUris = @($identifierUris + $expectedIdentifierUri | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    $graphResource = Get-GraphResourceUrl
    $appUrl = "$graphResource/v1.0/applications/$($enterpriseApp.id)"
    $tempBody = New-TemporaryFile
    try {
        [ordered]@{ identifierUris = $updatedIdentifierUris } | ConvertTo-Json -Depth 5 | Set-Content -Path $tempBody -Encoding utf8
        Invoke-AzureCliJson -Description "Publishing Enterprise App identifier URI '$expectedIdentifierUri'" -Command {
            az rest --method patch --url $appUrl --headers "Content-Type=application/json" --body "@$tempBody" -o json
        } | Out-Null
    }
    finally {
        Remove-Item -Path $tempBody -Force -ErrorAction SilentlyContinue
    }
}

function Set-AppServiceCiBearerSessionAuth {
    param(
        [string]$SubscriptionId,
        [string]$ResourceGroupName,
        [string]$WebAppName,
        [string]$AllowedClientId,
        [string]$RequiredRole
    )

    Invoke-AzureCliJson -Description "Enabling CI bearer session auth on App Service '$WebAppName'" -Command {
        az webapp config appsettings set `
            --subscription $SubscriptionId `
            --resource-group $ResourceGroupName `
            --name $WebAppName `
            --settings `
                ENABLE_CI_BEARER_SESSION_AUTH=true `
                CI_BEARER_SESSION_ALLOWED_APP_IDS=$AllowedClientId `
                CI_BEARER_SESSION_REQUIRED_ROLE=$RequiredRole `
            --query "{name:name}" `
            -o json
    } | Out-Null
}

function Convert-TextToBase64Secret {
    param(
        [string]$Name,
        [string]$Text
    )

    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($Text))
    if ($encoded.Length -gt $GitHubSecretLimit) {
        throw "Secret '$Name' is $($encoded.Length) characters after base64 encoding, which exceeds the GitHub secret size limit of $GitHubSecretLimit. Store it in Key Vault or reduce the file size."
    }

    return $encoded
}

function Convert-FileToBase64Secret {
    param(
        [string]$Name,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    $resolvedPath = Resolve-Path -Path $Path -ErrorAction Stop
    $encoded = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($resolvedPath))
    if ($encoded.Length -gt $GitHubSecretLimit) {
        throw "Secret '$Name' is $($encoded.Length) characters after base64 encoding, which exceeds the GitHub secret size limit of $GitHubSecretLimit. Store it in Key Vault or reduce the file size."
    }

    return $encoded
}

function Get-AzdEnvironmentFileSecret {
    param([string]$Path)

    if (-not [string]::IsNullOrWhiteSpace($Path)) {
        return Convert-FileToBase64Secret -Name "AZD_ENV_FILE_B64" -Path $Path
    }

    if (-not (Test-CommandAvailable -CommandName "azd")) {
        throw "azd is required to export environment values when AzdEnvironmentValuesPath is not provided."
    }

    Write-InfoMessage "Exporting azd environment values for '$AzdEnvironmentName'"
    $output = azd env get-values -e $AzdEnvironmentName --cwd $PSScriptRoot 2>&1
    $exitCode = $LASTEXITCODE
    $outputText = Get-CommandOutputText -CommandOutput $output

    if ($exitCode -ne 0 -or [string]::IsNullOrWhiteSpace($outputText)) {
        throw "Failed to export azd environment '$AzdEnvironmentName'. Run 'azd env new $AzdEnvironmentName' and configure it before bootstrapping GitHub Actions. azd returned: $outputText"
    }

    return Convert-TextToBase64Secret -Name "AZD_ENV_FILE_B64" -Text ($outputText + [Environment]::NewLine)
}

function Test-GitHubCliAuthenticated {
    if (-not (Test-CommandAvailable -CommandName "gh")) {
        throw "GitHub CLI is not installed. Install GitHub CLI and run 'gh auth login', or rerun this script with -SkipGitHubConfiguration."
    }

    $status = gh auth status 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI is not authenticated. Run 'gh auth login'. Output: $(Get-CommandOutputText -CommandOutput $status)"
    }
}

function Set-GitHubEnvironment {
    param(
        [string]$Repository,
        [string]$EnvironmentName
    )

    Write-InfoMessage "Ensuring GitHub Environment '$EnvironmentName' exists in '$Repository'"
    gh api --method PUT "repos/$Repository/environments/$EnvironmentName" --silent
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create or update GitHub Environment '$EnvironmentName'."
    }
}

function Set-GitHubVariable {
    param(
        [string]$Repository,
        [string]$EnvironmentName,
        [string]$Name,
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return
    }

    Write-InfoMessage "Setting GitHub Environment variable '$Name'"
    gh variable set $Name --repo $Repository --env $EnvironmentName --body $Value | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to set GitHub variable '$Name'."
    }
}

function Set-GitHubSecret {
    param(
        [string]$Repository,
        [string]$EnvironmentName,
        [string]$Name,
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return
    }

    Write-InfoMessage "Setting GitHub Environment secret '$Name'"
    $tempSecretFile = New-TemporaryFile
    try {
        Set-Content -Path $tempSecretFile -Value $Value -NoNewline -Encoding utf8
        Get-Content -Path $tempSecretFile -Raw | gh secret set $Name --repo $Repository --env $EnvironmentName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to set GitHub secret '$Name'."
        }
    }
    finally {
        Remove-Item -Path $tempSecretFile -Force -ErrorAction SilentlyContinue
    }
}

try {
    $resolvedRepository = Resolve-GitHubRepository -RequestedRepository $GitHubRepository
    $account = Get-CurrentAzureAccount
    $resolvedLocation = Resolve-AzureLocation -RequestedLocation $AzureLocation
    $resolvedBaseUrl = Resolve-SimpleChatBaseUrl -RequestedBaseUrl $SimpleChatUiBaseUrl
    $resolvedEnterpriseAppClientId = Resolve-EnterpriseAppClientId -RequestedClientId $EnterpriseAppClientId
    $resolvedAppServiceResourceGroupName = Resolve-AppServiceResourceGroupName -RequestedResourceGroupName $AppServiceResourceGroupName
    $resolvedAppServiceName = Resolve-AppServiceName -RequestedAppServiceName $AppServiceName
    $resolvedAppRegistrationName = if ([string]::IsNullOrWhiteSpace($CiAppRegistrationName)) {
        "$AppName-$AzdEnvironmentName-github-actions".ToLowerInvariant()
    }
    else {
        $CiAppRegistrationName
    }

    $resolvedRoleAssignmentScope = if ([string]::IsNullOrWhiteSpace($RoleAssignmentScope)) {
        "/subscriptions/$($account.subscriptionId)"
    }
    else {
        $RoleAssignmentScope.Trim()
    }

    $resolvedPlaywrightWorkspaceName = if ([string]::IsNullOrWhiteSpace($PlaywrightWorkspaceName)) {
        "$AppName-$AzdEnvironmentName-pw".ToLowerInvariant()
    }
    else {
        $PlaywrightWorkspaceName.Trim()
    }

    $resolvedPlaywrightWorkspaceResourceGroupName = if ([string]::IsNullOrWhiteSpace($PlaywrightWorkspaceResourceGroupName)) {
        "$AppName-$AzdEnvironmentName-rg".ToLowerInvariant()
    }
    else {
        $PlaywrightWorkspaceResourceGroupName.Trim()
    }

    Write-Host ""
    Write-InfoMessage "Preparing GitHub Actions staging CI/CD bootstrap"
    Write-Host "Repository:             $resolvedRepository"
    Write-Host "GitHub Environment:     $GitHubEnvironment"
    Write-Host "azd Environment:        $AzdEnvironmentName"
    Write-Host "App Name:               $AppName"
    Write-Host "Azure Location:         $resolvedLocation"
    Write-Host "Subscription:           $($account.subscriptionId)"
    Write-Host "Tenant:                 $($account.tenantId)"
    Write-Host "OIDC App Registration:  $resolvedAppRegistrationName"
    Write-Host "RBAC Scope:             $resolvedRoleAssignmentScope"
    Write-Host "UI Base URL:            $resolvedBaseUrl"
    Write-Host "Playwright Workspace:   $resolvedPlaywrightWorkspaceName"
    Write-Host "App Service:            $resolvedAppServiceName"
    Write-Host "Enterprise App Client:  $resolvedEnterpriseAppClientId"
    Write-Host ""

    $ciApplication = Initialize-CiApplication -DisplayName $resolvedAppRegistrationName -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment

    if (-not $SkipCiBearerSessionAuth) {
        if ([string]::IsNullOrWhiteSpace($resolvedEnterpriseAppClientId)) {
            Write-WarningMessage "Skipping CI bearer session auth because EnterpriseAppClientId could not be resolved."
        }
        else {
            Set-EnterpriseAppIdentifierUri -EnterpriseClientId $resolvedEnterpriseAppClientId
            Set-EnterpriseAppRoleApplicationMemberType -EnterpriseClientId $resolvedEnterpriseAppClientId -AppRoleValue "Admin"
            Set-EnterpriseAppAssignment -EnterpriseClientId $resolvedEnterpriseAppClientId -PrincipalObjectId $ciApplication.ServicePrincipalObjectId -AppRoleValue "Admin"
            Set-AppServiceCiBearerSessionAuth -SubscriptionId $account.subscriptionId -ResourceGroupName $resolvedAppServiceResourceGroupName -WebAppName $resolvedAppServiceName -AllowedClientId $ciApplication.ClientId -RequiredRole "Admin"
        }
    }
    else {
        Write-WarningMessage "Skipping CI bearer session auth. The workflow will need a Playwright storage state secret for authenticated UI tests."
    }

    $playwrightWorkspace = $null
    if (-not $SkipPlaywrightWorkspace) {
        $playwrightWorkspace = Set-PlaywrightWorkspace -SubscriptionId $account.subscriptionId -ResourceGroupName $resolvedPlaywrightWorkspaceResourceGroupName -WorkspaceName $resolvedPlaywrightWorkspaceName -Location $PlaywrightWorkspaceLocation
        Set-CiRoleAssignment -PrincipalObjectId $ciApplication.ServicePrincipalObjectId -RoleName "Playwright Workspace Contributor" -Scope $playwrightWorkspace.ResourceId
    }
    else {
        Write-WarningMessage "Skipping Microsoft Playwright Workspaces setup. The workflow will need PLAYWRIGHT_SERVICE_URL if you want Azure-hosted browsers."
    }

    if (-not $SkipRoleAssignments) {
        Write-WarningMessage "Assigning Contributor and User Access Administrator to the CI identity at '$resolvedRoleAssignmentScope'. This is required for subscription-scoped azd up with role assignments. Use -RoleAssignmentScope to narrow it for deploy-only scenarios."
        Set-CiRoleAssignment -PrincipalObjectId $ciApplication.ServicePrincipalObjectId -RoleName "Contributor" -Scope $resolvedRoleAssignmentScope
        Set-CiRoleAssignment -PrincipalObjectId $ciApplication.ServicePrincipalObjectId -RoleName "User Access Administrator" -Scope $resolvedRoleAssignmentScope
    }
    else {
        Write-WarningMessage "Skipping Azure role assignments. The workflow identity must already have enough access for azd up/deploy."
    }

    Set-EnterpriseAppAssignment -EnterpriseClientId $resolvedEnterpriseAppClientId -PrincipalObjectId $UiTestPrincipalObjectId -AppRoleValue $UiTestAppRoleValue

    $azdEnvFileSecret = $null
    $uiStorageStateSecret = $null
    $adminStorageStateSecret = $null

    if (-not $SkipGitHubConfiguration) {
        $azdEnvFileSecret = Get-AzdEnvironmentFileSecret -Path $AzdEnvironmentValuesPath
        $uiStorageStateSecret = Convert-FileToBase64Secret -Name "SIMPLECHAT_UI_STORAGE_STATE_B64" -Path $UiStorageStatePath
        $adminStorageStateSecret = Convert-FileToBase64Secret -Name "SIMPLECHAT_UI_ADMIN_STORAGE_STATE_B64" -Path $AdminUiStorageStatePath

        Test-GitHubCliAuthenticated
        Set-GitHubEnvironment -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment

        Set-GitHubVariable -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "AZURE_CLIENT_ID" -Value $ciApplication.ClientId
        Set-GitHubVariable -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "AZURE_TENANT_ID" -Value $account.tenantId
        Set-GitHubVariable -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "AZURE_SUBSCRIPTION_ID" -Value $account.subscriptionId
        Set-GitHubVariable -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "AZURE_LOCATION" -Value $resolvedLocation
        Set-GitHubVariable -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "AZURE_ENV_NAME" -Value $AzdEnvironmentName
        Set-GitHubVariable -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "DEPLOYMENT_APPNAME" -Value $AppName
        Set-GitHubVariable -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "SIMPLECHAT_UI_BASE_URL" -Value $resolvedBaseUrl
        if (-not [string]::IsNullOrWhiteSpace($resolvedEnterpriseAppClientId) -and -not $SkipCiBearerSessionAuth) {
            Set-GitHubVariable -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "SIMPLECHAT_UI_AUTH_RESOURCE" -Value "api://$resolvedEnterpriseAppClientId"
        }

        if ($null -ne $playwrightWorkspace) {
            Set-GitHubVariable -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "PLAYWRIGHT_SERVICE_URL" -Value $playwrightWorkspace.ServiceUrl
            Set-GitHubVariable -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "PLAYWRIGHT_WORKSPACE_NAME" -Value $playwrightWorkspace.Name
            Set-GitHubVariable -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "PLAYWRIGHT_WORKSPACE_RESOURCE_ID" -Value $playwrightWorkspace.ResourceId
        }

        Set-GitHubSecret -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "AZD_ENV_FILE_B64" -Value $azdEnvFileSecret
        Set-GitHubSecret -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "SIMPLECHAT_UI_STORAGE_STATE_B64" -Value $uiStorageStateSecret
        Set-GitHubSecret -Repository $resolvedRepository -EnvironmentName $GitHubEnvironment -Name "SIMPLECHAT_UI_ADMIN_STORAGE_STATE_B64" -Value $adminStorageStateSecret
    }
    else {
        Write-WarningMessage "Skipping GitHub configuration. Create the GitHub Environment '$GitHubEnvironment' and set the variables/secrets documented in STAGING_UI_CICD.md."
    }

    Write-Host ""
    Write-SuccessMessage "GitHub Actions staging bootstrap completed."
    Write-Host "OIDC Client ID: $($ciApplication.ClientId)"
    Write-Host "OIDC Subject:   $($ciApplication.FederatedCredentialSubject)"
    if (-not [string]::IsNullOrWhiteSpace($resolvedEnterpriseAppClientId) -and -not $SkipCiBearerSessionAuth) {
        Write-Host "UI Auth Resource: api://$resolvedEnterpriseAppClientId"
    }
    if ($null -ne $playwrightWorkspace) {
        Write-Host "Playwright URL: $($playwrightWorkspace.ServiceUrl)"
    }
    Write-Host ""
    Write-Host "Next steps:"
    Write-Host "  1. Confirm the GitHub Environment '$GitHubEnvironment' is restricted to trusted admins/branches."
    Write-Host "  2. Use SIMPLECHAT_UI_AUTH_RESOURCE for CI bearer auth, or refresh SIMPLECHAT_UI_STORAGE_STATE_B64 whenever browser-session auth is needed."
    Write-Host "  3. Push or dispatch the staging workflow after the new workflow file is merged."
}
catch {
    Write-ErrorMessage $_.Exception.Message
    exit 1
}
