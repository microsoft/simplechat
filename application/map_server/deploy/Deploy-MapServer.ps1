# Deploy-MapServer.ps1
#Requires -Version 7.0
<#
.SYNOPSIS
    Builds and deploys the SimpleChat map server to Azure Container Apps for a proof of concept.

.DESCRIPTION
    Uses the signed-in Azure CLI account. Safe to run again: existing resources are reused.
    1. Builds the image in Azure Container Registry from a staged context (only the map server and docker-customization).
    2. Creates the Cosmos DB database "mapserver" with containers "maps" (/map_id) and "map_links" (/scope_key).
    3. Creates a user-assigned managed identity and grants it AcrPull, Cosmos DB data access and, when a Maps
       account is given, Azure Maps Data Reader.
    4. Registers the map server API with the MapServer.ActOnBehalf app role and assigns that role to SimpleChat's
       managed identity. If the role can't be assigned, SimpleChat's identity is allowlisted by object ID instead.
    5. Creates or updates the container app and prints the values SimpleChat needs.

.EXAMPLE
    ./Deploy-MapServer.ps1 -ResourceGroup my-rg -RegistryName myacr -ContainerAppsEnvironment my-env `
        -CosmosAccountName my-cosmos -SimpleChatPrincipalId 00000000-0000-0000-0000-000000000000 -MapsAccountName my-maps
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $ResourceGroup,
    [Parameter(Mandatory)] [string] $RegistryName,
    [Parameter(Mandatory)] [string] $ContainerAppsEnvironment,
    [Parameter(Mandatory)] [string] $CosmosAccountName,
    [Parameter(Mandatory)] [ValidatePattern('^[0-9a-fA-F-]{36}$')] [string] $SimpleChatPrincipalId,
    [string] $RegistryResourceGroup = $ResourceGroup,
    [string] $CosmosResourceGroup = $ResourceGroup,
    [string] $MapsAccountName = '',
    [string] $MapsResourceGroup = $ResourceGroup,
    [ValidatePattern('^[a-z][a-z0-9-]{1,30}[a-z0-9]$')] [string] $ContainerAppName = 'simplechat-map-server',
    [string] $ImageTag = (Get-Date -Format 'yyyyMMdd-HHmmss'),
    [string] $ApiAppId = '',
    [ValidateSet('external', 'internal')] [string] $Ingress = 'external',
    [switch] $SkipBuild,
    [string] $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
)

$ErrorActionPreference = 'Stop'
$RoleValue = 'MapServer.ActOnBehalf'
$CosmosDataContributorRole = '00000000-0000-0000-0000-000000000002'
$ImageName = 'simplechat-map-server'
$AzErrorFile = New-TemporaryFile

function Invoke-AzCommand {
    param([Parameter(Mandatory)] [string[]] $Arguments, [switch] $AllowFailure)
    $output = & az @Arguments 2>$AzErrorFile.FullName
    if ($LASTEXITCODE -ne 0) {
        if ($AllowFailure) { return $null }
        $details = (Get-Content -Raw -Path $AzErrorFile.FullName -ErrorAction SilentlyContinue)
        throw "az $($Arguments[0]) $($Arguments[1]) failed: $details"
    }
    return (($output | Out-String).Trim())
}

function Invoke-AzJson {
    param([Parameter(Mandatory)] [string[]] $Arguments, [switch] $AllowFailure)
    # az is a .cmd on Windows, so JMESPath filters with parentheses get mangled; filter JSON in PowerShell instead.
    $raw = Invoke-AzCommand -Arguments ($Arguments + @('-o', 'json')) -AllowFailure:$AllowFailure
    if (-not $raw) { return $null }
    return ($raw | ConvertFrom-Json)
}

function Write-Step {
    param([string] $Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-ImageBuild {
    param([string] $Image, [string] $SourceRoot)
    $staging = Join-Path ([System.IO.Path]::GetTempPath()) "map-server-build-$([guid]::NewGuid().ToString('N'))"
    try {
        New-Item -ItemType Directory -Path (Join-Path $staging 'application') | Out-Null
        Copy-Item -Recurse -Path (Join-Path $SourceRoot 'application/map_server') -Destination (Join-Path $staging 'application/map_server')
        Copy-Item -Recurse -Path (Join-Path $SourceRoot 'docker-customization') -Destination (Join-Path $staging 'docker-customization')
        Get-ChildItem -Path $staging -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force

        $queued = & az acr build --registry $RegistryName --resource-group $RegistryResourceGroup --image $Image `
            --file (Join-Path $staging 'application/map_server/Dockerfile') --no-wait $staging 2>&1 | Out-String
        if ($queued -notmatch 'Queued a build with ID:\s*(\S+)') {
            throw "The image build wasn't queued: $queued"
        }
        $runId = $Matches[1]
        Write-Host "    build $runId queued"

        $deadline = (Get-Date).AddMinutes(30)
        $unreadable = 0
        while ($true) {
            Start-Sleep -Seconds 10
            $status = Invoke-AzCommand -AllowFailure -Arguments @(
                'acr', 'task', 'show-run', '--registry', $RegistryName, '--resource-group', $RegistryResourceGroup,
                '--run-id', $runId, '--query', 'status', '-o', 'tsv')
            if (-not $status) {
                $unreadable++
                if ($unreadable -gt 15) { throw "Couldn't read the status of build $runId." }
            }
            elseif ($status -eq 'Succeeded') { break }
            elseif ($status -in @('Failed', 'Canceled', 'Error', 'Timeout')) {
                throw "Build $runId ended with status $status. See: az acr task logs --registry $RegistryName --run-id $runId"
            }
            if ((Get-Date) -gt $deadline) { throw "Build $runId didn't finish within 30 minutes." }
        }
    }
    finally {
        Remove-Item -Recurse -Force -Path $staging -ErrorAction SilentlyContinue
    }
}

