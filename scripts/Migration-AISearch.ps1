# Migration-AISearch.ps1
#Requires -Version 7.0

[CmdletBinding()]
param(
    [string]$SourceSearchService = "<source-search-service>",

    [string]$SourceResourceGroup = "<source-resource-group>",

    [string]$SourceSubscriptionId = "<source-subscription-id>",

    [string]$SourceAdminKey = "",

    [string]$DestinationSearchService = "<destination-search-service>",

    [string]$DestinationResourceGroup = "<destination-resource-group>",

    [string]$DestinationSubscriptionId = "<destination-subscription-id>",

    [string]$DestinationAdminKey = "",

    [bool]$DifferentialMigration = $false,

    [bool]$ShowProgress = $true,

    [ValidateRange(1, 100000)]
    [int]$ProgressUpdateInterval = 100,

    [ValidateRange(1, 1000)]
    [int]$BatchSize = 100,

    [ValidateRange(1, 64)]
    [int]$MaxConcurrentBatches = 30,

    [ValidateRange(1024, 16777216)]
    [int]$MaxBatchBytes = 15000000,

    [ValidateRange(1, 1000)]
    [int]$PageSize = 100,

    [ValidateRange(1, 10)]
    [int]$MaxRetryCount = 5,

    [ValidateRange(30, 3600)]
    [int]$RequestTimeoutSeconds = 300,

    [string]$ApiVersion = "2026-04-01",

    [string]$ManagementApiVersion = "2025-05-01",

    # Optional parameters for testing against Azure Government or other sovereign clouds.    
    [string]$SearchDnsSuffix = "search.windows.net",

    [string]$StateFilePath = "",

    [switch]$ResetState
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Migration-State.ps1")

function Get-AISearchProgressPercent {
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

function Write-AISearchProgress {
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

function Write-AISearchCountProgress {
    param(
        [int]$Id,
        [int]$ParentId = -1,
        [string]$Activity,
        [string]$Phase,
        [long]$ProcessedCount,
        [long]$TotalCount,
        [string]$CurrentOperation = ""
    )

    $percentComplete = Get-AISearchProgressPercent `
        -ProcessedCount $ProcessedCount `
        -TotalCount $TotalCount
    $remainingCount = [Math]::Max(0, $TotalCount - $ProcessedCount)
    $status = "$Phase`: $ProcessedCount/$TotalCount | Remaining: $remainingCount | $percentComplete%"

    Write-AISearchProgress `
        -Id $Id `
        -ParentId $ParentId `
        -Activity $Activity `
        -Status $status `
        -CurrentOperation $CurrentOperation `
        -PercentComplete $percentComplete
}

function Test-AISearchProgressCheckpoint {
    param(
        [long]$ProcessedCount,
        [long]$TotalCount
    )

    return (
        $ProcessedCount -eq 1 -or
        $ProcessedCount -eq $TotalCount -or
        ($ProcessedCount % $ProgressUpdateInterval) -eq 0
    )
}

function Get-AISearchAdminKey {
    param(
        [string]$ProvidedKey,
        [string]$SubscriptionId,
        [string]$ResourceGroupName,
        [string]$ServiceName
    )

    if (-not [string]::IsNullOrWhiteSpace($ProvidedKey)) {
        return $ProvidedKey
    }

    Set-AzContext -SubscriptionId $SubscriptionId | Out-Null
    $encodedResourceGroupName = [Uri]::EscapeDataString($ResourceGroupName)
    $encodedServiceName = [Uri]::EscapeDataString($ServiceName)
    $keyPath = "/subscriptions/$SubscriptionId/resourceGroups/$encodedResourceGroupName/providers/Microsoft.Search/searchServices/$encodedServiceName/listAdminKeys?api-version=$ManagementApiVersion"
    $keyResponse = Invoke-AzRestMethod -Method "POST" -Path $keyPath

    if ($keyResponse.StatusCode -ne 200) {
        throw "Admin key lookup failed for AI Search service '$ServiceName' with HTTP $($keyResponse.StatusCode)."
    }

    $keyPair = $keyResponse.Content | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($keyPair.primaryKey)) {
        throw "The primary admin key for AI Search service '$ServiceName' could not be resolved."
    }

    return $keyPair.primaryKey
}

function New-AISearchUri {
    param(
        [string]$Endpoint,
        [string]$RelativePath
    )

    return "{0}/{1}?api-version={2}" -f $Endpoint.Trim().TrimEnd("/"), $RelativePath.Trim().TrimStart("/"), $ApiVersion.Trim()
}

function Invoke-AISearchRequest {
    param(
        [ValidateSet("GET", "POST", "PUT")]
        [string]$Method,
        [string]$Uri,
        [string]$AdminKey,
        [AllowNull()]
        [object]$Body = $null
    )

    $headers = @{
        "api-key" = $AdminKey
        "Accept" = "application/json"
    }

    $invokeParameters = @{
        Method = $Method
        Uri = $Uri
        Headers = $headers
        TimeoutSec = $RequestTimeoutSeconds
        ErrorAction = "Stop"
    }

    if ($null -ne $Body) {
        $invokeParameters.ContentType = "application/json"
        $invokeParameters.Body = $Body | ConvertTo-Json -Depth 100 -Compress
    }

    for ($attempt = 1; $attempt -le $MaxRetryCount; $attempt++) {
        try {
            return Invoke-RestMethod @invokeParameters
        }
        catch {
            $statusCode = $null
            if ($null -ne $_.Exception.Response) {
                $statusCode = [int]$_.Exception.Response.StatusCode
            }

            $requestTimedOut = $_.Exception.Message -match '(?i)timed out|timeout'
            $retryable = $statusCode -in @(409, 422, 429, 503) -or $requestTimedOut
            if (-not $retryable -or $attempt -eq $MaxRetryCount) {
                throw
            }

            $retryDelaySeconds = [Math]::Pow(2, $attempt - 1)
            $failureDescription = if ($requestTimedOut) { "timed out" } else { "returned HTTP $statusCode" }
            Write-Warning "AI Search request $failureDescription. Retrying in $retryDelaySeconds second(s)."
            Start-Sleep -Seconds $retryDelaySeconds
        }
    }
}

function ConvertTo-AISearchWritableDefinition {
    param(
        [object]$Definition
    )

    $copy = $Definition | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100
    foreach ($property in @($copy.PSObject.Properties)) {
        if ($property.Name.StartsWith("@odata.", [System.StringComparison]::Ordinal)) {
            $copy.PSObject.Properties.Remove($property.Name)
        }
    }

    $definitionJson = $copy | ConvertTo-Json -Depth 100 -Compress
    if ($definitionJson.Contains('"<redacted>"')) {
        throw "The definition for '$($copy.name)' contains a redacted secret and cannot be recreated automatically."
    }

    return $copy
}

function Get-AISearchKeyField {
    param(
        [object]$IndexDefinition
    )

    $keyFields = @($IndexDefinition.fields | Where-Object { $_.key -eq $true })
    if ($keyFields.Count -ne 1) {
        throw "AI Search index '$($IndexDefinition.name)' must have exactly one key field."
    }

    return $keyFields[0]
}

function Get-AISearchDocumentCount {
    param(
        [string]$Endpoint,
        [string]$AdminKey,
        [string]$IndexName
    )

    $encodedIndexName = [Uri]::EscapeDataString($IndexName)
    $countUri = New-AISearchUri -Endpoint $Endpoint -RelativePath "indexes/$encodedIndexName/docs/`$count"
    return [long](Invoke-AISearchRequest -Method "GET" -Uri $countUri -AdminKey $AdminKey)
}

function Get-AISearchDocuments {
    param(
        [string]$Endpoint,
        [string]$AdminKey,
        [object]$IndexDefinition,
        [switch]$KeysOnly,
        [long]$TotalCount = 0,
        [string]$ProgressActivity = "",
        [string]$ProgressPhase = "Documents",
        [string]$StartAfterKey = "",
        [long]$InitialProcessedCount = 0
    )

    $keyField = Get-AISearchKeyField -IndexDefinition $IndexDefinition
    $encodedIndexName = [Uri]::EscapeDataString($IndexDefinition.name)
    $searchUri = New-AISearchUri -Endpoint $Endpoint -RelativePath "indexes/$encodedIndexName/docs/search"
    $supportsKeysetPagination = $keyField.filterable -eq $true -and $keyField.sortable -eq $true
    $skip = 0
    if (-not [string]::IsNullOrEmpty($StartAfterKey) -and -not $supportsKeysetPagination) {
        throw "Index '$($IndexDefinition.name)' cannot resume by key because its key field is not filterable and sortable."
    }
    $lastKey = if ([string]::IsNullOrEmpty($StartAfterKey)) { $null } else { $StartAfterKey }
    $migrationComplete = $false
    $pageNumber = 0
    $emittedCount = $InitialProcessedCount

    while (-not $migrationComplete) {
        $requestBody = [ordered]@{
            search = "*"
            top = $PageSize
            count = $true
        }

        if ($KeysOnly) {
            $requestBody.select = $keyField.name
        }

        if ($supportsKeysetPagination) {
            $requestBody.orderby = "$($keyField.name) asc"
            if ($null -ne $lastKey) {
                $escapedLastKey = ([string]$lastKey).Replace("'", "''")
                $requestBody.filter = "$($keyField.name) gt '$escapedLastKey'"
            }
        }
        else {
            $requestBody.skip = $skip
        }

        $requestUri = $searchUri
        $logicalPageCount = 0
        $logicalPageLastKey = $lastKey

        do {
            $pageNumber++
            if (-not [string]::IsNullOrWhiteSpace($ProgressActivity)) {
                Write-AISearchCountProgress `
                    -Id 1 `
                    -ParentId 0 `
                    -Activity $ProgressActivity `
                    -Phase $ProgressPhase `
                    -ProcessedCount $emittedCount `
                    -TotalCount $TotalCount `
                    -CurrentOperation "Requesting page $pageNumber (up to $PageSize documents; timeout: $RequestTimeoutSeconds seconds)"
            }

            $requestStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
            $response = Invoke-AISearchRequest `
                -Method "POST" `
                -Uri $requestUri `
                -AdminKey $AdminKey `
                -Body $requestBody
            $requestStopwatch.Stop()

            $documents = @($response.value)
            if ($pageNumber -eq 1 -or ($pageNumber % 10) -eq 0 -or $documents.Count -lt $PageSize) {
                $elapsedSeconds = [Math]::Round($requestStopwatch.Elapsed.TotalSeconds, 1)
                Write-Host "Fetched $ProgressPhase page $pageNumber for index '$($IndexDefinition.name)': $($documents.Count) document(s) in $elapsedSeconds second(s)."
            }
            foreach ($document in $documents) {
                Write-Output $document
                $emittedCount++
            }

            $logicalPageCount += $documents.Count
            if ($documents.Count -gt 0) {
                $logicalPageLastKey = $documents[-1].PSObject.Properties[$keyField.name].Value
            }

            $nextLink = $response.PSObject.Properties["@odata.nextLink"].Value
            $nextPageParameters = $response.PSObject.Properties["@search.nextPageParameters"].Value
            if ($null -ne $nextLink -and $null -ne $nextPageParameters) {
                $requestUri = $nextLink
                $requestBody = $nextPageParameters
            }
            else {
                $requestUri = $null
            }
        } while ($null -ne $requestUri)

        if ($logicalPageCount -lt $PageSize) {
            $migrationComplete = $true
            continue
        }

        if ($supportsKeysetPagination) {
            if ($logicalPageLastKey -eq $lastKey) {
                throw "Keyset pagination did not advance for index '$($IndexDefinition.name)'."
            }
            $lastKey = $logicalPageLastKey
        }
        else {
            $skip += $logicalPageCount
            if ($skip -gt 100000) {
                throw "Index '$($IndexDefinition.name)' exceeds skip-based paging limits. Its key field must be filterable and sortable to migrate more than 100,000 documents."
            }
        }
    }
}

function ConvertTo-AISearchWriteDocument {
    param(
        [object]$Document,
        [ValidateSet("upload", "mergeOrUpload")]
        [string]$Action
    )

    $writeDocument = [ordered]@{
        "@search.action" = $Action
    }

    foreach ($property in $Document.PSObject.Properties) {
        if (-not $property.Name.StartsWith("@search.", [System.StringComparison]::Ordinal)) {
            $writeDocument[$property.Name] = $property.Value
        }
    }

    return [pscustomobject]$writeDocument
}

function Send-AISearchDocumentBatch {
    param(
        [string]$Endpoint,
        [string]$AdminKey,
        [string]$IndexName,
        [System.Collections.Generic.List[object]]$Documents
    )

    if ($Documents.Count -eq 0) {
        return 0
    }

    $encodedIndexName = [Uri]::EscapeDataString($IndexName)
    $indexUri = New-AISearchUri -Endpoint $Endpoint -RelativePath "indexes/$encodedIndexName/docs/index"
    for ($attempt = 1; $attempt -le $MaxRetryCount; $attempt++) {
        $response = Invoke-AISearchRequest `
            -Method "POST" `
            -Uri $indexUri `
            -AdminKey $AdminKey `
            -Body @{ value = @($Documents) }

        $failedDocuments = @($response.value | Where-Object { $_.status -ne $true })
        if ($failedDocuments.Count -eq 0) {
            return $Documents.Count
        }

        $permanentFailures = @($failedDocuments | Where-Object {
            [int]$_.statusCode -notin @(409, 422, 429, 503)
        })
        if ($permanentFailures.Count -gt 0 -or $attempt -eq $MaxRetryCount) {
            $failureSummary = $failedDocuments | ForEach-Object {
                "key=$($_.key), status=$($_.statusCode), error=$($_.errorMessage)"
            }
            throw "Document indexing failed for index '$IndexName': $($failureSummary -join '; ')"
        }

        $retryDelaySeconds = [Math]::Pow(2, $attempt - 1)
        Write-Warning "Document indexing returned transient failures for '$IndexName'. Retrying the batch in $retryDelaySeconds second(s)."
        Start-Sleep -Seconds $retryDelaySeconds
    }
}

function New-AISearchDocumentBatchWorkItem {
    param(
        [System.Collections.Generic.List[object]]$Documents,
        [long]$Sequence
    )

    $documentArray = @($Documents.ToArray())
    return [pscustomobject]@{
        Sequence = $Sequence
        DocumentCount = $documentArray.Count
        Documents = $documentArray
        Body = @{ value = $documentArray } | ConvertTo-Json -Depth 100 -Compress
    }
}

function Invoke-AISearchParallelDocumentBatches {
    param(
        [Parameter(ValueFromPipeline)]
        [object]$WorkItem,
        [string]$Endpoint,
        [string]$AdminKey,
        [string]$IndexName
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

        $encodedIndexName = [Uri]::EscapeDataString($IndexName)
        $indexUri = New-AISearchUri `
            -Endpoint $Endpoint `
            -RelativePath "indexes/$encodedIndexName/docs/index"
        $retryLimit = $MaxRetryCount
        $requestTimeout = $RequestTimeoutSeconds
        $invokeRestMethodCommand = Get-Command "Invoke-RestMethod" -ErrorAction "Stop"
        $invokeRestMethodOverrideDefinition = if (
            $invokeRestMethodCommand.CommandType -eq "Function"
        ) {
            $invokeRestMethodCommand.Definition
        }
        else {
            ""
        }
        $startSleepCommand = Get-Command "Start-Sleep" -ErrorAction "Stop"
        $startSleepOverrideDefinition = if ($startSleepCommand.CommandType -eq "Function") {
            $startSleepCommand.Definition
        }
        else {
            ""
        }

        $workItems | ForEach-Object -Parallel {
            $currentWorkItem = $_
            if (-not [string]::IsNullOrWhiteSpace($using:invokeRestMethodOverrideDefinition)) {
                Set-Item `
                    -Path "Function:Invoke-RestMethod" `
                    -Value ([scriptblock]::Create($using:invokeRestMethodOverrideDefinition))
            }
            if (-not [string]::IsNullOrWhiteSpace($using:startSleepOverrideDefinition)) {
                Set-Item `
                    -Path "Function:Start-Sleep" `
                    -Value ([scriptblock]::Create($using:startSleepOverrideDefinition))
            }

            $headers = @{
                "api-key" = $using:AdminKey
                "Accept" = "application/json"
            }
            for ($attempt = 1; $attempt -le $using:retryLimit; $attempt++) {
                try {
                    $response = Invoke-RestMethod `
                        -Method "POST" `
                        -Uri $using:indexUri `
                        -Headers $headers `
                        -ContentType "application/json" `
                        -Body $currentWorkItem.Body `
                        -TimeoutSec $using:requestTimeout `
                        -ErrorAction "Stop"
                }
                catch {
                    $statusCode = 0
                    if ($null -ne $_.Exception.Response) {
                        try {
                            $statusCode = [int]$_.Exception.Response.StatusCode
                        }
                        catch {
                            $statusCode = 0
                        }
                    }

                    $requestTimedOut = $_.Exception.Message -match '(?i)timed out|timeout'
                    $retryable = $statusCode -in @(409, 422, 429, 503) -or $requestTimedOut
                    if ($retryable -and $attempt -lt $using:retryLimit) {
                        $retryDelaySeconds = [int][Math]::Pow(2, $attempt - 1)
                        Start-Sleep -Seconds $retryDelaySeconds
                        continue
                    }

                    [pscustomobject]@{
                        Sequence = $currentWorkItem.Sequence
                        DocumentCount = $currentWorkItem.DocumentCount
                        Succeeded = $false
                        ErrorMessage = "AI Search batch request failed after $attempt attempt(s): $($_.Exception.Message)"
                    }
                    return
                }

                $failedDocuments = @($response.value | Where-Object { $_.status -ne $true })
                if ($failedDocuments.Count -eq 0) {
                    [pscustomobject]@{
                        Sequence = $currentWorkItem.Sequence
                        DocumentCount = $currentWorkItem.DocumentCount
                        Succeeded = $true
                        ErrorMessage = ""
                    }
                    return
                }

                $permanentFailures = @($failedDocuments | Where-Object {
                    [int]$_.statusCode -notin @(409, 422, 429, 503)
                })
                if ($permanentFailures.Count -gt 0 -or $attempt -eq $using:retryLimit) {
                    $failureSummary = $failedDocuments | ForEach-Object {
                        "key=$($_.key), status=$($_.statusCode), error=$($_.errorMessage)"
                    }
                    [pscustomobject]@{
                        Sequence = $currentWorkItem.Sequence
                        DocumentCount = $currentWorkItem.DocumentCount
                        Succeeded = $false
                        ErrorMessage = "Document indexing failed for index '$using:IndexName': $($failureSummary -join '; ')"
                    }
                    return
                }

                $retryDelaySeconds = [int][Math]::Pow(2, $attempt - 1)
                Start-Sleep -Seconds $retryDelaySeconds
            }
        } -ThrottleLimit $MaxConcurrentBatches
    }
}

function Send-AISearchDocumentBatchWindow {
    param(
        [System.Collections.Generic.List[object]]$WorkItems,
        [string]$Endpoint,
        [string]$AdminKey,
        [string]$IndexName
    )

    if ($WorkItems.Count -eq 0) {
        return 0
    }

    if ($MaxConcurrentBatches -eq 1) {
        $copiedCount = 0
        foreach ($workItem in $WorkItems) {
            $documents = [System.Collections.Generic.List[object]]::new()
            foreach ($document in @($workItem.Documents)) {
                $documents.Add($document)
            }
            $copiedCount += Send-AISearchDocumentBatch `
                -Endpoint $Endpoint `
                -AdminKey $AdminKey `
                -IndexName $IndexName `
                -Documents $documents
        }
        return $copiedCount
    }

    $batchResults = @(
        $WorkItems.ToArray() |
            Invoke-AISearchParallelDocumentBatches `
                -Endpoint $Endpoint `
                -AdminKey $AdminKey `
                -IndexName $IndexName |
            Sort-Object Sequence
    )
    if ($batchResults.Count -ne $WorkItems.Count) {
        throw "AI Search parallel batch processing returned $($batchResults.Count) result(s) for $($WorkItems.Count) batch(es)."
    }

    $failedBatch = @($batchResults | Where-Object { -not $_.Succeeded } | Select-Object -First 1)
    if ($failedBatch.Count -gt 0) {
        throw $failedBatch[0].ErrorMessage
    }

    return [long](($batchResults | Measure-Object -Property DocumentCount -Sum).Sum)
}

function Copy-AISearchSynonymMaps {
    param(
        [string]$SourceEndpoint,
        [string]$SourceKey,
        [string]$DestinationEndpoint,
        [string]$DestinationKey
    )

    $sourceUri = New-AISearchUri -Endpoint $SourceEndpoint -RelativePath "synonymmaps"
    $destinationUri = New-AISearchUri -Endpoint $DestinationEndpoint -RelativePath "synonymmaps"
    $sourceMaps = @((Invoke-AISearchRequest -Method "GET" -Uri $sourceUri -AdminKey $SourceKey).value)
    $destinationMaps = @((Invoke-AISearchRequest -Method "GET" -Uri $destinationUri -AdminKey $DestinationKey).value)
    $destinationMapNames = @{}
    foreach ($synonymMap in $destinationMaps) {
        $destinationMapNames[$synonymMap.name] = $true
    }

    foreach ($synonymMap in $sourceMaps) {
        if ($DifferentialMigration -and $destinationMapNames.ContainsKey($synonymMap.name)) {
            Write-Host "Skipping existing synonym map: $($synonymMap.name)"
            continue
        }

        $writableMap = ConvertTo-AISearchWritableDefinition -Definition $synonymMap
        $encodedMapName = [Uri]::EscapeDataString($synonymMap.name)
        $mapUri = New-AISearchUri -Endpoint $DestinationEndpoint -RelativePath "synonymmaps/$encodedMapName"
        Invoke-AISearchRequest -Method "PUT" -Uri $mapUri -AdminKey $DestinationKey -Body $writableMap | Out-Null
        Write-Host "Migrated synonym map: $($synonymMap.name)"
    }
}

function Update-AISearchDocumentCheckpoint {
    param(
        [object]$StateContext,
        [string]$ResourceName,
        [object]$KeyField,
        [long]$SourceDocumentCount,
        [AllowNull()]
        [object]$LastCommittedKey,
        [long]$ProcessedCount,
        [long]$CopiedCount,
        [long]$SkippedCount,
        [long]$BatchCount
    )

    Update-MigrationResourceCheckpoint `
        -Context $StateContext `
        -ResourceName $ResourceName `
        -Progress ([ordered]@{
            phase = "source_documents"
            keyField = $KeyField.name
            resumeSupported = ($KeyField.filterable -eq $true -and $KeyField.sortable -eq $true)
            sourceDocumentCount = $SourceDocumentCount
            lastCommittedKey = $LastCommittedKey
            processedCount = $ProcessedCount
            copiedCount = $CopiedCount
            skippedCount = $SkippedCount
            batchCount = $BatchCount
        })
}

function Copy-AISearchIndexDocuments {
    param(
        [object]$SourceIndex,
        [AllowNull()]
        [object]$DestinationIndex,
        [bool]$DestinationIndexExisted,
        [string]$SourceEndpoint,
        [string]$SourceKey,
        [string]$DestinationEndpoint,
        [string]$DestinationKey,
        [object]$StateContext,
        [string]$ResourceName
    )

    $sourceKeyField = Get-AISearchKeyField -IndexDefinition $SourceIndex
    $indexActivity = "Index '$($SourceIndex.name)' documents"
    $sourceDocumentCount = Get-AISearchDocumentCount `
        -Endpoint $SourceEndpoint `
        -AdminKey $SourceKey `
        -IndexName $SourceIndex.name
    $resumeSupported = $sourceKeyField.filterable -eq $true -and $sourceKeyField.sortable -eq $true
    $processedCount = 0
    $copiedCount = 0
    $skippedCount = 0
    $batchCount = 0
    $lastCommittedKey = $null
    $resumeAfterKey = ""

    $resourceCheckpoint = Get-MigrationResourceCheckpoint `
        -Context $StateContext `
        -ResourceName $ResourceName
    if ($null -eq $resourceCheckpoint) {
        throw "Migration state for index '$($SourceIndex.name)' was not initialized."
    }

    $storedProgress = $resourceCheckpoint["progress"]
    if ($null -ne $storedProgress -and $storedProgress.Count -gt 0) {
        if ($storedProgress["keyField"] -ne $sourceKeyField.name) {
            throw "Index '$($SourceIndex.name)' changed key fields after checkpointing. Use -ResetState to start over."
        }
        if ([bool]$storedProgress["resumeSupported"] -ne $resumeSupported) {
            throw "Index '$($SourceIndex.name)' changed keyset paging capabilities after checkpointing. Use -ResetState to start over."
        }

        if ([long]$storedProgress["sourceDocumentCount"] -ne $sourceDocumentCount) {
            Write-Warning "Source document count changed for index '$($SourceIndex.name)'. Restarting this index from the beginning."
        }
        elseif (
            $resumeSupported -and
            -not [string]::IsNullOrEmpty([string]$storedProgress["lastCommittedKey"])
        ) {
            $lastCommittedKey = [string]$storedProgress["lastCommittedKey"]
            $resumeAfterKey = $lastCommittedKey
            $processedCount = [long]$storedProgress["processedCount"]
            $copiedCount = [long]$storedProgress["copiedCount"]
            $skippedCount = [long]$storedProgress["skippedCount"]
            $batchCount = [long]$storedProgress["batchCount"]
            Write-Host "Resuming index '$($SourceIndex.name)' after committed key '$lastCommittedKey' ($processedCount/$sourceDocumentCount processed)."
        }
        elseif ([long]$storedProgress["processedCount"] -gt 0) {
            Write-Warning "Index '$($SourceIndex.name)' has no safe keyset checkpoint. Restarting this index from the beginning."
        }
    }

    Update-AISearchDocumentCheckpoint `
        -StateContext $StateContext `
        -ResourceName $ResourceName `
        -KeyField $sourceKeyField `
        -SourceDocumentCount $sourceDocumentCount `
        -LastCommittedKey $lastCommittedKey `
        -ProcessedCount $processedCount `
        -CopiedCount $copiedCount `
        -SkippedCount $skippedCount `
        -BatchCount $batchCount
    $existingKeys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)

    if ($DifferentialMigration -and $DestinationIndexExisted) {
        $destinationKeyField = Get-AISearchKeyField -IndexDefinition $DestinationIndex
        if ($destinationKeyField.name -ne $sourceKeyField.name) {
            throw "Index '$($SourceIndex.name)' uses different source and destination key fields."
        }

        $destinationDocumentCount = Get-AISearchDocumentCount `
            -Endpoint $DestinationEndpoint `
            -AdminKey $DestinationKey `
            -IndexName $DestinationIndex.name
        $destinationKeysRead = 0
        Write-Host "Reading destination keys for differential migration: $($SourceIndex.name)"
        Write-AISearchCountProgress `
            -Id 1 `
            -ParentId 0 `
            -Activity $indexActivity `
            -Phase "Destination keys" `
            -ProcessedCount 0 `
            -TotalCount $destinationDocumentCount `
            -CurrentOperation "Comparing destination document keys"
        Get-AISearchDocuments `
            -Endpoint $DestinationEndpoint `
            -AdminKey $DestinationKey `
            -IndexDefinition $DestinationIndex `
            -KeysOnly `
            -TotalCount $destinationDocumentCount `
            -ProgressActivity $indexActivity `
            -ProgressPhase "Destination keys" | ForEach-Object {
            $destinationDocument = $_
            $keyValue = [string]$destinationDocument.PSObject.Properties[$destinationKeyField.name].Value
            [void]$existingKeys.Add($keyValue)
            $destinationKeysRead++
            if (Test-AISearchProgressCheckpoint `
                -ProcessedCount $destinationKeysRead `
                -TotalCount $destinationDocumentCount) {
                Write-AISearchCountProgress `
                    -Id 1 `
                    -ParentId 0 `
                    -Activity $indexActivity `
                    -Phase "Destination keys" `
                    -ProcessedCount $destinationKeysRead `
                    -TotalCount $destinationDocumentCount `
                    -CurrentOperation "Comparing destination document keys"
            }
        }
    }

    $nonRetrievableFields = @($SourceIndex.fields | Where-Object { $_.retrievable -eq $false })
    if ($nonRetrievableFields.Count -gt 0) {
        $fieldNames = $nonRetrievableFields.name -join ", "
        Write-Warning "Index '$($SourceIndex.name)' has non-retrievable fields that cannot be copied: $fieldNames"
    }

    $action = "upload"
    $batch = [System.Collections.Generic.List[object]]::new()
    $pendingBatches = [System.Collections.Generic.List[object]]::new()
    $batchBytes = 12
    $pendingDocumentCount = 0
    $lastProcessedKey = $lastCommittedKey
    $nextBatchSequence = $batchCount + 1

    Write-AISearchCountProgress `
        -Id 1 `
        -ParentId 0 `
        -Activity $indexActivity `
        -Phase "Source documents" `
        -ProcessedCount $processedCount `
        -TotalCount $sourceDocumentCount `
        -CurrentOperation "Copied: $copiedCount | Skipped: $skippedCount | Batches: $batchCount | Buffered: 0"

    Get-AISearchDocuments `
        -Endpoint $SourceEndpoint `
        -AdminKey $SourceKey `
        -IndexDefinition $SourceIndex `
        -TotalCount $sourceDocumentCount `
        -ProgressActivity $indexActivity `
        -ProgressPhase "Source documents" `
        -StartAfterKey $resumeAfterKey `
        -InitialProcessedCount $processedCount | ForEach-Object {
        $sourceDocument = $_
        $keyValue = [string]$sourceDocument.PSObject.Properties[$sourceKeyField.name].Value
        $documentAlreadyExists = $DifferentialMigration -and $existingKeys.Contains($keyValue)
        $writeDocument = $null
        $documentBytes = 0
        if (-not $documentAlreadyExists) {
            $writeDocument = ConvertTo-AISearchWriteDocument -Document $sourceDocument -Action $action
            $documentJson = $writeDocument | ConvertTo-Json -Depth 100 -Compress
            $documentBytes = [System.Text.Encoding]::UTF8.GetByteCount($documentJson)
            if ($documentBytes -gt $MaxBatchBytes) {
                throw "Document '$keyValue' in index '$($SourceIndex.name)' exceeds the configured maximum batch payload size."
            }
        }

        $windowFlushed = $false
        if (
            -not $documentAlreadyExists -and
            $batch.Count -gt 0 -and
            ($batchBytes + $documentBytes + 1) -gt $MaxBatchBytes
        ) {
            $pendingBatches.Add((New-AISearchDocumentBatchWorkItem `
                -Documents $batch `
                -Sequence $nextBatchSequence))
            $nextBatchSequence++
            $pendingDocumentCount += $batch.Count
            $batch.Clear()
            $batchBytes = 12
            if ($pendingBatches.Count -ge $MaxConcurrentBatches) {
                $completedBatchCount = $pendingBatches.Count
                $copiedCount += Send-AISearchDocumentBatchWindow `
                    -WorkItems $pendingBatches `
                    -Endpoint $DestinationEndpoint `
                    -AdminKey $DestinationKey `
                    -IndexName $SourceIndex.name
                $batchCount += $completedBatchCount
                $pendingBatches.Clear()
                $pendingDocumentCount = 0
                $lastCommittedKey = $lastProcessedKey
                Update-AISearchDocumentCheckpoint `
                    -StateContext $StateContext `
                    -ResourceName $ResourceName `
                    -KeyField $sourceKeyField `
                    -SourceDocumentCount $sourceDocumentCount `
                    -LastCommittedKey $lastCommittedKey `
                    -ProcessedCount $processedCount `
                    -CopiedCount $copiedCount `
                    -SkippedCount $skippedCount `
                    -BatchCount $batchCount
                $windowFlushed = $true
            }
        }

        $processedCount++
        $lastProcessedKey = $keyValue
        if ($documentAlreadyExists) {
            $skippedCount++
        }
        else {
            $batch.Add($writeDocument)
            $batchBytes += $documentBytes + 1
        }

        if ($batch.Count -ge $BatchSize) {
            $pendingBatches.Add((New-AISearchDocumentBatchWorkItem `
                -Documents $batch `
                -Sequence $nextBatchSequence))
            $nextBatchSequence++
            $pendingDocumentCount += $batch.Count
            $batch.Clear()
            $batchBytes = 12
        }

        if ($pendingBatches.Count -ge $MaxConcurrentBatches) {
            $completedBatchCount = $pendingBatches.Count
            $copiedCount += Send-AISearchDocumentBatchWindow `
                -WorkItems $pendingBatches `
                -Endpoint $DestinationEndpoint `
                -AdminKey $DestinationKey `
                -IndexName $SourceIndex.name
            $batchCount += $completedBatchCount
            $pendingBatches.Clear()
            $pendingDocumentCount = 0
            $lastCommittedKey = $lastProcessedKey
            Update-AISearchDocumentCheckpoint `
                -StateContext $StateContext `
                -ResourceName $ResourceName `
                -KeyField $sourceKeyField `
                -SourceDocumentCount $sourceDocumentCount `
                -LastCommittedKey $lastCommittedKey `
                -ProcessedCount $processedCount `
                -CopiedCount $copiedCount `
                -SkippedCount $skippedCount `
                -BatchCount $batchCount
            $windowFlushed = $true
        }

        $checkpointDue = Test-AISearchProgressCheckpoint `
            -ProcessedCount $processedCount `
            -TotalCount $sourceDocumentCount
        if ($checkpointDue -and $batch.Count -eq 0 -and $pendingBatches.Count -eq 0) {
            $lastCommittedKey = $lastProcessedKey
            Update-AISearchDocumentCheckpoint `
                -StateContext $StateContext `
                -ResourceName $ResourceName `
                -KeyField $sourceKeyField `
                -SourceDocumentCount $sourceDocumentCount `
                -LastCommittedKey $lastCommittedKey `
                -ProcessedCount $processedCount `
                -CopiedCount $copiedCount `
                -SkippedCount $skippedCount `
                -BatchCount $batchCount
        }

        if ($windowFlushed -or $checkpointDue) {
            $bufferedCount = $batch.Count + $pendingDocumentCount
            Write-AISearchCountProgress `
                -Id 1 `
                -ParentId 0 `
                -Activity $indexActivity `
                -Phase "Source documents" `
                -ProcessedCount $processedCount `
                -TotalCount $sourceDocumentCount `
                -CurrentOperation "Copied: $copiedCount | Skipped: $skippedCount | Batches: $batchCount | Buffered: $bufferedCount"
        }
    }

    if ($batch.Count -gt 0) {
        $pendingBatches.Add((New-AISearchDocumentBatchWorkItem `
            -Documents $batch `
            -Sequence $nextBatchSequence))
        $pendingDocumentCount += $batch.Count
        $batch.Clear()
        $batchBytes = 12
    }

    if ($pendingBatches.Count -gt 0) {
        $completedBatchCount = $pendingBatches.Count
        $copiedCount += Send-AISearchDocumentBatchWindow `
            -WorkItems $pendingBatches `
            -Endpoint $DestinationEndpoint `
            -AdminKey $DestinationKey `
            -IndexName $SourceIndex.name
        $batchCount += $completedBatchCount
        $pendingBatches.Clear()
        $pendingDocumentCount = 0
    }

    $lastCommittedKey = $lastProcessedKey
    Update-AISearchDocumentCheckpoint `
        -StateContext $StateContext `
        -ResourceName $ResourceName `
        -KeyField $sourceKeyField `
        -SourceDocumentCount $sourceDocumentCount `
        -LastCommittedKey $lastCommittedKey `
        -ProcessedCount $processedCount `
        -CopiedCount $copiedCount `
        -SkippedCount $skippedCount `
        -BatchCount $batchCount

    Write-AISearchCountProgress `
        -Id 1 `
        -ParentId 0 `
        -Activity $indexActivity `
        -Phase "Source documents" `
        -ProcessedCount $processedCount `
        -TotalCount $sourceDocumentCount `
        -CurrentOperation "Copied: $copiedCount | Skipped: $skippedCount | Batches: $batchCount | Buffered: 0"
    Write-AISearchProgress -Id 1 -ParentId 0 -Activity $indexActivity -Completed
    Write-Host "Completed index '$($SourceIndex.name)': copied=$copiedCount, skipped=$skippedCount"
    return [pscustomobject]@{
        CopiedCount = $copiedCount
        SkippedCount = $skippedCount
        ProcessedCount = $processedCount
        TotalCount = $sourceDocumentCount
        BatchCount = $batchCount
    }
}

$migrationState = $null
$activeMigrationResource = $null

try {
    $SourceSearchService = $SourceSearchService.Trim()
    $SourceResourceGroup = $SourceResourceGroup.Trim()
    $SourceSubscriptionId = $SourceSubscriptionId.Trim()
    $DestinationSearchService = $DestinationSearchService.Trim()
    $DestinationResourceGroup = $DestinationResourceGroup.Trim()
    $DestinationSubscriptionId = $DestinationSubscriptionId.Trim()
    $SearchDnsSuffix = $SearchDnsSuffix.Trim().TrimEnd(".")
    $ApiVersion = $ApiVersion.Trim()
    $ManagementApiVersion = $ManagementApiVersion.Trim()
    $SourceAdminKey = $SourceAdminKey.Trim()
    $DestinationAdminKey = $DestinationAdminKey.Trim()
    if ([string]::IsNullOrWhiteSpace($StateFilePath)) {
        $StateFilePath = Join-Path $PSScriptRoot "Migration-AISearch.state.json"
    }

    foreach ($serviceName in @($SourceSearchService, $DestinationSearchService)) {
        if ($serviceName -notmatch '^(?!.*--)[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])$') {
            throw "AI Search service name '$serviceName' must contain 2-60 lowercase letters, numbers, or single hyphens."
        }
    }
    if ([string]::IsNullOrWhiteSpace($SearchDnsSuffix)) {
        throw "SearchDnsSuffix cannot be empty."
    }

    $sourceEndpoint = "https://$SourceSearchService.$SearchDnsSuffix"
    $destinationEndpoint = "https://$DestinationSearchService.$SearchDnsSuffix"
    $parsedEndpoint = $null
    foreach ($endpoint in @($sourceEndpoint, $destinationEndpoint)) {
        if (-not [Uri]::TryCreate($endpoint, [UriKind]::Absolute, [ref]$parsedEndpoint)) {
            throw "AI Search endpoint '$endpoint' is not a valid absolute URI."
        }
    }

    Write-AISearchProgress `
        -Id 0 `
        -Activity "AI Search migration" `
        -Status "Connecting and discovering source resources" `
        -CurrentOperation "Resolving credentials" `
        -PercentComplete -1

    if ([string]::Equals($sourceEndpoint, $destinationEndpoint, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Source and destination AI Search services must be different."
    }

    $migrationMode = if ($DifferentialMigration) { "differential" } else { "full" }
    $stateConfiguration = [ordered]@{
        sourceService = $SourceSearchService
        sourceResourceGroup = $SourceResourceGroup
        sourceSubscriptionId = $SourceSubscriptionId
        destinationService = $DestinationSearchService
        destinationResourceGroup = $DestinationResourceGroup
        destinationSubscriptionId = $DestinationSubscriptionId
        mode = $migrationMode
        searchApiVersion = $ApiVersion
        managementApiVersion = $ManagementApiVersion
        searchDnsSuffix = $SearchDnsSuffix
    }
    $migrationState = Initialize-MigrationState `
        -MigrationType "ai_search" `
        -StateFilePath $StateFilePath `
        -Configuration $stateConfiguration `
        -Reset:$ResetState
    Write-Host "Migration state: $($migrationState.Path)"

    if ([string]::IsNullOrWhiteSpace($SourceAdminKey) -or [string]::IsNullOrWhiteSpace($DestinationAdminKey)) {
        foreach ($requiredCommand in @("Connect-AzAccount", "Set-AzContext", "Invoke-AzRestMethod")) {
            if (-not (Get-Command $requiredCommand -ErrorAction SilentlyContinue)) {
                throw "The Az.Accounts command '$requiredCommand' is required when admin keys are not supplied."
            }
        }

        Connect-AzAccount | Out-Null
    }

    $resolvedSourceKey = Get-AISearchAdminKey `
        -ProvidedKey $SourceAdminKey `
        -SubscriptionId $SourceSubscriptionId `
        -ResourceGroupName $SourceResourceGroup `
        -ServiceName $SourceSearchService
    $resolvedDestinationKey = Get-AISearchAdminKey `
        -ProvidedKey $DestinationAdminKey `
        -SubscriptionId $DestinationSubscriptionId `
        -ResourceGroupName $DestinationResourceGroup `
        -ServiceName $DestinationSearchService

    Write-Host "Starting $migrationMode AI Search migration. Destination-only indexes and documents will not be deleted."
    Write-Host "Document batch concurrency: $MaxConcurrentBatches"

    $synonymMapResource = "synonymmaps"
    if (Test-MigrationResourceCompleted `
        -Context $migrationState `
        -ResourceName $synonymMapResource) {
        Write-Host "Skipping completed synonym maps from migration state."
    }
    else {
        Start-MigrationResourceCheckpoint `
            -Context $migrationState `
            -ResourceName $synonymMapResource
        $activeMigrationResource = $synonymMapResource
        Copy-AISearchSynonymMaps `
            -SourceEndpoint $sourceEndpoint `
            -SourceKey $resolvedSourceKey `
            -DestinationEndpoint $destinationEndpoint `
            -DestinationKey $resolvedDestinationKey
        Complete-MigrationResourceCheckpoint `
            -Context $migrationState `
            -ResourceName $synonymMapResource
        $activeMigrationResource = $null
    }

    $sourceIndexesUri = New-AISearchUri -Endpoint $sourceEndpoint -RelativePath "indexes"
    $destinationIndexesUri = New-AISearchUri -Endpoint $destinationEndpoint -RelativePath "indexes"
    $sourceIndexes = @((Invoke-AISearchRequest -Method "GET" -Uri $sourceIndexesUri -AdminKey $resolvedSourceKey).value)
    $destinationIndexes = @((Invoke-AISearchRequest -Method "GET" -Uri $destinationIndexesUri -AdminKey $resolvedDestinationKey).value)
    $destinationIndexesByName = @{}
    foreach ($destinationIndex in $destinationIndexes) {
        $destinationIndexesByName[$destinationIndex.name] = $destinationIndex
    }

    $completedIndexCount = 0
    $totalCopiedCount = 0
    $totalSkippedCount = 0
    $indexNumber = 0
    Write-AISearchCountProgress `
        -Id 0 `
        -Activity "AI Search migration" `
        -Phase "Indexes" `
        -ProcessedCount 0 `
        -TotalCount $sourceIndexes.Count `
        -CurrentOperation "Ready to migrate $($sourceIndexes.Count) index(es)"

    foreach ($sourceIndex in $sourceIndexes) {
        $indexNumber++
        $resourceName = "index:$($sourceIndex.name)"
        Write-AISearchCountProgress `
            -Id 0 `
            -Activity "AI Search migration" `
            -Phase "Indexes" `
            -ProcessedCount $completedIndexCount `
            -TotalCount $sourceIndexes.Count `
            -CurrentOperation "Current index: $indexNumber/$($sourceIndexes.Count) - $($sourceIndex.name)"

        if (Test-MigrationResourceCompleted `
            -Context $migrationState `
            -ResourceName $resourceName) {
            $checkpoint = Get-MigrationResourceCheckpoint `
                -Context $migrationState `
                -ResourceName $resourceName
            $completedIndexCount++
            $totalCopiedCount += [long]$checkpoint["result"]["CopiedCount"]
            $totalSkippedCount += [long]$checkpoint["result"]["SkippedCount"]
            Write-Host "Skipping completed index from migration state: $($sourceIndex.name)"
            Write-AISearchCountProgress `
                -Id 0 `
                -Activity "AI Search migration" `
                -Phase "Indexes" `
                -ProcessedCount $completedIndexCount `
                -TotalCount $sourceIndexes.Count `
                -CurrentOperation "Documents copied: $totalCopiedCount | Skipped: $totalSkippedCount"
            continue
        }

        Start-MigrationResourceCheckpoint `
            -Context $migrationState `
            -ResourceName $resourceName
        $activeMigrationResource = $resourceName
        $destinationIndexExisted = $destinationIndexesByName.ContainsKey($sourceIndex.name)
        $destinationIndex = if ($destinationIndexExisted) {
            $destinationIndexesByName[$sourceIndex.name]
        }
        else {
            $null
        }

        if (-not $destinationIndexExisted -or -not $DifferentialMigration) {
            $writableIndex = ConvertTo-AISearchWritableDefinition -Definition $sourceIndex
            $encodedIndexName = [Uri]::EscapeDataString($sourceIndex.name)
            $destinationIndexUri = New-AISearchUri -Endpoint $destinationEndpoint -RelativePath "indexes/$encodedIndexName"
            Invoke-AISearchRequest `
                -Method "PUT" `
                -Uri $destinationIndexUri `
                -AdminKey $resolvedDestinationKey `
                -Body $writableIndex | Out-Null
            Write-Host "Migrated index definition: $($sourceIndex.name)"
        }
        else {
            Write-Host "Keeping existing destination index definition: $($sourceIndex.name)"
        }

        $indexResult = Copy-AISearchIndexDocuments `
            -SourceIndex $sourceIndex `
            -DestinationIndex $destinationIndex `
            -DestinationIndexExisted $destinationIndexExisted `
            -SourceEndpoint $sourceEndpoint `
            -SourceKey $resolvedSourceKey `
            -DestinationEndpoint $destinationEndpoint `
            -DestinationKey $resolvedDestinationKey `
            -StateContext $migrationState `
            -ResourceName $resourceName

        Complete-MigrationResourceCheckpoint `
            -Context $migrationState `
            -ResourceName $resourceName `
            -Result $indexResult
        $activeMigrationResource = $null
        $completedIndexCount++
        $totalCopiedCount += $indexResult.CopiedCount
        $totalSkippedCount += $indexResult.SkippedCount
        Write-AISearchCountProgress `
            -Id 0 `
            -Activity "AI Search migration" `
            -Phase "Indexes" `
            -ProcessedCount $completedIndexCount `
            -TotalCount $sourceIndexes.Count `
            -CurrentOperation "Documents copied: $totalCopiedCount | Skipped: $totalSkippedCount"
    }

    Complete-MigrationState `
        -Context $migrationState `
        -Summary ([ordered]@{
            IndexCount = $completedIndexCount
            CopiedCount = $totalCopiedCount
            SkippedCount = $totalSkippedCount
        })
    Write-Host "AI Search migration completed successfully. Indexes processed: $($sourceIndexes.Count), documents copied: $totalCopiedCount, documents skipped: $totalSkippedCount"
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
    Write-Error "AI Search migration failed: $migrationErrorMessage" -ErrorAction Continue
    throw
}
finally {
    Write-AISearchProgress -Id 1 -ParentId 0 -Activity "Index documents" -Completed
    Write-AISearchProgress -Id 0 -Activity "AI Search migration" -Completed
}