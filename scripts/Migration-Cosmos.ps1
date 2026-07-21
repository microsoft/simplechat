# Migration-Cosmos.ps1
#Requires -Version 7.0

[CmdletBinding()]
param(
    [string]$SourceCosmosAccount = "<source-cosmos-account>",

    [string]$SourceResourceGroup = "<source-resource-group> ",

    [string]$SourceSubscriptionId = "<source-subscription-id>",

    [string]$SourceDatabaseName = "SimpleChat",

    [string]$SourcePrimaryKey = "<source-primary-key>",

    [string]$DestinationCosmosAccount = "<destination-cosmos-account>",

    [string]$DestinationResourceGroup = "<destination-resource-group>",

    [string]$DestinationSubscriptionId = "<destination-subscription-id>",

    [string]$DestinationDatabaseName = "SimpleChat",

    [string]$DestinationPrimaryKey = "<destination-primary-key>",

    [AllowEmptyCollection()]
    [string[]]$Containers = @(),

    [bool]$DifferentialMigration = $true,

    [bool]$ShowProgress = $true,

    [ValidateRange(1, 100000)]
    [int]$ProgressUpdateInterval = 100,

    [ValidateRange(1, 1000)]
    [int]$PageSize = 100,

    [ValidateRange(1, 64)]
    [int]$MaxConcurrentDocuments = 100,

    [ValidateRange(1, 10)]
    [int]$MaxRetryCount = 5,

    [string]$CosmosApiVersion = "2020-07-15",

    [string]$ManagementApiVersion = "2025-04-15",

    [string]$CosmosDnsSuffix = "documents.azure.com",

    [string]$StateFilePath = "",

    [switch]$ResetState
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Migration-State.ps1")
$adminSettingsContainerName = "settings"
$adminSettingsDocumentId = "app_settings"

function Get-CosmosMigrationProgressPercent {
    param(
        [long]$ProcessedCount,
        [long]$TotalCount
    )

    if ($TotalCount -le 0) {
        return 100
    }

    return [int][Math]::Min(
        100,
        [Math]::Floor(([double]$ProcessedCount / [double]$TotalCount) * 100)
    )
}

function Write-CosmosMigrationProgress {
    param(
        [int]$Id,
        [int]$ParentId = -1,
        [string]$Activity,
        [string]$Status = "",
        [string]$CurrentOperation = "",
        [int]$PercentComplete = -1,
        [switch]$Completed
    )

    if (-not $ShowProgress) {
        return
    }

    $progressParameters = @{
        Id = $Id
        ParentId = $ParentId
        Activity = $Activity
    }

    if ($Completed) {
        $progressParameters.Completed = $true
    }
    else {
        $progressParameters.Status = $Status
        $progressParameters.PercentComplete = $PercentComplete
        if (-not [string]::IsNullOrWhiteSpace($CurrentOperation)) {
            $progressParameters.CurrentOperation = $CurrentOperation
        }
    }

    Write-Progress @progressParameters
}

function Write-CosmosMigrationCountProgress {
    param(
        [int]$Id,
        [int]$ParentId = -1,
        [string]$Activity,
        [string]$Phase,
        [long]$ProcessedCount,
        [long]$TotalCount,
        [string]$CurrentOperation = ""
    )

    $percentComplete = Get-CosmosMigrationProgressPercent `
        -ProcessedCount $ProcessedCount `
        -TotalCount $TotalCount
    $remainingCount = [Math]::Max(0, $TotalCount - $ProcessedCount)
    $status = "$Phase`: $ProcessedCount/$TotalCount | Remaining: $remainingCount | $percentComplete%"

    Write-CosmosMigrationProgress `
        -Id $Id `
        -ParentId $ParentId `
        -Activity $Activity `
        -Status $status `
        -CurrentOperation $CurrentOperation `
        -PercentComplete $percentComplete
}

function Test-CosmosMigrationProgressCheckpoint {
    param(
        [long]$ProcessedCount,
        [long]$TotalCount = -1
    )

    return (
        $ProcessedCount -eq 1 -or
        ($TotalCount -gt 0 -and $ProcessedCount -eq $TotalCount) -or
        ($ProcessedCount % $ProgressUpdateInterval) -eq 0
    )
}

function Get-CosmosProgressDocumentLabel {
    param(
        [AllowNull()]
        [object]$DocumentId,
        [int]$MaximumLength = 96
    )

    $label = [string]$DocumentId
    if ([string]::IsNullOrWhiteSpace($label)) {
        return "<missing id>"
    }
    if ($label.Length -le $MaximumLength) {
        return $label
    }
    return "$($label.Substring(0, $MaximumLength - 3))..."
}

function Get-NormalizedCosmosContainerSelection {
    param(
        [AllowNull()]
        [string[]]$ContainerNames
    )

    $normalizedNames = [System.Collections.Generic.List[string]]::new()
    $seenNames = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($containerName in @($ContainerNames)) {
        $normalizedName = ([string]$containerName).Trim()
        if ([string]::IsNullOrWhiteSpace($normalizedName)) {
            throw "Containers cannot contain an empty container name."
        }
        if (
            $normalizedName.Length -gt 255 -or
            $normalizedName.IndexOfAny([char[]]'\/\?#') -ge 0
        ) {
            throw "Cosmos DB container name '$normalizedName' contains an unsupported character or exceeds 255 characters."
        }
        if (-not $seenNames.Add($normalizedName)) {
            throw "Cosmos DB container '$normalizedName' is listed more than once."
        }
        $normalizedNames.Add($normalizedName)
    }
    return $normalizedNames.ToArray()
}

function Select-CosmosMigrationContainers {
    param(
        [object[]]$SourceContainers,
        [string[]]$RequestedContainerNames,
        [string]$DatabaseName
    )

    if ($RequestedContainerNames.Count -eq 0) {
        return @($SourceContainers)
    }

    $sourceContainersByName = [System.Collections.Generic.Dictionary[string, object]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($sourceContainer in $SourceContainers) {
        $sourceContainersByName[[string]$sourceContainer.id] = $sourceContainer
    }

    $selectedContainers = [System.Collections.Generic.List[object]]::new()
    $missingContainerNames = [System.Collections.Generic.List[string]]::new()
    foreach ($containerName in $RequestedContainerNames) {
        if ($sourceContainersByName.ContainsKey($containerName)) {
            $selectedContainers.Add($sourceContainersByName[$containerName])
        }
        else {
            $missingContainerNames.Add($containerName)
        }
    }
    if ($missingContainerNames.Count -gt 0) {
        throw "Requested Cosmos DB container(s) were not found in source database '$DatabaseName': $($missingContainerNames -join ', ')."
    }
    return $selectedContainers.ToArray()
}

function Test-CosmosMigrationConfiguration {
    $configuredValues = [ordered]@{
        SourceCosmosAccount = $SourceCosmosAccount
        SourceResourceGroup = $SourceResourceGroup
        SourceSubscriptionId = $SourceSubscriptionId
        SourceDatabaseName = $SourceDatabaseName
        DestinationCosmosAccount = $DestinationCosmosAccount
        DestinationResourceGroup = $DestinationResourceGroup
        DestinationSubscriptionId = $DestinationSubscriptionId
        DestinationDatabaseName = $DestinationDatabaseName
    }
    foreach ($entry in $configuredValues.GetEnumerator()) {
        if (
            [string]::IsNullOrWhiteSpace($entry.Value) -or
            $entry.Value -match '^<[^>]+>$'
        ) {
            throw "Set '$($entry.Key)' in the script or supply it as a parameter."
        }
    }

    foreach ($accountName in @($SourceCosmosAccount, $DestinationCosmosAccount)) {
        if ($accountName -notmatch '^[a-z0-9](?:[a-z0-9-]{1,42}[a-z0-9])$') {
            throw "Cosmos DB account name '$accountName' must contain 3-44 lowercase letters, numbers, or hyphens and cannot start or end with a hyphen."
        }
    }

    foreach ($subscriptionId in @($SourceSubscriptionId, $DestinationSubscriptionId)) {
        $parsedSubscriptionId = [Guid]::Empty
        if (-not [Guid]::TryParse($subscriptionId, [ref]$parsedSubscriptionId)) {
            throw "Subscription ID '$subscriptionId' must be a valid GUID."
        }
    }

    foreach ($databaseName in @($SourceDatabaseName, $DestinationDatabaseName)) {
        if ($databaseName.Length -gt 255 -or $databaseName.IndexOfAny([char[]]'\/\?#') -ge 0) {
            throw "Cosmos DB database name '$databaseName' contains an unsupported character or exceeds 255 characters."
        }
    }

    if (
        [string]::Equals(
            $SourceCosmosAccount,
            $DestinationCosmosAccount,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        [string]::Equals(
            $SourceDatabaseName,
            $DestinationDatabaseName,
            [System.StringComparison]::Ordinal
        )
    ) {
        throw "Source and destination Cosmos DB account/database pairs must be different."
    }
}

function Get-CosmosAccountPrimaryKey {
    param(
        [string]$ProvidedKey,
        [string]$SubscriptionId,
        [string]$ResourceGroupName,
        [string]$AccountName
    )

    if (-not [string]::IsNullOrWhiteSpace($ProvidedKey)) {
        return $ProvidedKey.Trim()
    }

    Set-AzContext -SubscriptionId $SubscriptionId | Out-Null
    $encodedResourceGroupName = [Uri]::EscapeDataString($ResourceGroupName)
    $encodedAccountName = [Uri]::EscapeDataString($AccountName)
    $keyPath = "/subscriptions/$SubscriptionId/resourceGroups/$encodedResourceGroupName/providers/Microsoft.DocumentDB/databaseAccounts/$encodedAccountName/listKeys?api-version=$ManagementApiVersion"
    $keyResponse = Invoke-AzRestMethod -Method "POST" -Path $keyPath

    if ($keyResponse.StatusCode -ne 200) {
        throw "Primary key lookup failed for Cosmos DB account '$AccountName' with HTTP $($keyResponse.StatusCode)."
    }

    $keyPair = $keyResponse.Content | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($keyPair.primaryMasterKey)) {
        throw "The primary key for Cosmos DB account '$AccountName' could not be resolved."
    }

    return $keyPair.primaryMasterKey
}

function New-CosmosAuthorizationHeader {
    param(
        [string]$Method,
        [string]$ResourceType,
        [string]$ResourceLink,
        [string]$RequestDate,
        [string]$PrimaryKey
    )

    try {
        $keyBytes = [Convert]::FromBase64String($PrimaryKey)
    }
    catch {
        throw "A supplied Cosmos DB primary key is not valid Base64."
    }

    $payload = "{0}`n{1}`n{2}`n{3}`n`n" -f `
        $Method.ToLowerInvariant(), `
        $ResourceType.ToLowerInvariant(), `
        $ResourceLink, `
        $RequestDate.ToLowerInvariant()
    $hmac = [System.Security.Cryptography.HMACSHA256]::new($keyBytes)
    try {
        $hash = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($payload))
    }
    finally {
        $hmac.Dispose()
    }

    $signature = [Convert]::ToBase64String($hash)
    return [Uri]::EscapeDataString("type=master&ver=1.0&sig=$signature")
}

function ConvertTo-CosmosRequestPath {
    param(
        [string]$ResourcePath
    )

    $encodedSegments = foreach ($segment in $ResourcePath.Split('/')) {
        [Uri]::EscapeDataString($segment)
    }
    return $encodedSegments -join '/'
}

function Get-CosmosResponseHeaderValue {
    param(
        [AllowNull()]
        [object]$Headers,
        [string]$Name
    )

    if ($null -eq $Headers) {
        return ""
    }

    if ($Headers -is [System.Collections.IDictionary]) {
        foreach ($headerName in $Headers.Keys) {
            if ([string]::Equals([string]$headerName, $Name, [System.StringComparison]::OrdinalIgnoreCase)) {
                return @($Headers[$headerName]) -join ','
            }
        }
        return ""
    }

    foreach ($header in $Headers) {
        if ([string]::Equals([string]$header.Key, $Name, [System.StringComparison]::OrdinalIgnoreCase)) {
            return @($header.Value) -join ','
        }
    }
    return ""
}

function Get-CosmosStatisticsDocumentCount {
    param(
        [AllowNull()]
        [object]$Resource
    )

    if ($null -eq $Resource) {
        return -1
    }

    $statisticsProperty = $Resource.PSObject.Properties["statistics"]
    if ($null -eq $statisticsProperty -or $null -eq $statisticsProperty.Value) {
        return -1
    }

    $documentCounts = @(
        @($statisticsProperty.Value) | Where-Object { $null -ne $_ } | ForEach-Object {
            $documentCountProperty = $_.PSObject.Properties["documentCount"]
            if ($null -ne $documentCountProperty -and $null -ne $documentCountProperty.Value) {
                [long]$documentCountProperty.Value
            }
        }
    )
    if ($documentCounts.Count -eq 0) {
        return -1
    }
    return [long](($documentCounts | Measure-Object -Sum).Sum)
}

function Get-CosmosContainerDocumentCount {
    param(
        [object]$ContainerDefinition,
        [string]$SubscriptionId,
        [string]$ResourceGroupName,
        [string]$AccountName,
        [string]$DatabaseName
    )

    $embeddedCount = Get-CosmosStatisticsDocumentCount -Resource $ContainerDefinition
    if ($embeddedCount -ge 0) {
        return $embeddedCount
    }

    $encodedResourceGroupName = [Uri]::EscapeDataString($ResourceGroupName)
    $encodedAccountName = [Uri]::EscapeDataString($AccountName)
    $encodedDatabaseName = [Uri]::EscapeDataString($DatabaseName)
    $encodedContainerName = [Uri]::EscapeDataString([string]$ContainerDefinition.id)
    $managementPath = "/subscriptions/$SubscriptionId/resourceGroups/$encodedResourceGroupName/providers/Microsoft.DocumentDB/databaseAccounts/$encodedAccountName/sqlDatabases/$encodedDatabaseName/containers/${encodedContainerName}?api-version=$ManagementApiVersion"
    $managementResource = $null

    if (Get-Command "Invoke-AzRestMethod" -ErrorAction "SilentlyContinue") {
        try {
            $response = Invoke-AzRestMethod -Method "GET" -Path $managementPath
            if ($response.StatusCode -eq 200) {
                $managementResource = ($response.Content | ConvertFrom-Json -Depth 100).properties.resource
            }
        }
        catch {
            Write-Verbose "PowerShell ARM document-count lookup failed for '$($ContainerDefinition.id)': $($_.Exception.Message)"
        }
    }

    if ($null -eq $managementResource -and (Get-Command "az" -ErrorAction "SilentlyContinue")) {
        try {
            $managementUrl = "https://management.azure.com$managementPath"
            $azOutput = & az rest `
                --method get `
                --url $managementUrl `
                --output json 2>$null
            if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($azOutput)) {
                $managementResource = ($azOutput | ConvertFrom-Json -Depth 100).properties.resource
            }
        }
        catch {
            Write-Verbose "Azure CLI document-count lookup failed for '$($ContainerDefinition.id)': $($_.Exception.Message)"
        }
    }

    $managementCount = Get-CosmosStatisticsDocumentCount -Resource $managementResource
    if ($managementCount -lt 0) {
        Write-Verbose "Document total is unavailable for container '$($ContainerDefinition.id)'."
    }
    return $managementCount
}

function Write-CosmosDocumentProgress {
    param(
        [string]$Activity,
        [long]$ProcessedCount,
        [long]$TotalCount,
        [string]$CurrentOperation
    )

    if ($TotalCount -ge 0) {
        Write-CosmosMigrationCountProgress `
            -Id 1 `
            -ParentId 0 `
            -Activity $Activity `
            -Phase "Source documents" `
            -ProcessedCount $ProcessedCount `
            -TotalCount $TotalCount `
            -CurrentOperation $CurrentOperation
        return
    }

    Write-CosmosMigrationProgress `
        -Id 1 `
        -ParentId 0 `
        -Activity $Activity `
        -Status "Source documents completed: $ProcessedCount | Total: unavailable" `
        -PercentComplete -1 `
        -CurrentOperation $CurrentOperation
}

function Invoke-CosmosRestRequest {
    param(
        [string]$Endpoint,
        [string]$PrimaryKey,
        [ValidateSet("GET", "POST", "PUT")]
        [string]$Method,
        [string]$ResourcePath,
        [string]$ResourceType,
        [string]$ResourceLink,
        [AllowNull()]
        [string]$Body = $null,
        [hashtable]$AdditionalHeaders = @{},
        [int[]]$AllowedStatusCodes = @(200)
    )

    $encodedPath = ConvertTo-CosmosRequestPath -ResourcePath $ResourcePath
    $requestUri = "$($Endpoint.TrimEnd('/'))/$encodedPath"

    for ($attempt = 1; $attempt -le $MaxRetryCount; $attempt++) {
        $requestDate = [DateTime]::UtcNow.ToString(
            "r",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
        $requestHeaders = @{
            "Accept" = "application/json"
            "Authorization" = New-CosmosAuthorizationHeader `
                -Method $Method `
                -ResourceType $ResourceType `
                -ResourceLink $ResourceLink `
                -RequestDate $requestDate `
                -PrimaryKey $PrimaryKey
            "x-ms-date" = $requestDate
            "x-ms-version" = $CosmosApiVersion
        }
        $contentType = ""
        foreach ($headerName in $AdditionalHeaders.Keys) {
            if ([string]::Equals(
                $headerName,
                "Content-Type",
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
                $contentType = [string]$AdditionalHeaders[$headerName]
                continue
            }
            $requestHeaders[$headerName] = $AdditionalHeaders[$headerName]
        }

        $invokeParameters = @{
            Method = $Method
            Uri = $requestUri
            Headers = $requestHeaders
            SkipHttpErrorCheck = $true
            ErrorAction = "Stop"
        }
        if ($null -ne $Body) {
            $invokeParameters.Body = $Body
        }
        if (-not [string]::IsNullOrWhiteSpace($contentType)) {
            $invokeParameters.ContentType = $contentType
        }

        try {
            $response = Invoke-WebRequest @invokeParameters
        }
        catch {
            if ($attempt -eq $MaxRetryCount) {
                throw
            }

            $retryDelayMilliseconds = [int]([Math]::Pow(2, $attempt - 1) * 1000)
            Write-Warning "Cosmos DB request failed before receiving a response. Retrying in $retryDelayMilliseconds millisecond(s)."
            Start-Sleep -Milliseconds $retryDelayMilliseconds
            continue
        }

        $statusCode = [int]$response.StatusCode
        if ($AllowedStatusCodes -contains $statusCode) {
            $responseBody = $null
            $responseContent = [string]$response.Content
            if (-not [string]::IsNullOrWhiteSpace($responseContent)) {
                $responseBody = $responseContent | ConvertFrom-Json -Depth 100
            }
            return [pscustomobject]@{
                StatusCode = $statusCode
                Headers = $response.Headers
                Body = $responseBody
                Content = $responseContent
            }
        }

        $retryable = $statusCode -in @(408, 429, 449, 500, 503)
        if ($retryable -and $attempt -lt $MaxRetryCount) {
            $retryAfterHeader = Get-CosmosResponseHeaderValue `
                -Headers $response.Headers `
                -Name "x-ms-retry-after-ms"
            $retryAfterMilliseconds = 0
            if (-not [int]::TryParse($retryAfterHeader, [ref]$retryAfterMilliseconds)) {
                $retryAfterMilliseconds = [int]([Math]::Pow(2, $attempt - 1) * 1000)
            }
            $retryAfterMilliseconds = [Math]::Max(1, $retryAfterMilliseconds)
            Write-Warning "Cosmos DB request returned HTTP $statusCode. Retrying in $retryAfterMilliseconds millisecond(s)."
            Start-Sleep -Milliseconds $retryAfterMilliseconds
            continue
        }

        $errorContent = [string]$response.Content
        if ($errorContent.Length -gt 1000) {
            $errorContent = $errorContent.Substring(0, 1000)
        }
        throw "Cosmos DB request '$Method $ResourcePath' failed with HTTP $statusCode. $errorContent"
    }
}

function Get-CosmosDatabase {
    param(
        [string]$Endpoint,
        [string]$PrimaryKey,
        [string]$DatabaseName
    )

    $resourceLink = "dbs/$DatabaseName"
    return Invoke-CosmosRestRequest `
        -Endpoint $Endpoint `
        -PrimaryKey $PrimaryKey `
        -Method "GET" `
        -ResourcePath $resourceLink `
        -ResourceType "dbs" `
        -ResourceLink $resourceLink `
        -AllowedStatusCodes @(200, 404)
}

function New-CosmosDatabaseIfMissing {
    param(
        [string]$Endpoint,
        [string]$PrimaryKey,
        [string]$DatabaseName
    )

    $databaseResponse = Get-CosmosDatabase `
        -Endpoint $Endpoint `
        -PrimaryKey $PrimaryKey `
        -DatabaseName $DatabaseName
    if ($databaseResponse.StatusCode -eq 200) {
        return
    }

    $body = @{ id = $DatabaseName } | ConvertTo-Json -Compress
    Invoke-CosmosRestRequest `
        -Endpoint $Endpoint `
        -PrimaryKey $PrimaryKey `
        -Method "POST" `
        -ResourcePath "dbs" `
        -ResourceType "dbs" `
        -ResourceLink "" `
        -Body $body `
        -AdditionalHeaders @{ "Content-Type" = "application/json" } `
        -AllowedStatusCodes @(201) | Out-Null
    Write-Host "Created destination database: $DatabaseName"
}

function Get-CosmosContainers {
    param(
        [string]$Endpoint,
        [string]$PrimaryKey,
        [string]$DatabaseName
    )

    $databaseLink = "dbs/$DatabaseName"
    $continuation = ""
    do {
        $headers = @{
            "x-ms-max-item-count" = [string]$PageSize
        }
        if (-not [string]::IsNullOrWhiteSpace($continuation)) {
            $headers["x-ms-continuation"] = $continuation
        }
        $response = Invoke-CosmosRestRequest `
            -Endpoint $Endpoint `
            -PrimaryKey $PrimaryKey `
            -Method "GET" `
            -ResourcePath "$databaseLink/colls" `
            -ResourceType "colls" `
            -ResourceLink $databaseLink `
            -AdditionalHeaders $headers
        foreach ($container in @($response.Body.DocumentCollections)) {
            Write-Output $container
        }
        $continuation = Get-CosmosResponseHeaderValue `
            -Headers $response.Headers `
            -Name "x-ms-continuation"
    } while (-not [string]::IsNullOrWhiteSpace($continuation))
}

function ConvertTo-CosmosNonNullJsonValue {
    param(
        [AllowNull()]
        [object]$Value
    )

    if ($null -eq $Value) {
        return $null
    }
    if (
        $Value -is [string] -or
        $Value -is [ValueType]
    ) {
        return $Value
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $convertedDictionary = [ordered]@{}
        foreach ($key in $Value.Keys) {
            if ($null -ne $Value[$key]) {
                $convertedDictionary[[string]$key] = ConvertTo-CosmosNonNullJsonValue `
                    -Value $Value[$key]
            }
        }
        return $convertedDictionary
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $convertedItems = [System.Collections.Generic.List[object]]::new()
        foreach ($item in $Value) {
            if ($null -ne $item) {
                $convertedItems.Add((ConvertTo-CosmosNonNullJsonValue -Value $item))
            }
        }
        return ,$convertedItems.ToArray()
    }

    $convertedObject = [ordered]@{}
    foreach ($property in $Value.PSObject.Properties) {
        if ($null -ne $property.Value) {
            $convertedObject[$property.Name] = ConvertTo-CosmosNonNullJsonValue `
                -Value $property.Value
        }
    }
    return $convertedObject
}

function ConvertTo-CosmosWritableResource {
    param(
        [object]$Resource
    )

    $partitionKey = [ordered]@{
        paths = @($Resource.partitionKey.paths)
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Resource.partitionKey.kind)) {
        $partitionKey.kind = [string]$Resource.partitionKey.kind
    }
    if ($null -ne $Resource.partitionKey.version) {
        $partitionKey.version = $Resource.partitionKey.version
    }

    $writableResource = [ordered]@{
        id = [string]$Resource.id
        partitionKey = $partitionKey
    }
    $optionalWritableProperties = @(
        "indexingPolicy",
        "defaultTtl",
        "uniqueKeyPolicy",
        "conflictResolutionPolicy",
        "analyticalStorageTtl",
        "computedProperties",
        "clientEncryptionPolicy",
        "geospatialConfig",
        "changeFeedPolicy",
        "vectorEmbeddingPolicy",
        "fullTextPolicy"
    )
    foreach ($propertyName in $optionalWritableProperties) {
        $property = $Resource.PSObject.Properties[$propertyName]
        if ($null -ne $property -and $null -ne $property.Value) {
            $writableResource[$propertyName] = ConvertTo-CosmosNonNullJsonValue `
                -Value $property.Value
        }
    }
    return [pscustomobject]$writableResource
}

function Get-CosmosPartitionKeyDefinitionJson {
    param(
        [object]$Container
    )

    $partitionKey = [ordered]@{
        paths = @($Container.partitionKey.paths)
        kind = [string]$Container.partitionKey.kind
        version = $Container.partitionKey.version
    }
    return $partitionKey | ConvertTo-Json -Depth 10 -Compress
}

function Assert-CosmosContainerCompatibility {
    param(
        [object]$SourceContainer,
        [object]$DestinationContainer
    )

    $sourcePartitionKey = Get-CosmosPartitionKeyDefinitionJson -Container $SourceContainer
    $destinationPartitionKey = Get-CosmosPartitionKeyDefinitionJson -Container $DestinationContainer
    if ($sourcePartitionKey -ne $destinationPartitionKey) {
        throw "Container '$($SourceContainer.id)' has incompatible source and destination partition key definitions. Cosmos DB partition keys cannot be changed in place."
    }
}

function Sync-CosmosContainerDefinition {
    param(
        [object]$SourceContainer,
        [AllowNull()]
        [object]$DestinationContainer,
        [string]$DestinationEndpoint,
        [string]$DestinationKey,
        [string]$DestinationDatabase
    )

    $databaseLink = "dbs/$DestinationDatabase"
    $containerLink = "$databaseLink/colls/$($SourceContainer.id)"
    $writableContainer = ConvertTo-CosmosWritableResource -Resource $SourceContainer
    $containerBody = $writableContainer | ConvertTo-Json -Depth 100 -Compress
    Write-Verbose "Writable container definition for '$($SourceContainer.id)': $containerBody"

    if ($null -eq $DestinationContainer) {
        Invoke-CosmosRestRequest `
            -Endpoint $DestinationEndpoint `
            -PrimaryKey $DestinationKey `
            -Method "POST" `
            -ResourcePath "$databaseLink/colls" `
            -ResourceType "colls" `
            -ResourceLink $databaseLink `
            -Body $containerBody `
            -AdditionalHeaders @{ "Content-Type" = "application/json" } `
            -AllowedStatusCodes @(201) | Out-Null
        Write-Host "Created destination container: $($SourceContainer.id)"
        return
    }

    Assert-CosmosContainerCompatibility `
        -SourceContainer $SourceContainer `
        -DestinationContainer $DestinationContainer
    if ($DifferentialMigration) {
        Write-Host "Keeping existing destination container definition: $($SourceContainer.id)"
        return
    }

    Invoke-CosmosRestRequest `
        -Endpoint $DestinationEndpoint `
        -PrimaryKey $DestinationKey `
        -Method "PUT" `
        -ResourcePath $containerLink `
        -ResourceType "colls" `
        -ResourceLink $containerLink `
        -Body $containerBody `
        -AdditionalHeaders @{ "Content-Type" = "application/json" } `
        -AllowedStatusCodes @(200) | Out-Null
    Write-Host "Updated destination container definition: $($SourceContainer.id)"
}

function Invoke-CosmosDocumentFeedPage {
    param(
        [string]$Endpoint,
        [string]$PrimaryKey,
        [string]$DatabaseName,
        [string]$ContainerName,
        [string]$Continuation = ""
    )

    $containerLink = "dbs/$DatabaseName/colls/$ContainerName"
    $headers = @{
        "x-ms-max-item-count" = [string]$PageSize
    }
    if (-not [string]::IsNullOrWhiteSpace($Continuation)) {
        $headers["x-ms-continuation"] = $Continuation
    }

    return Invoke-CosmosRestRequest `
        -Endpoint $Endpoint `
        -PrimaryKey $PrimaryKey `
        -Method "GET" `
        -ResourcePath "$containerLink/docs" `
        -ResourceType "docs" `
        -ResourceLink $containerLink `
        -AdditionalHeaders $headers
}

function Get-CosmosDocuments {
    param(
        [string]$Endpoint,
        [string]$PrimaryKey,
        [string]$DatabaseName,
        [string]$ContainerName,
        [bool]$ExcludeAdminSettings
    )

    $continuation = ""

    do {
        $response = Invoke-CosmosDocumentFeedPage `
            -Endpoint $Endpoint `
            -PrimaryKey $PrimaryKey `
            -DatabaseName $DatabaseName `
            -ContainerName $ContainerName `
            -Continuation $continuation
        foreach ($document in @($response.Body.Documents)) {
            if (
                $ExcludeAdminSettings -and
                [string]::Equals(
                    [string]$document.id,
                    $adminSettingsDocumentId,
                    [System.StringComparison]::Ordinal
                )
            ) {
                continue
            }
            Write-Output $document
        }
        $continuation = Get-CosmosResponseHeaderValue `
            -Headers $response.Headers `
            -Name "x-ms-continuation"
    } while (-not [string]::IsNullOrWhiteSpace($continuation))
}

function Get-CosmosPropertyPathValue {
    param(
        [object]$Document,
        [string]$Path
    )

    $current = $Document
    $segments = $Path.TrimStart('/').Split('/')
    foreach ($encodedSegment in $segments) {
        $segment = $encodedSegment.Replace('~1', '/').Replace('~0', '~')
        if ($current -is [System.Collections.IDictionary]) {
            if (-not $current.Contains($segment)) {
                return [pscustomobject]@{ Exists = $false; Value = $null }
            }
            $current = $current[$segment]
            continue
        }

        $property = $current.PSObject.Properties[$segment]
        if ($null -eq $property) {
            return [pscustomobject]@{ Exists = $false; Value = $null }
        }
        $current = $property.Value
    }

    return [pscustomobject]@{ Exists = $true; Value = $current }
}

function Get-CosmosPartitionKeyHeader {
    param(
        [object]$Document,
        [object]$ContainerDefinition
    )

    $partitionKeyValues = [System.Collections.Generic.List[object]]::new()
    foreach ($path in @($ContainerDefinition.partitionKey.paths)) {
        $pathValue = Get-CosmosPropertyPathValue -Document $Document -Path $path
        if ($pathValue.Exists) {
            $partitionKeyValues.Add($pathValue.Value)
        }
        else {
            $partitionKeyValues.Add([pscustomobject]@{})
        }
    }
    return ConvertTo-Json -InputObject $partitionKeyValues.ToArray() -Depth 100 -Compress
}

function ConvertTo-CosmosWritableDocument {
    param(
        [object]$Document
    )

    $copy = $Document | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100
    foreach ($propertyName in @("_rid", "_self", "_etag", "_attachments", "_ts")) {
        $copy.PSObject.Properties.Remove($propertyName)
    }
    return $copy
}

function Send-CosmosDocument {
    param(
        [object]$Document,
        [object]$ContainerDefinition,
        [string]$Endpoint,
        [string]$PrimaryKey,
        [string]$DatabaseName
    )

    $writableDocument = ConvertTo-CosmosWritableDocument -Document $Document
    if ([string]::IsNullOrWhiteSpace([string]$writableDocument.id)) {
        throw "Container '$($ContainerDefinition.id)' contains a document without a valid id."
    }

    $containerLink = "dbs/$DatabaseName/colls/$($ContainerDefinition.id)"
    $headers = @{
        "Content-Type" = "application/json"
        "x-ms-documentdb-partitionkey" = Get-CosmosPartitionKeyHeader `
            -Document $writableDocument `
            -ContainerDefinition $ContainerDefinition
    }
    $allowedStatusCodes = @(201)
    if (-not $DifferentialMigration) {
        $headers["x-ms-documentdb-is-upsert"] = "true"
        $allowedStatusCodes = @(200, 201)
    }

    $response = Invoke-CosmosRestRequest `
        -Endpoint $Endpoint `
        -PrimaryKey $PrimaryKey `
        -Method "POST" `
        -ResourcePath "$containerLink/docs" `
        -ResourceType "docs" `
        -ResourceLink $containerLink `
        -Body ($writableDocument | ConvertTo-Json -Depth 100 -Compress) `
        -AdditionalHeaders $headers `
        -AllowedStatusCodes ($allowedStatusCodes + @(409))
    if ($response.StatusCode -eq 409) {
        if (-not $DifferentialMigration) {
            throw "Full migration received an unexpected conflict for document '$($writableDocument.id)' in container '$($ContainerDefinition.id)'."
        }
        return "Skipped"
    }
    return "Copied"
}

function New-CosmosDocumentWriteWorkItem {
    param(
        [object]$Document,
        [object]$ContainerDefinition,
        [long]$Sequence
    )

    $writableDocument = ConvertTo-CosmosWritableDocument -Document $Document
    if ([string]::IsNullOrWhiteSpace([string]$writableDocument.id)) {
        throw "Container '$($ContainerDefinition.id)' contains a document without a valid id."
    }

    return [pscustomobject]@{
        Sequence = $Sequence
        DocumentId = [string]$writableDocument.id
        DocumentLabel = Get-CosmosProgressDocumentLabel -DocumentId $writableDocument.id
        Body = $writableDocument | ConvertTo-Json -Depth 100 -Compress
        PartitionKeyHeader = Get-CosmosPartitionKeyHeader `
            -Document $writableDocument `
            -ContainerDefinition $ContainerDefinition
    }
}

function Invoke-CosmosParallelDocumentWrites {
    param(
        [Parameter(ValueFromPipeline)]
        [object]$WorkItem,
        [string]$Endpoint,
        [string]$PrimaryKey,
        [string]$DatabaseName,
        [string]$ContainerName
    )

    begin {
        $workItems = [System.Collections.Generic.List[object]]::new()
    }
    process {
        $workItems.Add($WorkItem)
    }
    end {
        if ($workItems.Count -eq 0) {
            return
        }

        $resourceLink = "dbs/$DatabaseName/colls/$ContainerName"
        $encodedDatabaseName = [Uri]::EscapeDataString($DatabaseName)
        $encodedContainerName = [Uri]::EscapeDataString($ContainerName)
        $requestUri = "$($Endpoint.TrimEnd('/'))/dbs/$encodedDatabaseName/colls/$encodedContainerName/docs"
        $keyBytes = [Convert]::FromBase64String($PrimaryKey)
        $apiVersion = $CosmosApiVersion
        $retryLimit = $MaxRetryCount
        $useUpsert = -not $DifferentialMigration
        $invokeWebRequestCommand = Get-Command "Invoke-WebRequest" -ErrorAction "Stop"
        $invokeWebRequestOverrideDefinition = if ($invokeWebRequestCommand.CommandType -eq "Function") {
            $invokeWebRequestCommand.Definition
        }
        else {
            ""
        }

        $workItems | ForEach-Object -Parallel {
            $currentWorkItem = $_
            if (-not [string]::IsNullOrWhiteSpace($using:invokeWebRequestOverrideDefinition)) {
                Set-Item `
                    -Path "Function:Invoke-WebRequest" `
                    -Value ([scriptblock]::Create($using:invokeWebRequestOverrideDefinition))
            }
            [pscustomobject]@{
                EventType = "Started"
                Sequence = $currentWorkItem.Sequence
                DocumentId = $currentWorkItem.DocumentId
                DocumentLabel = $currentWorkItem.DocumentLabel
                Attempt = 1
                StatusCode = 0
                RetryDelayMilliseconds = 0
                Result = ""
                ErrorMessage = ""
            }

            for ($attempt = 1; $attempt -le $using:retryLimit; $attempt++) {
                $requestDate = [DateTime]::UtcNow.ToString(
                    "r",
                    [System.Globalization.CultureInfo]::InvariantCulture
                )
                $signaturePayload = "post`ndocs`n$using:resourceLink`n$($requestDate.ToLowerInvariant())`n`n"
                $hmac = [System.Security.Cryptography.HMACSHA256]::new($using:keyBytes)
                try {
                    $hash = $hmac.ComputeHash(
                        [System.Text.Encoding]::UTF8.GetBytes($signaturePayload)
                    )
                }
                finally {
                    $hmac.Dispose()
                }
                $signature = [Convert]::ToBase64String($hash)
                $authorization = [Uri]::EscapeDataString(
                    "type=master&ver=1.0&sig=$signature"
                )
                $headers = @{
                    "Accept" = "application/json"
                    "Authorization" = $authorization
                    "x-ms-date" = $requestDate
                    "x-ms-version" = $using:apiVersion
                    "x-ms-documentdb-partitionkey" = $currentWorkItem.PartitionKeyHeader
                }
                if ($using:useUpsert) {
                    $headers["x-ms-documentdb-is-upsert"] = "true"
                }

                try {
                    $response = Invoke-WebRequest `
                        -Method "POST" `
                        -Uri $using:requestUri `
                        -Headers $headers `
                        -ContentType "application/json" `
                        -Body $currentWorkItem.Body `
                        -SkipHttpErrorCheck `
                        -ErrorAction "Stop"
                }
                catch {
                    if ($attempt -eq $using:retryLimit) {
                        [pscustomobject]@{
                            EventType = "Failed"
                            Sequence = $currentWorkItem.Sequence
                            DocumentId = $currentWorkItem.DocumentId
                            DocumentLabel = $currentWorkItem.DocumentLabel
                            Attempt = $attempt
                            StatusCode = 0
                            RetryDelayMilliseconds = 0
                            Result = ""
                            ErrorMessage = $_.Exception.Message
                        }
                        return
                    }

                    $retryDelayMilliseconds = [int]([Math]::Pow(2, $attempt - 1) * 1000)
                    [pscustomobject]@{
                        EventType = "Retrying"
                        Sequence = $currentWorkItem.Sequence
                        DocumentId = $currentWorkItem.DocumentId
                        DocumentLabel = $currentWorkItem.DocumentLabel
                        Attempt = $attempt
                        StatusCode = 0
                        RetryDelayMilliseconds = $retryDelayMilliseconds
                        Result = ""
                        ErrorMessage = $_.Exception.Message
                    }
                    Start-Sleep -Milliseconds $retryDelayMilliseconds
                    continue
                }

                $statusCode = [int]$response.StatusCode
                $successfulWrite = $statusCode -in @(200, 201)
                $differentialConflict = -not $using:useUpsert -and $statusCode -eq 409
                if ($successfulWrite -or $differentialConflict) {
                    [pscustomobject]@{
                        EventType = "Completed"
                        Sequence = $currentWorkItem.Sequence
                        DocumentId = $currentWorkItem.DocumentId
                        DocumentLabel = $currentWorkItem.DocumentLabel
                        Attempt = $attempt
                        StatusCode = $statusCode
                        RetryDelayMilliseconds = 0
                        Result = if ($differentialConflict) { "Skipped" } else { "Copied" }
                        ErrorMessage = ""
                    }
                    return
                }

                $retryable = $statusCode -in @(408, 429, 449, 500, 503)
                if ($retryable -and $attempt -lt $using:retryLimit) {
                    $retryAfterHeader = @($response.Headers["x-ms-retry-after-ms"]) -join ","
                    $retryDelayMilliseconds = 0
                    if (-not [int]::TryParse($retryAfterHeader, [ref]$retryDelayMilliseconds)) {
                        $retryDelayMilliseconds = [int]([Math]::Pow(2, $attempt - 1) * 1000)
                    }
                    $retryDelayMilliseconds = [Math]::Max(1, $retryDelayMilliseconds)
                    [pscustomobject]@{
                        EventType = "Retrying"
                        Sequence = $currentWorkItem.Sequence
                        DocumentId = $currentWorkItem.DocumentId
                        DocumentLabel = $currentWorkItem.DocumentLabel
                        Attempt = $attempt
                        StatusCode = $statusCode
                        RetryDelayMilliseconds = $retryDelayMilliseconds
                        Result = ""
                        ErrorMessage = ""
                    }
                    Start-Sleep -Milliseconds $retryDelayMilliseconds
                    continue
                }

                $errorContent = [string]$response.Content
                if ($errorContent.Length -gt 1000) {
                    $errorContent = $errorContent.Substring(0, 1000)
                }
                [pscustomobject]@{
                    EventType = "Failed"
                    Sequence = $currentWorkItem.Sequence
                    DocumentId = $currentWorkItem.DocumentId
                    DocumentLabel = $currentWorkItem.DocumentLabel
                    Attempt = $attempt
                    StatusCode = $statusCode
                    RetryDelayMilliseconds = 0
                    Result = ""
                    ErrorMessage = "HTTP $statusCode. $errorContent"
                }
                return
            }
        } -ThrottleLimit $MaxConcurrentDocuments
    }
}

function Invoke-CosmosParallelDocumentBatch {
    param(
        [object[]]$WorkItems,
        [string]$Activity,
        [string]$DestinationEndpoint,
        [string]$DestinationKey,
        [string]$DestinationDatabase,
        [string]$ContainerName,
        [long]$SourceDocumentCount,
        [long]$InitialProcessedCount,
        [long]$InitialCopiedCount,
        [long]$InitialSkippedCount,
        [long]$InitialRetryCount
    )

    $processedCount = $InitialProcessedCount
    $copiedCount = $InitialCopiedCount
    $skippedCount = $InitialSkippedCount
    $retryCount = $InitialRetryCount
    $inFlightCount = 0

    $WorkItems |
        Invoke-CosmosParallelDocumentWrites `
            -Endpoint $DestinationEndpoint `
            -PrimaryKey $DestinationKey `
            -DatabaseName $DestinationDatabase `
            -ContainerName $ContainerName |
        ForEach-Object {
            $writeEvent = $_
            $updateDocumentProgress = Test-CosmosMigrationProgressCheckpoint `
                -ProcessedCount $writeEvent.Sequence
            switch ($writeEvent.EventType) {
                "Started" {
                    $inFlightCount++
                    if ($updateDocumentProgress) {
                        Write-CosmosDocumentProgress `
                            -Activity $Activity `
                            -ProcessedCount $processedCount `
                            -TotalCount $SourceDocumentCount `
                            -CurrentOperation "Copying document $($writeEvent.Sequence)`: '$($writeEvent.DocumentLabel)' | Copied: $copiedCount | Skipped: $skippedCount"
                    }
                }
                "Retrying" {
                    $retryCount++
                }
                "Completed" {
                    $inFlightCount = [Math]::Max(0, $inFlightCount - 1)
                    $processedCount++
                    if ($writeEvent.Result -eq "Skipped") {
                        $skippedCount++
                    }
                    else {
                        $copiedCount++
                    }
                    if ($updateDocumentProgress) {
                        Write-CosmosDocumentProgress `
                            -Activity $Activity `
                            -ProcessedCount $processedCount `
                            -TotalCount $SourceDocumentCount `
                            -CurrentOperation "$($writeEvent.Result) document $($writeEvent.Sequence)`: '$($writeEvent.DocumentLabel)' | Copied: $copiedCount | Skipped: $skippedCount"
                    }
                }
                "Failed" {
                    throw "Document '$($writeEvent.DocumentId)' in container '$ContainerName' failed after $($writeEvent.Attempt) attempt(s): $($writeEvent.ErrorMessage)"
                }
                default {
                    throw "Unexpected parallel document event '$($writeEvent.EventType)'."
                }
            }
        }

    return [pscustomobject]@{
        ProcessedCount = $processedCount
        CopiedCount = $copiedCount
        SkippedCount = $skippedCount
        RetryCount = $retryCount
    }
}

function Copy-CosmosContainerDocuments {
    param(
        [object]$SourceContainer,
        [string]$SourceEndpoint,
        [string]$SourceKey,
        [string]$SourceDatabase,
        [string]$DestinationEndpoint,
        [string]$DestinationKey,
        [string]$DestinationDatabase
    )

    $excludeAdminSettings = [string]::Equals(
        $SourceContainer.id,
        $adminSettingsContainerName,
        [System.StringComparison]::Ordinal
    )
    $activity = "Container '$($SourceContainer.id)' documents"
    $copiedCount = 0
    $skippedCount = 0
    $processedCount = 0
    $retryCount = 0
    $sourceDocumentCount = Get-CosmosContainerDocumentCount `
        -ContainerDefinition $SourceContainer `
        -SubscriptionId $SourceSubscriptionId `
        -ResourceGroupName $SourceResourceGroup `
        -AccountName $SourceCosmosAccount `
        -DatabaseName $SourceDatabase
    if ($excludeAdminSettings -and $sourceDocumentCount -gt 0) {
        $sourceDocumentCount--
    }

    Write-CosmosDocumentProgress `
        -Activity $activity `
        -ProcessedCount 0 `
        -TotalCount $sourceDocumentCount `
        -CurrentOperation "Copied: 0 | Skipped: 0"

    if ($MaxConcurrentDocuments -eq 1) {
        Get-CosmosDocuments `
            -Endpoint $SourceEndpoint `
            -PrimaryKey $SourceKey `
            -DatabaseName $SourceDatabase `
            -ContainerName $SourceContainer.id `
            -ExcludeAdminSettings $excludeAdminSettings |
        ForEach-Object {
            $document = $_
            $nextDocumentNumber = $processedCount + 1
            $documentLabel = Get-CosmosProgressDocumentLabel -DocumentId $document.id
            $updateDocumentProgress = Test-CosmosMigrationProgressCheckpoint `
                -ProcessedCount $nextDocumentNumber `
                -TotalCount $sourceDocumentCount
            if ($updateDocumentProgress) {
                Write-CosmosDocumentProgress `
                    -Activity $activity `
                    -ProcessedCount $processedCount `
                    -TotalCount $sourceDocumentCount `
                    -CurrentOperation "Copying document $nextDocumentNumber`: '$documentLabel' | Copied: $copiedCount | Skipped: $skippedCount"
            }

            $result = Send-CosmosDocument `
                -Document $document `
                -ContainerDefinition $SourceContainer `
                -Endpoint $DestinationEndpoint `
                -PrimaryKey $DestinationKey `
                -DatabaseName $DestinationDatabase
            $processedCount++
            if ($result -eq "Skipped") {
                $skippedCount++
            }
            else {
                $copiedCount++
            }

                if ($updateDocumentProgress) {
                Write-CosmosDocumentProgress `
                    -Activity $activity `
                    -ProcessedCount $processedCount `
                    -TotalCount $sourceDocumentCount `
                    -CurrentOperation "$result document $processedCount`: '$documentLabel' | Copied: $copiedCount | Skipped: $skippedCount"
            }
        }
    }
    else {
        $scheduledCount = 0
        $writeBatchSize = [Math]::Min(
            $PageSize,
            [Math]::Max($MaxConcurrentDocuments, $MaxConcurrentDocuments * 4)
        )
        $workItems = [System.Collections.Generic.List[object]]::new()

        Get-CosmosDocuments `
            -Endpoint $SourceEndpoint `
            -PrimaryKey $SourceKey `
            -DatabaseName $SourceDatabase `
            -ContainerName $SourceContainer.id `
            -ExcludeAdminSettings $excludeAdminSettings |
        ForEach-Object {
            $document = $_
            $scheduledCount++
            $workItems.Add((New-CosmosDocumentWriteWorkItem `
                -Document $document `
                -ContainerDefinition $SourceContainer `
                -Sequence $scheduledCount))

            if ($workItems.Count -ge $writeBatchSize) {
                $batchResult = Invoke-CosmosParallelDocumentBatch `
                    -WorkItems $workItems.ToArray() `
                    -Activity $activity `
                    -DestinationEndpoint $DestinationEndpoint `
                    -DestinationKey $DestinationKey `
                    -DestinationDatabase $DestinationDatabase `
                    -ContainerName $SourceContainer.id `
                    -SourceDocumentCount $sourceDocumentCount `
                    -InitialProcessedCount $processedCount `
                    -InitialCopiedCount $copiedCount `
                    -InitialSkippedCount $skippedCount `
                    -InitialRetryCount $retryCount
                $processedCount = $batchResult.ProcessedCount
                $copiedCount = $batchResult.CopiedCount
                $skippedCount = $batchResult.SkippedCount
                $retryCount = $batchResult.RetryCount
                $workItems.Clear()
            }
        }

        if ($workItems.Count -gt 0) {
            $batchResult = Invoke-CosmosParallelDocumentBatch `
                -WorkItems $workItems.ToArray() `
                -Activity $activity `
                -DestinationEndpoint $DestinationEndpoint `
                -DestinationKey $DestinationKey `
                -DestinationDatabase $DestinationDatabase `
                -ContainerName $SourceContainer.id `
                -SourceDocumentCount $sourceDocumentCount `
                -InitialProcessedCount $processedCount `
                -InitialCopiedCount $copiedCount `
                -InitialSkippedCount $skippedCount `
                -InitialRetryCount $retryCount
            $processedCount = $batchResult.ProcessedCount
            $copiedCount = $batchResult.CopiedCount
            $skippedCount = $batchResult.SkippedCount
            $retryCount = $batchResult.RetryCount
        }
    }

    $finalTotalCount = if ($sourceDocumentCount -ge 0) {
        $sourceDocumentCount
    }
    else {
        $processedCount
    }
    Write-CosmosMigrationCountProgress `
        -Id 1 `
        -ParentId 0 `
        -Activity $activity `
        -Phase "Source documents" `
        -ProcessedCount $processedCount `
        -TotalCount $finalTotalCount `
        -CurrentOperation "Copied: $copiedCount | Skipped: $skippedCount"
    Write-CosmosMigrationProgress -Id 1 -ParentId 0 -Activity $activity -Completed
    Write-Host "Completed container '$($SourceContainer.id)': copied=$copiedCount, skipped=$skippedCount"
    return [pscustomobject]@{
        CopiedCount = $copiedCount
        SkippedCount = $skippedCount
        ProcessedCount = $processedCount
        TotalCount = $finalTotalCount
        RetryCount = $retryCount
    }
}

$SourceCosmosAccount = $SourceCosmosAccount.Trim()
$SourceResourceGroup = $SourceResourceGroup.Trim()
$SourceSubscriptionId = $SourceSubscriptionId.Trim()
$SourceDatabaseName = $SourceDatabaseName.Trim()
$DestinationCosmosAccount = $DestinationCosmosAccount.Trim()
$DestinationResourceGroup = $DestinationResourceGroup.Trim()
$DestinationSubscriptionId = $DestinationSubscriptionId.Trim()
$DestinationDatabaseName = $DestinationDatabaseName.Trim()
$CosmosApiVersion = $CosmosApiVersion.Trim()
$ManagementApiVersion = $ManagementApiVersion.Trim()
$CosmosDnsSuffix = $CosmosDnsSuffix.Trim().Trim('.')
$requestedContainerNames = @(Get-NormalizedCosmosContainerSelection -ContainerNames $Containers)
if ([string]::IsNullOrWhiteSpace($StateFilePath)) {
    $StateFilePath = Join-Path $PSScriptRoot "Migration-Cosmos.state.json"
}
$sourceEndpoint = "https://$SourceCosmosAccount.$CosmosDnsSuffix"
$destinationEndpoint = "https://$DestinationCosmosAccount.$CosmosDnsSuffix"
$migrationMode = if ($DifferentialMigration) { "differential" } else { "full" }
$migrationState = $null
$activeMigrationResource = $null

try {
    Test-CosmosMigrationConfiguration

    Write-CosmosMigrationProgress `
        -Id 0 `
        -Activity "Cosmos DB migration" `
        -Status "Connecting and discovering source resources" `
        -CurrentOperation "Resolving credentials" `
        -PercentComplete -1

    if ([string]::IsNullOrWhiteSpace($SourcePrimaryKey) -or [string]::IsNullOrWhiteSpace($DestinationPrimaryKey)) {
        foreach ($requiredCommand in @("Connect-AzAccount", "Set-AzContext", "Invoke-AzRestMethod")) {
            if (-not (Get-Command $requiredCommand -ErrorAction SilentlyContinue)) {
                throw "The Az.Accounts command '$requiredCommand' is required when primary keys are not supplied."
            }
        }
        Connect-AzAccount | Out-Null
    }

    $resolvedSourceKey = Get-CosmosAccountPrimaryKey `
        -ProvidedKey $SourcePrimaryKey `
        -SubscriptionId $SourceSubscriptionId `
        -ResourceGroupName $SourceResourceGroup `
        -AccountName $SourceCosmosAccount
    $resolvedDestinationKey = Get-CosmosAccountPrimaryKey `
        -ProvidedKey $DestinationPrimaryKey `
        -SubscriptionId $DestinationSubscriptionId `
        -ResourceGroupName $DestinationResourceGroup `
        -AccountName $DestinationCosmosAccount

    $sourceDatabase = Get-CosmosDatabase `
        -Endpoint $sourceEndpoint `
        -PrimaryKey $resolvedSourceKey `
        -DatabaseName $SourceDatabaseName
    if ($sourceDatabase.StatusCode -ne 200) {
        throw "Source database '$SourceDatabaseName' does not exist in Cosmos DB account '$SourceCosmosAccount'."
    }

    $allSourceContainers = @(Get-CosmosContainers `
        -Endpoint $sourceEndpoint `
        -PrimaryKey $resolvedSourceKey `
        -DatabaseName $SourceDatabaseName)
    $sourceContainers = @(Select-CosmosMigrationContainers `
        -SourceContainers $allSourceContainers `
        -RequestedContainerNames $requestedContainerNames `
        -DatabaseName $SourceDatabaseName)
    $stateContainerNames = [string[]]@($sourceContainers | ForEach-Object { [string]$_.id })
    [Array]::Sort($stateContainerNames, [System.StringComparer]::Ordinal)
    $selectionMode = if ($requestedContainerNames.Count -eq 0) { "all" } else { "explicit" }
    $stateConfiguration = [ordered]@{
        sourceAccount = $SourceCosmosAccount
        sourceResourceGroup = $SourceResourceGroup
        sourceSubscriptionId = $SourceSubscriptionId
        sourceDatabase = $SourceDatabaseName
        destinationAccount = $DestinationCosmosAccount
        destinationResourceGroup = $DestinationResourceGroup
        destinationSubscriptionId = $DestinationSubscriptionId
        destinationDatabase = $DestinationDatabaseName
        containers = @($stateContainerNames)
        containerSelectionMode = $selectionMode
        mode = $migrationMode
        cosmosApiVersion = $CosmosApiVersion
        cosmosDnsSuffix = $CosmosDnsSuffix
        excludedAdminSettingsDocument = "$adminSettingsContainerName/$adminSettingsDocumentId"
    }
    $migrationState = Initialize-MigrationState `
        -MigrationType "cosmos" `
        -StateFilePath $StateFilePath `
        -Configuration $stateConfiguration `
        -Reset:$ResetState
    Write-Host "Migration state: $($migrationState.Path)"

    New-CosmosDatabaseIfMissing `
        -Endpoint $destinationEndpoint `
        -PrimaryKey $resolvedDestinationKey `
        -DatabaseName $DestinationDatabaseName

    Write-Host "Starting $migrationMode Cosmos DB migration. Destination-only containers and documents will not be deleted."
    Write-Host "Document write concurrency: $MaxConcurrentDocuments"
    Write-Host "Preserving destination admin app settings. '$adminSettingsContainerName/$adminSettingsDocumentId' will not be migrated."
    if ($selectionMode -eq "explicit") {
        Write-Host "Selected containers: $($stateContainerNames -join ', ')"
    }
    $destinationContainers = @(Get-CosmosContainers `
        -Endpoint $destinationEndpoint `
        -PrimaryKey $resolvedDestinationKey `
        -DatabaseName $DestinationDatabaseName)
    $destinationContainersByName = @{}
    foreach ($destinationContainer in $destinationContainers) {
        $destinationContainersByName[$destinationContainer.id] = $destinationContainer
    }

    $completedContainerCount = 0
    $totalCopiedCount = 0
    $totalSkippedCount = 0
    $containerNumber = 0
    Write-CosmosMigrationCountProgress `
        -Id 0 `
        -Activity "Cosmos DB migration" `
        -Phase "Containers" `
        -ProcessedCount 0 `
        -TotalCount $sourceContainers.Count `
        -CurrentOperation "Ready to migrate $($sourceContainers.Count) container(s)"

    foreach ($sourceContainer in $sourceContainers) {
        $containerNumber++
        $resourceName = [string]$sourceContainer.id
        Write-CosmosMigrationCountProgress `
            -Id 0 `
            -Activity "Cosmos DB migration" `
            -Phase "Containers" `
            -ProcessedCount $completedContainerCount `
            -TotalCount $sourceContainers.Count `
            -CurrentOperation "Current container: $containerNumber/$($sourceContainers.Count) - $($sourceContainer.id)"

        if (Test-MigrationResourceCompleted `
            -Context $migrationState `
            -ResourceName $resourceName) {
            $checkpoint = Get-MigrationResourceCheckpoint `
                -Context $migrationState `
                -ResourceName $resourceName
            $completedContainerCount++
            $totalCopiedCount += [long]$checkpoint["result"]["CopiedCount"]
            $totalSkippedCount += [long]$checkpoint["result"]["SkippedCount"]
            Write-Host "Skipping completed container from migration state: $resourceName"
            Write-CosmosMigrationCountProgress `
                -Id 0 `
                -Activity "Cosmos DB migration" `
                -Phase "Containers" `
                -ProcessedCount $completedContainerCount `
                -TotalCount $sourceContainers.Count `
                -CurrentOperation "Documents copied: $totalCopiedCount | Skipped: $totalSkippedCount"
            continue
        }

        Start-MigrationResourceCheckpoint `
            -Context $migrationState `
            -ResourceName $resourceName
        $activeMigrationResource = $resourceName

        $destinationContainer = if ($destinationContainersByName.ContainsKey($sourceContainer.id)) {
            $destinationContainersByName[$sourceContainer.id]
        }
        else {
            $null
        }
        Sync-CosmosContainerDefinition `
            -SourceContainer $sourceContainer `
            -DestinationContainer $destinationContainer `
            -DestinationEndpoint $destinationEndpoint `
            -DestinationKey $resolvedDestinationKey `
            -DestinationDatabase $DestinationDatabaseName

        $containerResult = Copy-CosmosContainerDocuments `
            -SourceContainer $sourceContainer `
            -SourceEndpoint $sourceEndpoint `
            -SourceKey $resolvedSourceKey `
            -SourceDatabase $SourceDatabaseName `
            -DestinationEndpoint $destinationEndpoint `
            -DestinationKey $resolvedDestinationKey `
            -DestinationDatabase $DestinationDatabaseName
        Complete-MigrationResourceCheckpoint `
            -Context $migrationState `
            -ResourceName $resourceName `
            -Result $containerResult
        $activeMigrationResource = $null
        $completedContainerCount++
        $totalCopiedCount += $containerResult.CopiedCount
        $totalSkippedCount += $containerResult.SkippedCount

        Write-CosmosMigrationCountProgress `
            -Id 0 `
            -Activity "Cosmos DB migration" `
            -Phase "Containers" `
            -ProcessedCount $completedContainerCount `
            -TotalCount $sourceContainers.Count `
            -CurrentOperation "Documents copied: $totalCopiedCount | Skipped: $totalSkippedCount"
    }

    Complete-MigrationState `
        -Context $migrationState `
        -Summary ([ordered]@{
            ContainerCount = $completedContainerCount
            CopiedCount = $totalCopiedCount
            SkippedCount = $totalSkippedCount
        })
    Write-Host "Cosmos DB migration completed successfully. Containers processed: $completedContainerCount, documents copied: $totalCopiedCount, documents skipped: $totalSkippedCount"
}
catch {
    $migrationErrorMessage = $_.Exception.Message
    if ($null -ne $migrationState) {
        try {
            Set-MigrationStateFailure `
                -Context $migrationState `
                -ResourceName $activeMigrationResource `
                -ErrorMessage $migrationErrorMessage
        }
        catch {
            Write-Warning "Failed to update migration state after an error: $($_.Exception.Message)"
        }
    }
    Write-Error "Cosmos DB migration failed: $migrationErrorMessage" -ErrorAction Continue
    throw
}
finally {
    Write-CosmosMigrationProgress -Id 1 -ParentId 0 -Activity "Container documents" -Completed
    Write-CosmosMigrationProgress -Id 0 -Activity "Cosmos DB migration" -Completed
}