function Grant-AzureRole {
    param([string] $PrincipalId, [string] $Role, [string] $Scope)
    # Match by object ID: --assignee looks the principal up in Entra ID, which lags for a new identity.
    $existing = @(Invoke-AzJson -Arguments @('role', 'assignment', 'list', '--role', $Role, '--scope', $Scope) |
            Where-Object { $_.principalId -eq $PrincipalId })
    if ($existing.Count -gt 0) { return $false }
    Invoke-AzCommand -Arguments @(
        'role', 'assignment', 'create', '--assignee-object-id', $PrincipalId, '--assignee-principal-type', 'ServicePrincipal',
        '--role', $Role, '--scope', $Scope) | Out-Null
    return $true
}

try {
    Write-Step 'Checking the Azure CLI sign-in'
    $tenantId = Invoke-AzCommand -Arguments @('account', 'show', '--query', 'tenantId', '-o', 'tsv')
    if (-not (Invoke-AzCommand -AllowFailure -Arguments @('extension', 'show', '--name', 'containerapp', '--query', 'name', '-o', 'tsv'))) {
        Invoke-AzCommand -Arguments @('extension', 'add', '--name', 'containerapp', '--only-show-errors') | Out-Null
    }
    $loginServer = Invoke-AzCommand -Arguments @('acr', 'show', '-n', $RegistryName, '-g', $RegistryResourceGroup, '--query', 'loginServer', '-o', 'tsv')
    $registryId = Invoke-AzCommand -Arguments @('acr', 'show', '-n', $RegistryName, '-g', $RegistryResourceGroup, '--query', 'id', '-o', 'tsv')
    $image = "$ImageName`:$ImageTag"

    if ($SkipBuild) {
        Write-Step "Skipping the image build; using $loginServer/$image"
    }
    else {
        Write-Step "Building $image in $RegistryName"
        Invoke-ImageBuild -Image $image -SourceRoot $RepoRoot
    }

    Write-Step 'Preparing Cosmos DB'
    $cosmosAccount = Invoke-AzJson -Arguments @('cosmosdb', 'show', '-n', $CosmosAccountName, '-g', $CosmosResourceGroup)
    $cosmosEndpoint = $cosmosAccount.documentEndpoint
    $serverless = @($cosmosAccount.capabilities | Where-Object { $_.name -eq 'EnableServerless' }).Count -gt 0
    if (-not (Invoke-AzCommand -AllowFailure -Arguments @('cosmosdb', 'sql', 'database', 'show', '-a', $CosmosAccountName, '-g', $CosmosResourceGroup, '-n', 'mapserver', '--query', 'name', '-o', 'tsv'))) {
        Invoke-AzCommand -Arguments @('cosmosdb', 'sql', 'database', 'create', '-a', $CosmosAccountName, '-g', $CosmosResourceGroup, '-n', 'mapserver') | Out-Null
    }
    foreach ($container in @(@{ Name = 'maps'; Key = '/map_id' }, @{ Name = 'map_links'; Key = '/scope_key' })) {
        $exists = Invoke-AzCommand -AllowFailure -Arguments @(
            'cosmosdb', 'sql', 'container', 'show', '-a', $CosmosAccountName, '-g', $CosmosResourceGroup, '-d', 'mapserver',
            '-n', $container.Name, '--query', 'name', '-o', 'tsv')
        if (-not $exists) {
            $arguments = @('cosmosdb', 'sql', 'container', 'create', '-a', $CosmosAccountName, '-g', $CosmosResourceGroup,
                '-d', 'mapserver', '-n', $container.Name, '-p', $container.Key)
            if (-not $serverless) { $arguments += @('--max-throughput', '1000') }
            Invoke-AzCommand -Arguments $arguments | Out-Null
        }
    }

    Write-Step 'Preparing the managed identity'
    $identityName = "$ContainerAppName-id"
    $identityJson = Invoke-AzCommand -AllowFailure -Arguments @('identity', 'show', '-n', $identityName, '-g', $ResourceGroup, '-o', 'json')
    if (-not $identityJson) {
        $identityJson = Invoke-AzCommand -Arguments @('identity', 'create', '-n', $identityName, '-g', $ResourceGroup, '-o', 'json')
    }
    $identity = $identityJson | ConvertFrom-Json
    $rolesGranted = Grant-AzureRole -PrincipalId $identity.principalId -Role 'AcrPull' -Scope $registryId

    $cosmosAssignments = @(Invoke-AzJson -Arguments @('cosmosdb', 'sql', 'role', 'assignment', 'list', '-a', $CosmosAccountName, '-g', $CosmosResourceGroup))
    $cosmosAssigned = @($cosmosAssignments | Where-Object {
            $_.principalId -eq $identity.principalId -and $_.roleDefinitionId.EndsWith($CosmosDataContributorRole)
        }).Count -gt 0
    if (-not $cosmosAssigned) {
        Invoke-AzCommand -Arguments @(
            'cosmosdb', 'sql', 'role', 'assignment', 'create', '-a', $CosmosAccountName, '-g', $CosmosResourceGroup,
            '--role-definition-id', $CosmosDataContributorRole, '--principal-id', $identity.principalId, '--scope', '/dbs/mapserver') | Out-Null
    }

    $mapsClientId = ''
    if ($MapsAccountName) {
        Write-Step 'Granting Azure Maps access'
        $mapsAccount = Invoke-AzCommand -Arguments @('maps', 'account', 'show', '-n', $MapsAccountName, '-g', $MapsResourceGroup, '-o', 'json') | ConvertFrom-Json
        $mapsClientId = $mapsAccount.properties.uniqueId
        $rolesGranted = (Grant-AzureRole -PrincipalId $identity.principalId -Role 'Azure Maps Data Reader' -Scope $mapsAccount.id) -or $rolesGranted
    }
    else {
        Write-Host '    no Maps account given; the map viewer will show a black background'
    }

    Write-Step 'Registering the map server API'
    if (-not $ApiAppId) {
        $roleFile = New-TemporaryFile
        @(@{
                allowedMemberTypes = @('Application')
                description        = 'Act on behalf of people when reading and writing maps.'
                displayName        = 'Act on behalf of people'
                id                 = [guid]::NewGuid().ToString()
                isEnabled          = $true
                value              = $RoleValue
            }) | ConvertTo-Json -Depth 4 -AsArray | Set-Content -Path $roleFile.FullName -Encoding utf8
        $ApiAppId = Invoke-AzCommand -Arguments @(
            'ad', 'app', 'create', '--display-name', "SimpleChat map server ($ContainerAppName)", '--sign-in-audience', 'AzureADMyOrg',
            '--app-roles', "@$($roleFile.FullName)", '--query', 'appId', '-o', 'tsv')
        Remove-Item -Path $roleFile.FullName -Force
        Invoke-AzCommand -Arguments @('ad', 'app', 'update', '--id', $ApiAppId, '--identifier-uris', "api://$ApiAppId") | Out-Null
    }
    if (-not (Invoke-AzCommand -AllowFailure -Arguments @('ad', 'sp', 'show', '--id', $ApiAppId, '--query', 'id', '-o', 'tsv'))) {
        Invoke-AzCommand -Arguments @('ad', 'sp', 'create', '--id', $ApiAppId) | Out-Null
    }
    $apiPrincipal = Invoke-AzJson -Arguments @('ad', 'sp', 'show', '--id', $ApiAppId)
    $apiPrincipalId = $apiPrincipal.id
    $roleId = @($apiPrincipal.appRoles | Where-Object { $_.value -eq $RoleValue })[0].id
    if (-not $roleId) { throw "The map server API has no $RoleValue app role." }

    $assignmentsUri = "https://graph.microsoft.com/v1.0/servicePrincipals/$SimpleChatPrincipalId/appRoleAssignments"
    $existingGrants = Invoke-AzJson -AllowFailure -Arguments @('rest', '--method', 'GET', '--uri', $assignmentsUri)
    $assigned = if (@($existingGrants.value | Where-Object { $_.resourceId -eq $apiPrincipalId -and $_.appRoleId -eq $roleId }).Count -gt 0) { '1' } else { '0' }
    if ($assigned -ne '1') {
        $bodyFile = New-TemporaryFile
        @{ principalId = $SimpleChatPrincipalId; resourceId = $apiPrincipalId; appRoleId = $roleId } |
            ConvertTo-Json | Set-Content -Path $bodyFile.FullName -Encoding utf8
        $granted = Invoke-AzCommand -AllowFailure -Arguments @(
            'rest', '--method', 'POST', '--uri', $assignmentsUri, '--headers', 'Content-Type=application/json', '--body', "@$($bodyFile.FullName)")
        Remove-Item -Path $bodyFile.FullName -Force
        $assigned = if ($null -ne $granted) { '1' } else { '0' }
    }
    $allowedCallers = ''
    if ($assigned -ne '1') {
        Write-Warning "Couldn't assign $RoleValue to SimpleChat's identity. Allowlisting its object ID instead."
        $allowedCallers = $SimpleChatPrincipalId
    }

    Write-Step "Deploying the container app ($Ingress ingress)"
    $envVars = @(
        "MAP_SERVER_TENANT_ID=$tenantId",
        "MAP_SERVER_AUDIENCES=api://$ApiAppId,$ApiAppId",
        "MAP_SERVER_REQUIRED_ROLE=$RoleValue",
        "MAP_SERVER_STORE=cosmos",
        "MAP_SERVER_COSMOS_ENDPOINT=$cosmosEndpoint",
        "AZURE_CLIENT_ID=$($identity.clientId)"
    )
    if ($allowedCallers) { $envVars += "MAP_SERVER_ALLOWED_CALLER_IDS=$allowedCallers" }
    if ($mapsClientId) { $envVars += "AZURE_MAPS_CLIENT_ID=$mapsClientId" }

    $appExists = Invoke-AzCommand -AllowFailure -Arguments @('containerapp', 'show', '-n', $ContainerAppName, '-g', $ResourceGroup, '--query', 'name', '-o', 'tsv')
    if ($rolesGranted -and -not $appExists) {
        Write-Host '    waiting 60 seconds for the new role assignments to take effect'
        Start-Sleep -Seconds 60
    }
    if ($appExists) {
        Invoke-AzCommand -Arguments (@('containerapp', 'update', '-n', $ContainerAppName, '-g', $ResourceGroup,
                '--image', "$loginServer/$image", '--set-env-vars') + $envVars) | Out-Null
    }
    else {
        Invoke-AzCommand -Arguments (@('containerapp', 'create', '-n', $ContainerAppName, '-g', $ResourceGroup,
                '--environment', $ContainerAppsEnvironment, '--image', "$loginServer/$image",
                '--registry-server', $loginServer, '--registry-identity', $identity.id, '--user-assigned', $identity.id,
                '--target-port', '8080', '--ingress', $Ingress, '--min-replicas', '1', '--max-replicas', '2',
                '--cpu', '0.5', '--memory', '1.0Gi', '--env-vars') + $envVars) | Out-Null
    }
    $fqdn = Invoke-AzCommand -Arguments @('containerapp', 'show', '-n', $ContainerAppName, '-g', $ResourceGroup, '--query', 'properties.configuration.ingress.fqdn', '-o', 'tsv')

    Write-Step 'Done'
    Write-Host "    Map server URL:      https://$fqdn"
    Write-Host "    Token audience:      api://$ApiAppId"
    Write-Host "    Caller check:        $(if ($allowedCallers) { 'object ID allowlist' } else { "app role $RoleValue" })"
    Write-Host "    Health check:        https://$fqdn/healthz"
}
finally {
    Remove-Item -Path $AzErrorFile.FullName -Force -ErrorAction SilentlyContinue
}
