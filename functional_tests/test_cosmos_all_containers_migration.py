# test_cosmos_all_containers_migration.py
#!/usr/bin/env python3
"""
Functional test for all-container Azure Cosmos DB migration.
Version: 0.250.074
Implemented in: 0.250.063
Resume-state coverage added in: 0.250.064
Container-selection coverage added in: 0.250.066
REST container/feed compatibility coverage added in: 0.250.067
Per-document progress coverage added in: 0.250.068
Parallel write contract coverage added in: 0.250.069
Backpressured feed-order coverage added in: 0.250.070
Source document total coverage added in: 0.250.071
Log-only container exclusion added in: 0.250.074

This test ensures differential migration creates only missing documents, full
migration upserts source documents, requested containers can be selected, all
eligible source containers are discovered by default, file_processing is
always skipped, and settings/app_settings is never migrated.
"""

from pathlib import Path
import re
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "Migration-Cosmos.ps1"


def test_cosmos_all_containers_migration() -> None:
    """Exercise differential and full migration against mocked Cosmos APIs."""
    powershell = shutil.which("pwsh")
    if not powershell:
        raise AssertionError("PowerShell 7 is required to test the migration script.")

    script_content = SCRIPT_PATH.read_text(encoding="utf-8")
    for expected_contract in (
        "#Requires -Version 7.0",
        '$adminSettingsContainerName = "settings"',
        '$adminSettingsDocumentId = "app_settings"',
        '$excludedMigrationContainerNames = [string[]]@("file_processing")',
        '"x-ms-documentdb-is-upsert"',
        "listKeys?api-version=$ManagementApiVersion",
        'throw "Source and destination Cosmos DB account/database pairs must be different."',
        '[string[]]$Containers = @()',
        '[int]$MaxConcurrentDocuments = 8',
        'ForEach-Object -Parallel',
        '-ThrottleLimit $MaxConcurrentDocuments',
    ):
        if expected_contract not in script_content:
            raise AssertionError(f"Missing migration contract: {expected_contract}")
    if "foreach ($document in Get-CosmosDocuments" in script_content:
        raise AssertionError(
            "Cosmos document feeds must be consumed as streaming pipelines, not buffered foreach expressions."
        )

    for parameter_name in (
        "SourceCosmosAccount",
        "SourceResourceGroup",
        "SourceSubscriptionId",
        "SourceDatabaseName",
        "DestinationCosmosAccount",
        "DestinationResourceGroup",
        "DestinationSubscriptionId",
        "DestinationDatabaseName",
    ):
        if not re.search(rf"\[string\]\${parameter_name}\s*=", script_content):
            raise AssertionError(
                f"Migration parameter '{parameter_name}' must have an editable default."
            )

    script_path = str(SCRIPT_PATH).replace("'", "''")
    harness = rf'''
$ErrorActionPreference = "Stop"
$scriptPath = '{script_path}'
$global:mockDestinationDatabaseExists = $false
$global:mockConnectCount = 0
$global:mockContextCalls = @()
$global:mockArmKeyPaths = @()
$global:mockContainerCreates = @()
$global:mockContainerUpdates = @()
$global:mockDocumentWrites = @()
$global:mockDocumentFeedRecords = @()
$global:mockMigrationEvents = @()
$global:mockContainerListRecords = @()
$global:mockSleepCalls = @()
$global:mockProgressRecords = @()
$global:mockTransientFailuresRemaining = 1

function New-MockContainer {{
    param(
        [string]$Name,
        [string[]]$PartitionKeyPaths,
        [long]$DocumentCount
    )

    return [pscustomobject]@{{
        id = $Name
        partitionKey = [pscustomobject]@{{
            paths = @($PartitionKeyPaths)
            kind = "Hash"
            version = 2
            systemKey = $null
        }}
        indexingPolicy = [pscustomobject]@{{
            automatic = $true
            indexingMode = "consistent"
            includedPaths = @([pscustomobject]@{{ path = "/*"; indexes = $null }})
            excludedPaths = @()
            compositeIndexes = $null
            spatialIndexes = $null
            vectorIndexes = $null
        }}
        analyticalStorageTtl = $null
        backupPolicy = [pscustomobject]@{{ type = 1 }}
        clientEncryptionPolicy = $null
        computedProperties = $null
        conflictResolutionPolicy = [pscustomobject]@{{
            conflictResolutionPath = "/_ts"
            conflictResolutionProcedure = ""
            mode = "LastWriterWins"
        }}
        createMode = $null
        defaultTtl = $null
        etag = '"mock-arm-etag"'
        fullTextPolicy = $null
        geospatialConfig = [pscustomobject]@{{ type = "Geography" }}
        restoreParameters = $null
        rid = "arm-$Name"
        statistics = @([pscustomobject]@{{ documentCount = $DocumentCount; id = "0" }})
        ts = 1.0
        uniqueKeyPolicy = $null
        vectorEmbeddingPolicy = $null
        _rid = "system-$Name"
        _self = "dbs/mock/colls/$Name"
        _etag = '"mock"'
        _ts = 1
    }}
}}

$global:mockSourceContainers = @(
    (New-MockContainer -Name "settings" -PartitionKeyPaths @("/id") -DocumentCount 2)
    (New-MockContainer -Name "documents" -PartitionKeyPaths @("/user_id") -DocumentCount 2)
    (New-MockContainer -Name "agent_templates" -PartitionKeyPaths @("/scope/id") -DocumentCount 1)
    (New-MockContainer -Name "file_processing" -PartitionKeyPaths @("/id") -DocumentCount 1)
)
$global:mockDestinationContainers = @(
    (New-MockContainer -Name "settings" -PartitionKeyPaths @("/id") -DocumentCount 2)
    (New-MockContainer -Name "documents" -PartitionKeyPaths @("/user_id") -DocumentCount 2)
)
$global:mockSourceDocuments = @{{
    settings = @(
        [pscustomobject]@{{ id = "app_settings"; secret = "must-not-migrate"; _rid = "settings-1" }}
        [pscustomobject]@{{ id = "cache_state"; value = 7; _etag = '"source"'; _ts = 10 }}
    )
    documents = @(
        [pscustomobject]@{{ id = "existing-doc"; user_id = "user-a"; content = "source existing"; _self = "source-only" }}
        [pscustomobject]@{{ id = "new-doc"; user_id = "user-b"; content = "source new"; _attachments = "attachments/" }}
    )
    agent_templates = @(
        [pscustomobject]@{{ id = "template-1"; scope = [pscustomobject]@{{ id = "global" }}; name = "Template" }}
    )
    file_processing = @(
        [pscustomobject]@{{ id = "processing-log-1"; status = "Complete" }}
    )
}}
$global:mockDestinationDocuments = @{{
    settings = @{{
        app_settings = [pscustomobject]@{{ id = "app_settings"; secret = "destination-value" }}
        destination_only = [pscustomobject]@{{ id = "destination_only"; value = "keep" }}
    }}
    documents = @{{
        "existing-doc" = [pscustomobject]@{{ id = "existing-doc"; user_id = "user-a"; content = "destination existing" }}
        "destination-doc" = [pscustomobject]@{{ id = "destination-doc"; user_id = "user-c"; content = "keep" }}
    }}
    agent_templates = @{{}}
}}

function New-MockWebResponse {{
    param(
        [int]$StatusCode,
        [AllowNull()]
        [object]$Body = $null,
        [hashtable]$Headers = @{{}}
    )

    $content = if ($null -eq $Body) {{
        ""
    }}
    elseif ($Body -is [string]) {{
        $Body
    }}
    else {{
        ConvertTo-Json -InputObject $Body -Depth 100 -Compress
    }}
    return [pscustomobject]@{{
        StatusCode = $StatusCode
        Headers = $Headers
        Content = $content
    }}
}}

function Write-Progress {{
    [CmdletBinding()]
    param(
        [int]$Id,
        [int]$ParentId = -1,
        [string]$Activity,
        [string]$Status,
        [string]$CurrentOperation,
        [int]$PercentComplete,
        [switch]$Completed
    )

    $global:mockProgressRecords = @($global:mockProgressRecords) + [pscustomobject]@{{
        Id = $Id
        ParentId = $ParentId
        Activity = $Activity
        Status = $Status
        CurrentOperation = $CurrentOperation
        PercentComplete = $PercentComplete
        Completed = $Completed.IsPresent
    }}
}}

function Start-Sleep {{
    [CmdletBinding()]
    param([int]$Milliseconds)

    $global:mockSleepCalls = @($global:mockSleepCalls) + $Milliseconds
}}

function Connect-AzAccount {{
    [CmdletBinding()]
    param()

    $global:mockConnectCount++
}}

function Set-AzContext {{
    [CmdletBinding()]
    param([string]$SubscriptionId)

    $global:mockContextCalls = @($global:mockContextCalls) + $SubscriptionId
    return [pscustomobject]@{{ SubscriptionId = $SubscriptionId }}
}}

function Invoke-AzRestMethod {{
    [CmdletBinding()]
    param(
        [string]$Method,
        [string]$Path
    )

    $global:mockArmKeyPaths = @($global:mockArmKeyPaths) + $Path
    return [pscustomobject]@{{
        StatusCode = 200
        Content = '{{"primaryMasterKey":"YXV0by1yZXNvbHZlZC1rZXk="}}'
    }}
}}

function Invoke-WebRequest {{
    [CmdletBinding()]
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers,
        [AllowNull()]
        [string]$Body,
        [string]$ContentType,
        [switch]$SkipHttpErrorCheck
    )

    $isSource = $Uri.StartsWith("https://source-cosmos.")
    $isDestination = $Uri.StartsWith("https://destination-cosmos.")
    if (-not $isSource -and -not $isDestination) {{
        throw "Unexpected Cosmos endpoint: $Uri"
    }}

    if ($Method -eq "GET" -and $Uri -match "/dbs/SimpleChat$") {{
        if ($isSource -or $global:mockDestinationDatabaseExists) {{
            return New-MockWebResponse -StatusCode 200 -Body @{{ id = "SimpleChat" }}
        }}
        return New-MockWebResponse -StatusCode 404 -Body @{{ code = "NotFound" }}
    }}

    if ($Method -eq "POST" -and $Uri -match "/dbs$") {{
        $database = $Body | ConvertFrom-Json
        if (-not $isDestination -or $database.id -ne "SimpleChat") {{
            throw "Unexpected database create request."
        }}
        $global:mockDestinationDatabaseExists = $true
        return New-MockWebResponse -StatusCode 201 -Body @{{ id = "SimpleChat" }}
    }}

    if ($Method -eq "GET" -and $Uri -match "/dbs/SimpleChat/colls$") {{
        $containers = if ($isSource) {{
            $global:mockSourceContainers
        }}
        else {{
            $global:mockDestinationContainers
        }}
        $offset = 0
        if ($Headers.ContainsKey("x-ms-continuation")) {{
            $offset = [int]$Headers["x-ms-continuation"]
        }}
        $pageSize = [int]$Headers["x-ms-max-item-count"]
        $page = @($containers | Select-Object -Skip $offset -First $pageSize)
        $nextOffset = $offset + $page.Count
        $responseHeaders = @{{}}
        if ($nextOffset -lt $containers.Count) {{
            $responseHeaders["x-ms-continuation"] = [string]$nextOffset
        }}
        $global:mockContainerListRecords = @($global:mockContainerListRecords) + [pscustomobject]@{{
            IsSource = $isSource
            Continuation = [string]$Headers["x-ms-continuation"]
            Count = $page.Count
        }}
        return New-MockWebResponse `
            -StatusCode 200 `
            -Body @{{ DocumentCollections = $page }} `
            -Headers $responseHeaders
    }}

    if ($Method -eq "POST" -and $Uri -match "/dbs/SimpleChat/colls$") {{
        $container = $Body | ConvertFrom-Json -Depth 100
        $global:mockContainerCreates = @($global:mockContainerCreates) + $container
        $global:mockDestinationContainers = @($global:mockDestinationContainers) + $container
        $global:mockDestinationDocuments[$container.id] = @{{}}
        return New-MockWebResponse -StatusCode 201 -Body $container
    }}

    if ($Method -eq "PUT" -and $Uri -match "/dbs/SimpleChat/colls/([^/]+)$") {{
        $container = $Body | ConvertFrom-Json -Depth 100
        $global:mockContainerUpdates = @($global:mockContainerUpdates) + $container
        return New-MockWebResponse -StatusCode 200 -Body $container
    }}

    if ($Method -eq "GET" -and $Uri -match "/dbs/SimpleChat/colls/([^/]+)/docs$") {{
        $containerName = [Uri]::UnescapeDataString($Matches[1])
        $continuationValue = [string]$Headers["x-ms-continuation"]
        $global:mockMigrationEvents = @($global:mockMigrationEvents) + "source-feed:$containerName`:$continuationValue"
        $global:mockDocumentFeedRecords = @($global:mockDocumentFeedRecords) + [pscustomobject]@{{
            ContainerName = $containerName
            Continuation = $continuationValue
        }}
        $documents = @($global:mockSourceDocuments[$containerName])
        $offset = 0
        if ($Headers.ContainsKey("x-ms-continuation")) {{
            $offset = [int]$Headers["x-ms-continuation"]
        }}
        $pageSize = [int]$Headers["x-ms-max-item-count"]
        $page = @($documents | Select-Object -Skip $offset -First $pageSize)
        $nextOffset = $offset + $page.Count
        $responseHeaders = @{{}}
        if ($nextOffset -lt $documents.Count) {{
            $responseHeaders["x-ms-continuation"] = [string]$nextOffset
        }}
        return New-MockWebResponse `
            -StatusCode 200 `
            -Body @{{ Documents = $page; _count = $page.Count }} `
            -Headers $responseHeaders
    }}

    if ($Method -eq "POST" -and $Uri -match "/dbs/SimpleChat/colls/([^/]+)/docs$") {{
        $containerName = [Uri]::UnescapeDataString($Matches[1])
        $document = $Body | ConvertFrom-Json -Depth 100
        $global:mockMigrationEvents = @($global:mockMigrationEvents) + "destination-write:$containerName`:$($document.id)"
        $global:mockDocumentWrites = @($global:mockDocumentWrites) + [pscustomobject]@{{
            ContainerName = $containerName
            Document = $document
            PartitionKey = [string]$Headers["x-ms-documentdb-partitionkey"]
            IsUpsert = [string]$Headers["x-ms-documentdb-is-upsert"]
            ContentType = $ContentType
        }}

        if ($document.id -eq "new-doc" -and $global:mockTransientFailuresRemaining -gt 0) {{
            $global:mockTransientFailuresRemaining--
            return New-MockWebResponse `
                -StatusCode 429 `
                -Body @{{ code = "TooManyRequests" }} `
                -Headers @{{ "x-ms-retry-after-ms" = "7" }}
        }}

        $existing = $global:mockDestinationDocuments[$containerName].ContainsKey($document.id)
        $isUpsert = $Headers.ContainsKey("x-ms-documentdb-is-upsert")
        if ($existing -and -not $isUpsert) {{
            return New-MockWebResponse -StatusCode 409 -Body @{{ code = "Conflict" }}
        }}
        $global:mockDestinationDocuments[$containerName][$document.id] = $document
        $statusCode = if ($existing) {{ 200 }} else {{ 201 }}
        return New-MockWebResponse -StatusCode $statusCode -Body $document
    }}

    throw "Unexpected mock request: $Method $Uri"
}}

$sourceSubscriptionId = "00000000-0000-0000-0000-000000000001"
$destinationSubscriptionId = "00000000-0000-0000-0000-000000000002"
$stateDirectory = Join-Path ([IO.Path]::GetTempPath()) "simplechat-cosmos-state-$PID-$([Guid]::NewGuid().ToString('N'))"
[IO.Directory]::CreateDirectory($stateDirectory) | Out-Null
$differentialStatePath = Join-Path $stateDirectory "differential.json"
$subsetStatePath = Join-Path $stateDirectory "subset.json"
$singleStatePath = Join-Path $stateDirectory "single.json"
$missingStatePath = Join-Path $stateDirectory "missing.json"
$fullStatePath = Join-Path $stateDirectory "full.json"
$armStatePath = Join-Path $stateDirectory "arm.json"
$commonParameters = @{{
    SourceCosmosAccount = " source-cosmos "
    SourceResourceGroup = " source-rg "
    SourceSubscriptionId = " $sourceSubscriptionId "
    SourceDatabaseName = " SimpleChat "
    DestinationCosmosAccount = " destination-cosmos "
    DestinationResourceGroup = " destination-rg "
    DestinationSubscriptionId = " $destinationSubscriptionId "
    DestinationDatabaseName = " SimpleChat "
    SourcePrimaryKey = " c291cmNlLWtleQ== "
    DestinationPrimaryKey = " ZGVzdGluYXRpb24ta2V5 "
    PageSize = 1
    ProgressUpdateInterval = 1
    MaxConcurrentDocuments = 1
    StateFilePath = $differentialStatePath
}}

& $scriptPath @commonParameters -DifferentialMigration $true -ShowProgress $true

if (-not $global:mockDestinationDatabaseExists) {{
    throw "Differential migration did not create the missing destination database."
}}
if ($global:mockContainerCreates.Count -ne 1 -or $global:mockContainerCreates[0].id -ne "agent_templates") {{
    throw "Differential migration did not create only the missing container."
}}
if ($global:mockContainerCreates[0].PSObject.Properties["_rid"]) {{
    throw "Created container included source system properties."
}}
$createdContainer = $global:mockContainerCreates[0]
foreach ($readOnlyProperty in @(
    "backupPolicy",
    "createMode",
    "etag",
    "restoreParameters",
    "rid",
    "statistics",
    "ts"
)) {{
    if ($createdContainer.PSObject.Properties[$readOnlyProperty]) {{
        throw "Created container retained read-only property '$readOnlyProperty'."
    }}
}}
if ($createdContainer.partitionKey.PSObject.Properties["systemKey"]) {{
    throw "Created container retained partitionKey.systemKey."
}}
if ($createdContainer.indexingPolicy.includedPaths[0].PSObject.Properties["indexes"]) {{
    throw "Created container retained a null nested indexing property."
}}
if (
    $createdContainer.indexingPolicy.includedPaths -isnot [array] -or
    $createdContainer.indexingPolicy.excludedPaths -isnot [array]
) {{
    throw "Created container indexing paths were not serialized as JSON arrays."
}}
if (
    $createdContainer.conflictResolutionPolicy.mode -ne "LastWriterWins" -or
    $createdContainer.geospatialConfig.type -ne "Geography"
) {{
    throw "Created container dropped supported source policies."
}}
if ($global:mockContainerUpdates.Count -ne 0) {{
    throw "Differential migration unexpectedly replaced a destination container definition."
}}
$sourceContainerPages = @($global:mockContainerListRecords | Where-Object {{ $_.IsSource }})
if ($sourceContainerPages.Count -ne 4 -or $sourceContainerPages[3].Continuation -ne "3") {{
    throw "Source container continuation paging was not followed."
}}

$differentialWrites = @($global:mockDocumentWrites)
$differentialIds = @($differentialWrites.Document.id | Sort-Object -Unique)
if (($differentialIds -join ",") -ne "cache_state,existing-doc,new-doc,template-1") {{
    throw "Differential migration wrote an unexpected document set: $($differentialIds -join ',')"
}}
if ($differentialIds -contains "app_settings") {{
    throw "Differential migration attempted to write admin app settings."
}}
if (@($global:mockDocumentFeedRecords | Where-Object {{ $_.ContainerName -eq "file_processing" }}).Count -gt 0) {{
    throw "Differential migration read the excluded file_processing log container."
}}
if (@($differentialWrites | Where-Object {{ $_.IsUpsert -eq "true" }}).Count -gt 0) {{
    throw "Differential migration enabled upsert and could overwrite destination documents."
}}
if (@($differentialWrites | Where-Object {{ $_.ContentType -ne "application/json" }}).Count -gt 0) {{
    throw "Document writes did not use the Cosmos JSON content type."
}}
if ($global:mockDestinationDocuments.settings.app_settings.secret -ne "destination-value") {{
    throw "Differential migration changed destination admin app settings."
}}
if ($global:mockDestinationDocuments.documents["existing-doc"].content -ne "destination existing") {{
    throw "Differential migration overwrote an existing destination document."
}}
if ($global:mockDestinationDocuments.documents["destination-doc"].content -ne "keep") {{
    throw "Differential migration removed or changed a destination-only document."
}}

$newDocumentWrite = @($differentialWrites | Where-Object {{ $_.Document.id -eq "new-doc" }})[-1]
if ($newDocumentWrite.PartitionKey -ne '["user-b"]') {{
    throw "Document partition-key header was not derived from the container definition."
}}
$templateWrite = @($differentialWrites | Where-Object {{ $_.Document.id -eq "template-1" }})[-1]
if ($templateWrite.PartitionKey -ne '["global"]') {{
    throw "Nested partition-key paths were not resolved correctly."
}}
if ($newDocumentWrite.Document.PSObject.Properties["_attachments"]) {{
    throw "Document writes retained Cosmos-managed system properties."
}}
if (@($global:mockSleepCalls).Count -ne 1 -or $global:mockSleepCalls[0] -ne 7) {{
    throw "Cosmos 429 retry delay was not honored."
}}

$settingsFeedPages = @($global:mockDocumentFeedRecords | Where-Object {{ $_.ContainerName -eq "settings" }})
if ($settingsFeedPages.Count -ne 2 -or $settingsFeedPages[1].Continuation -ne "1") {{
    throw "Settings documents were not read through the paged document feed."
}}

$documentFeedPages = @($global:mockDocumentFeedRecords | Where-Object {{ $_.ContainerName -eq "documents" }})
if ($documentFeedPages.Count -ne 2 -or $documentFeedPages[1].Continuation -ne "1") {{
    throw "Source document read-feed continuation paging was not followed."
}}
$firstDocumentWriteIndex = [Array]::IndexOf(
    $global:mockMigrationEvents,
    "destination-write:documents:existing-doc"
)
$secondDocumentPageIndex = [Array]::IndexOf(
    $global:mockMigrationEvents,
    "source-feed:documents:1"
)
if (
    $firstDocumentWriteIndex -lt 0 -or
    $secondDocumentPageIndex -lt 0 -or
    $firstDocumentWriteIndex -gt $secondDocumentPageIndex
) {{
    throw "The source document feed was buffered instead of writing page 1 before requesting page 2."
}}

$overallProgress = @($global:mockProgressRecords | Where-Object {{
    $_.Id -eq 0 -and
    $_.PercentComplete -eq 33 -and
    $_.Status -eq "Containers: 1/3 | Remaining: 2 | 33%"
}})
if ($overallProgress.Count -eq 0) {{
    throw "Overall migration progress did not report the expected container checkpoint."
}}
$documentTotalProgress = @($global:mockProgressRecords | Where-Object {{
    $_.Id -eq 1 -and
    $_.Activity -eq "Container 'documents' documents" -and
    $_.Status -eq "Source documents: 1/2 | Remaining: 1 | 50%"
}})
if ($documentTotalProgress.Count -eq 0) {{
    throw "Document progress did not report processed, total, remaining, and percentage values."
}}
$copyingProgress = @($global:mockProgressRecords | Where-Object {{
    $_.Id -eq 1 -and $_.CurrentOperation -match "^Copying document \d+: '([^']+)'"
}})
$copyingDocumentIds = @($copyingProgress | ForEach-Object {{
    if ($_.CurrentOperation -match "^Copying document \d+: '([^']+)'") {{
        $Matches[1]
    }}
}} | Sort-Object -Unique)
if (($copyingDocumentIds -join ",") -ne "cache_state,existing-doc,new-doc,template-1") {{
    throw "Per-document progress did not identify every source document: $($copyingDocumentIds -join ',')"
}}
$completedDocumentProgress = @($global:mockProgressRecords | Where-Object {{
    $_.Id -eq 1 -and
    $_.CurrentOperation -match "^(Copied|Skipped) document \d+: '[^']+' \| Copied: \d+ \| Skipped: \d+$"
}})
if ($completedDocumentProgress.Count -lt 4) {{
    throw "Per-document progress did not report each document result and cumulative counts."
}}

$differentialStateJson = [IO.File]::ReadAllText($differentialStatePath)
$differentialState = $differentialStateJson | ConvertFrom-Json -AsHashtable -Depth 100
if ($differentialState.status -ne "completed" -or $differentialState.resources.Count -ne 3) {{
    throw "Differential migration state did not record all completed containers."
}}
if (@($differentialState.resources.Values | Where-Object {{ $_.status -ne "completed" }}).Count -gt 0) {{
    throw "Differential migration state contains a non-completed container."
}}
if ($differentialStateJson -match "c291cmNlLWtleQ|ZGVzdGluYXRpb24ta2V5|must-not-migrate") {{
    throw "Migration state persisted a key or excluded admin setting."
}}

$writeCountBeforeResume = $global:mockDocumentWrites.Count
$createCountBeforeResume = $global:mockContainerCreates.Count
$updateCountBeforeResume = $global:mockContainerUpdates.Count
& $scriptPath @commonParameters -DifferentialMigration $true -ShowProgress $false
if (
    $global:mockDocumentWrites.Count -ne $writeCountBeforeResume -or
    $global:mockContainerCreates.Count -ne $createCountBeforeResume -or
    $global:mockContainerUpdates.Count -ne $updateCountBeforeResume
) {{
    throw "Resumed differential migration repeated a completed container write."
}}
$resumedState = [IO.File]::ReadAllText($differentialStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if ($resumedState.status -ne "completed" -or $resumedState.resumeCount -ne 1) {{
    throw "Resumed differential migration did not retain and complete its state."
}}

$global:mockContainerCreates = @()
$global:mockContainerUpdates = @()
$global:mockDocumentWrites = @()
$global:mockDocumentFeedRecords = @()
$subsetParameters = $commonParameters.Clone()
$subsetParameters.StateFilePath = $subsetStatePath
$subsetParameters.Containers = @(" settings ", "documents", "file_processing")
& $scriptPath @subsetParameters -DifferentialMigration $true -ShowProgress $false

if ($global:mockContainerCreates.Count -ne 0 -or $global:mockContainerUpdates.Count -ne 0) {{
    throw "Selected-container migration changed an unrequested container definition."
}}
$subsetWriteContainers = @($global:mockDocumentWrites.ContainerName | Sort-Object -Unique)
if (($subsetWriteContainers -join ",") -ne "documents,settings") {{
    throw "Selected-container migration wrote an unexpected container set: $($subsetWriteContainers -join ',')"
}}
$subsetFeedContainers = @($global:mockDocumentFeedRecords.ContainerName | Sort-Object -Unique)
if (($subsetFeedContainers -join ",") -ne "documents,settings") {{
    throw "Selected-container migration read an unexpected container set: $($subsetFeedContainers -join ',')"
}}
$subsetState = [IO.File]::ReadAllText($subsetStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if (
    $subsetState.resources.Count -ne 2 -or
    ($subsetState.configuration.containers -join ",") -ne "documents,settings" -or
    $subsetState.configuration.containerSelectionMode -ne "explicit"
) {{
    throw "Selected-container migration state did not record the normalized scope."
}}

$global:mockContainerCreates = @()
$global:mockContainerUpdates = @()
$global:mockDocumentWrites = @()
$global:mockDocumentFeedRecords = @()
$singleParameters = $commonParameters.Clone()
$singleParameters.StateFilePath = $singleStatePath
$singleParameters.Containers = "documents"
& $scriptPath @singleParameters -DifferentialMigration $true -ShowProgress $false
$singleWriteContainers = @($global:mockDocumentWrites.ContainerName | Sort-Object -Unique)
$singleFeedContainers = @($global:mockDocumentFeedRecords.ContainerName | Sort-Object -Unique)
$singleState = [IO.File]::ReadAllText($singleStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if (
    ($singleWriteContainers -join ",") -ne "documents" -or
    ($singleFeedContainers -join ",") -ne "documents" -or
    $singleState.resources.Count -ne 1 -or
    $singleState.configuration.containers[0] -ne "documents"
) {{
    throw "Single-container migration did not restrict work and state to documents."
}}

$selectionMismatchRejected = $false
$subsetParameters.Containers = @("documents")
try {{
    & $scriptPath @subsetParameters -DifferentialMigration $true -ShowProgress $false
}}
catch {{
    if ($_ -match "does not match the current source, destination, or mode") {{
        $selectionMismatchRejected = $true
    }}
    else {{
        throw
    }}
}}
if (-not $selectionMismatchRejected) {{
    throw "A checkpoint from a different container selection was accepted."
}}

$missingContainerRejected = $false
$missingParameters = $commonParameters.Clone()
$missingParameters.StateFilePath = $missingStatePath
$missingParameters.Containers = @("missing-container")
try {{
    & $scriptPath @missingParameters -DifferentialMigration $true -ShowProgress $false
}}
catch {{
    if ($_ -match "Requested Cosmos DB container\(s\) were not found.*missing-container") {{
        $missingContainerRejected = $true
    }}
    else {{
        throw
    }}
}}
if (-not $missingContainerRejected -or [IO.File]::Exists($missingStatePath)) {{
    throw "A missing requested container was not rejected before state initialization."
}}

$global:mockContainerCreates = @()
$global:mockContainerUpdates = @()
$global:mockDocumentWrites = @()
$global:mockDocumentFeedRecords = @()
$global:mockSleepCalls = @()
$global:mockTransientFailuresRemaining = 0

$fullParameters = $commonParameters.Clone()
$fullParameters.StateFilePath = $fullStatePath
& $scriptPath @fullParameters -DifferentialMigration $false -ShowProgress $true

$updatedContainerNames = @($global:mockContainerUpdates.id | Sort-Object)
if (($updatedContainerNames -join ",") -ne "agent_templates,documents,settings") {{
    throw "Full migration did not update every source container definition."
}}
if ($global:mockContainerCreates.Count -ne 0) {{
    throw "Full migration unexpectedly recreated existing destination containers."
}}
$fullWrites = @($global:mockDocumentWrites)
$fullIds = @($fullWrites.Document.id | Sort-Object -Unique)
if (($fullIds -join ",") -ne "cache_state,existing-doc,new-doc,template-1") {{
    throw "Full migration wrote an unexpected document set: $($fullIds -join ',')"
}}
if (@($fullWrites | Where-Object {{ $_.IsUpsert -ne "true" }}).Count -gt 0) {{
    throw "Full migration did not use upsert for every source document."
}}
if ($global:mockDestinationDocuments.documents["existing-doc"].content -ne "source existing") {{
    throw "Full migration did not replace an existing destination document."
}}
if ($global:mockDestinationDocuments.settings.app_settings.secret -ne "destination-value") {{
    throw "Full migration changed destination admin app settings."
}}
if ($global:mockDestinationDocuments.documents["destination-doc"].content -ne "keep") {{
    throw "Full migration removed or changed a destination-only document."
}}

$armParameters = $commonParameters.Clone()
$armParameters.SourcePrimaryKey = " "
$armParameters.DestinationPrimaryKey = " "
$armParameters.StateFilePath = $armStatePath
& $scriptPath @armParameters -DifferentialMigration $true -ShowProgress $false

if ($global:mockConnectCount -ne 1) {{
    throw "Automatic key resolution did not connect exactly once; observed $global:mockConnectCount connection(s)."
}}
if ($global:mockArmKeyPaths.Count -ne 2) {{
    throw "Automatic key resolution did not request both account keys."
}}
if ($global:mockArmKeyPaths[0] -notmatch "/subscriptions/$sourceSubscriptionId/resourceGroups/source-rg/.*/source-cosmos/listKeys\?api-version=2025-04-15$") {{
    throw "Source key lookup used an unexpected ARM path: $($global:mockArmKeyPaths[0])"
}}
if ($global:mockArmKeyPaths[1] -notmatch "/subscriptions/$destinationSubscriptionId/resourceGroups/destination-rg/.*/destination-cosmos/listKeys\?api-version=2025-04-15$") {{
    throw "Destination key lookup used an unexpected ARM path: $($global:mockArmKeyPaths[1])"
}}
[IO.Directory]::Delete($stateDirectory, $true)
'''

    result = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", harness],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise AssertionError(
            f"Cosmos migration harness failed with exit code {result.returncode}."
        )


if __name__ == "__main__":
    test_cosmos_all_containers_migration()
    print("Cosmos all-container migration test passed.")