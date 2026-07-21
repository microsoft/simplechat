# test_ai_search_all_indexes_migration.py
#!/usr/bin/env python3
"""
Functional test for all-index Azure AI Search migration.
Version: 0.250.065
Implemented in: 0.250.065
Resume-state coverage added in: 0.250.064

This test ensures differential migration copies only missing document keys and
missing index definitions, while full migration overwrites source-key matches
across every source index without deleting destination-only content.
"""

from pathlib import Path
import re
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "Migration-AISearch.ps1"


def test_ai_search_all_indexes_migration() -> None:
    """Exercise differential and full migration against mocked Search REST APIs."""
    powershell = shutil.which("pwsh")
    if not powershell:
        raise AssertionError("PowerShell 7 is required to test the migration script.")

    script_content = SCRIPT_PATH.read_text(encoding="utf-8")
    for expected_contract in (
        "#Requires -Version 7.0",
        "listAdminKeys?api-version=$ManagementApiVersion",
        "Write-AISearchCountProgress",
        'throw "Source and destination AI Search services must be different."',
    ):
        if expected_contract not in script_content:
            raise AssertionError(f"Missing migration contract: {expected_contract}")

    for parameter_name in (
        "SourceSearchService",
        "SourceResourceGroup",
        "SourceSubscriptionId",
        "DestinationSearchService",
        "DestinationResourceGroup",
        "DestinationSubscriptionId",
    ):
        parameter_pattern = rf"\[string\]\${parameter_name}\s*="
        if not re.search(parameter_pattern, script_content):
            raise AssertionError(
                f"Migration parameter '{parameter_name}' must have an editable default."
            )

    script_path = str(SCRIPT_PATH).replace("'", "''")
    harness = rf'''
$ErrorActionPreference = "Stop"
$scriptPath = '{script_path}'

function New-MockIndex {{
    param([string]$Name)

    return [pscustomobject]@{{
        name = $Name
        fields = @(
            [pscustomobject]@{{
                name = "id"
                type = "Edm.String"
                key = $true
                retrievable = $true
                filterable = $true
                sortable = $true
            }}
            [pscustomobject]@{{
                name = "content"
                type = "Edm.String"
                key = $false
                retrievable = $true
                filterable = $false
                sortable = $false
            }}
        )
    }}
}}

$script:sourceIndexes = @(
    (New-MockIndex -Name "index-a")
    (New-MockIndex -Name "index-b")
)
$script:destinationIndexes = @($script:sourceIndexes[0])
$script:sourceDocuments = @{{
    "index-a" = @(
        [pscustomobject]@{{ id = "existing-a"; content = "source existing" }}
        [pscustomobject]@{{ id = "new-a"; content = "source new" }}
    )
    "index-b" = @(
        [pscustomobject]@{{ id = "new-b-1"; content = "source b1" }}
        [pscustomobject]@{{ id = "new-b-2"; content = "source b2" }}
    )
}}
$script:destinationDocuments = @{{
    "index-a" = @(
        [pscustomobject]@{{ id = "existing-a"; content = "destination existing" }}
        [pscustomobject]@{{ id = "destination-only"; content = "keep me" }}
    )
}}
$script:indexPuts = @()
$script:documentWrites = @()
$script:transientFailuresRemaining = 1
$script:sleepCalls = @()
$script:progressRecords = @()
$script:migrationEvents = @()
$script:requestTimeouts = @()
$script:permanentFailureKey = $null

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

    $script:progressRecords += [pscustomobject]@{{
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
    param([int]$Seconds)

    $script:sleepCalls += $Seconds
}}

function Invoke-RestMethod {{
    [CmdletBinding()]
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers,
        [string]$ContentType,
        [string]$Body,
        [int]$TimeoutSec
    )

    $script:requestTimeouts += $TimeoutSec

    if ($Method -eq "GET" -and $Uri -match "/synonymmaps\?api-version=") {{
        return [pscustomobject]@{{ value = @() }}
    }}

    if ($Method -eq "GET" -and $Uri -match "/indexes\?api-version=") {{
        if ($Uri.StartsWith("https://source-search.")) {{
            return [pscustomobject]@{{ value = $script:sourceIndexes }}
        }}
        return [pscustomobject]@{{ value = $script:destinationIndexes }}
    }}

    if ($Method -eq "GET" -and $Uri -match "/indexes/([^/]+)/docs/\$count\?api-version=") {{
        $indexName = [Uri]::UnescapeDataString($Matches[1])
        if ($Uri.StartsWith("https://source-search.")) {{
            return [long]@($script:sourceDocuments[$indexName]).Count
        }}
        return [long]@($script:destinationDocuments[$indexName]).Count
    }}

    if ($Method -eq "PUT" -and $Uri -match "/indexes/([^/?]+)\?api-version=") {{
        $script:indexPuts += [Uri]::UnescapeDataString($Matches[1])
        return $Body | ConvertFrom-Json
    }}

    if ($Method -eq "POST" -and $Uri -match "/indexes/([^/]+)/docs/search\?api-version=") {{
        $indexName = [Uri]::UnescapeDataString($Matches[1])
        $searchRequest = $Body | ConvertFrom-Json
        if ($Uri.StartsWith("https://source-search.")) {{
            $script:migrationEvents += "source-page:$indexName"
            $documents = @($script:sourceDocuments[$indexName])
        }}
        else {{
            $documents = @($script:destinationDocuments[$indexName])
        }}
        if ($searchRequest.filter -match "^id gt '((?:''|[^'])*)'$" ) {{
            $lastKey = $Matches[1].Replace("''", "'")
            $documents = @($documents | Where-Object {{ $_.id -gt $lastKey }})
        }}
        $documents = @($documents | Sort-Object id | Select-Object -First $searchRequest.top)
        return [pscustomobject]@{{ value = $documents }}
    }}

    if ($Method -eq "POST" -and $Uri -match "/indexes/([^/]+)/docs/index\?api-version=") {{
        $indexName = [Uri]::UnescapeDataString($Matches[1])
        $script:migrationEvents += "destination-write:$indexName"
        $payload = $Body | ConvertFrom-Json -Depth 100
        $documents = @($payload.value)
        $script:documentWrites += [pscustomobject]@{{
            indexName = $indexName
            documents = $documents
        }}
        $results = foreach ($document in $documents) {{
            if ($document.id -eq $script:permanentFailureKey) {{
                [pscustomobject]@{{
                    key = $document.id
                    status = $false
                    statusCode = 400
                    errorMessage = "Forced permanent mock failure"
                }}
                continue
            }}
            if ($document.id -eq "new-a" -and $script:transientFailuresRemaining -gt 0) {{
                $script:transientFailuresRemaining--
                [pscustomobject]@{{
                    key = $document.id
                    status = $false
                    statusCode = 503
                    errorMessage = "Transient mock failure"
                }}
                continue
            }}
            [pscustomobject]@{{
                key = $document.id
                status = $true
                statusCode = 201
            }}
        }}
        return [pscustomobject]@{{ value = @($results) }}
    }}

    throw "Unexpected mock request: $Method $Uri"
}}

$script:armKeyPaths = @()

function Connect-AzAccount {{
    [CmdletBinding()]
    param()
}}

function Set-AzContext {{
    [CmdletBinding()]
    param([string]$SubscriptionId)
}}

function Invoke-AzRestMethod {{
    [CmdletBinding()]
    param(
        [string]$Method,
        [string]$Path
    )

    $script:armKeyPaths += $Path
    return [pscustomobject]@{{
        StatusCode = 200
        Content = '{{"primaryKey":"mock-arm-admin-key","secondaryKey":"unused"}}'
    }}
}}

$stateDirectory = Join-Path ([IO.Path]::GetTempPath()) "simplechat-search-state-$PID-$([Guid]::NewGuid().ToString('N'))"
[IO.Directory]::CreateDirectory($stateDirectory) | Out-Null
$differentialStatePath = Join-Path $stateDirectory "differential.json"
$fullStatePath = Join-Path $stateDirectory "full.json"
$interruptedStatePath = Join-Path $stateDirectory "interrupted.json"
$armStatePath = Join-Path $stateDirectory "arm.json"
$commonParameters = @{{
    SourceSearchService = " source-search "
    SourceResourceGroup = " source-rg "
    SourceSubscriptionId = " 00000000-0000-0000-0000-000000000001 "
    DestinationSearchService = " destination-search "
    DestinationResourceGroup = " destination-rg "
    DestinationSubscriptionId = " 00000000-0000-0000-0000-000000000002 "
    SourceAdminKey = " source-key "
    DestinationAdminKey = " destination-key "
    SearchDnsSuffix = " search.windows.net. "
    ApiVersion = " 2026-04-01 "
    ManagementApiVersion = " 2025-05-01 "
    RequestTimeoutSeconds = 45
    PageSize = 1
    BatchSize = 1
    StateFilePath = $differentialStatePath
}}

& $scriptPath @commonParameters -DifferentialMigration $true

if (@($script:indexPuts).Count -ne 1 -or $script:indexPuts[0] -ne "index-b") {{
    throw "Differential migration did not create only the missing index definition."
}}

$differentialDocuments = @($script:documentWrites | ForEach-Object {{ $_.documents }})
$differentialIds = @($differentialDocuments.id | Sort-Object -Unique)
if (($differentialIds -join ",") -ne "new-a,new-b-1,new-b-2") {{
    throw "Differential migration copied an unexpected document set: $($differentialIds -join ',')"
}}
if (@($differentialDocuments | Where-Object {{ $_.'@search.action' -ne "upload" }}).Count -gt 0) {{
    throw "Differential migration did not use upload actions."
}}
if (@($script:sleepCalls).Count -ne 1 -or $script:sleepCalls[0] -ne 1) {{
    throw "Differential migration did not retry the transient indexing failure."
}}

$firstIndexAWrite = [Array]::IndexOf($script:migrationEvents, "destination-write:index-a")
$lastIndexAPage = [Array]::LastIndexOf($script:migrationEvents, "source-page:index-a")
if ($firstIndexAWrite -lt 0 -or $firstIndexAWrite -gt $lastIndexAPage) {{
    throw "Source documents were buffered in full instead of being streamed into destination batches."
}}
if (@($script:requestTimeouts | Where-Object {{ $_ -ne 45 }}).Count -gt 0) {{
    throw "AI Search requests did not receive the configured timeout."
}}
if (@($script:progressRecords | Where-Object {{
    $_.CurrentOperation -match '^Requesting page 1 \(up to 1 documents; timeout: 45 seconds\)$'
}}).Count -eq 0) {{
    throw "Document paging did not report request size and timeout before fetching a page."
}}

$differentialStateJson = [IO.File]::ReadAllText($differentialStatePath)
$differentialState = $differentialStateJson | ConvertFrom-Json -AsHashtable -Depth 100
if ($differentialState.status -ne "completed" -or $differentialState.resources.Count -ne 3) {{
    throw "Differential Search state did not record synonym maps and both indexes."
}}
if (@($differentialState.resources.Values | Where-Object {{ $_.status -ne "completed" }}).Count -gt 0) {{
    throw "Differential Search state contains a non-completed resource."
}}
if ($differentialStateJson -match "source-key|destination-key|mock-arm-admin-key") {{
    throw "Search migration state persisted an admin key."
}}

$indexPutCountBeforeResume = $script:indexPuts.Count
$documentWriteCountBeforeResume = $script:documentWrites.Count
& $scriptPath @commonParameters -DifferentialMigration $true -ShowProgress $false
if (
    $script:indexPuts.Count -ne $indexPutCountBeforeResume -or
    $script:documentWrites.Count -ne $documentWriteCountBeforeResume
) {{
    throw "Resumed Search migration repeated a completed index write."
}}
$resumedState = [IO.File]::ReadAllText($differentialStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if ($resumedState.status -ne "completed" -or $resumedState.resumeCount -ne 1) {{
    throw "Resumed Search migration did not retain and complete its state."
}}

$script:indexPuts = @()
$script:documentWrites = @()

$fullParameters = $commonParameters.Clone()
$fullParameters.StateFilePath = $fullStatePath
& $scriptPath @fullParameters -DifferentialMigration $false

$fullIndexNames = @($script:indexPuts | Sort-Object)
if (($fullIndexNames -join ",") -ne "index-a,index-b") {{
    throw "Full migration did not update every source index definition."
}}

$fullDocuments = @($script:documentWrites | ForEach-Object {{ $_.documents }})
$fullIds = @($fullDocuments.id | Sort-Object)
if (($fullIds -join ",") -ne "existing-a,new-a,new-b-1,new-b-2") {{
    throw "Full migration copied an unexpected document set: $($fullIds -join ',')"
}}
if (@($fullDocuments | Where-Object {{ $_.'@search.action' -ne "upload" }}).Count -gt 0) {{
    throw "Full migration did not use replacing upload actions."
}}
if (@($fullDocuments | Where-Object {{ $_.'@search.action' -eq "delete" }}).Count -gt 0) {{
    throw "Migration must not delete destination-only documents."
}}

$script:indexPuts = @()
$script:documentWrites = @()
$script:permanentFailureKey = "new-b-2"
$interruptedParameters = $commonParameters.Clone()
$interruptedParameters.StateFilePath = $interruptedStatePath
$interruptionObserved = $false
try {{
    & $scriptPath @interruptedParameters -DifferentialMigration $false -ShowProgress $false
}}
catch {{
    if ($_ -match "Document indexing failed for index 'index-b'") {{
        $interruptionObserved = $true
    }}
    else {{
        throw
    }}
}}
if (-not $interruptionObserved) {{
    throw "Forced mid-index failure did not stop the migration."
}}

$interruptedState = [IO.File]::ReadAllText($interruptedStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
$interruptedCheckpoint = $interruptedState.resources["index:index-b"]
if (
    $interruptedState.status -ne "failed" -or
    $interruptedCheckpoint.status -ne "failed" -or
    $interruptedCheckpoint.progress.lastCommittedKey -ne "new-b-1" -or
    $interruptedCheckpoint.progress.processedCount -ne 1 -or
    $interruptedCheckpoint.progress.copiedCount -ne 1
) {{
    throw "Mid-index failure did not preserve the last acknowledged batch checkpoint."
}}

$interruptedState.status = "in_progress"
$interruptedState.currentResource = "index:index-b"
$interruptedState.lastError = $null
$interruptedCheckpoint.status = "in_progress"
$interruptedCheckpoint.lastError = $null
[IO.File]::WriteAllText(
    $interruptedStatePath,
    ($interruptedState | ConvertTo-Json -Depth 100),
    [System.Text.UTF8Encoding]::new($false)
)

$script:permanentFailureKey = $null
& $scriptPath @interruptedParameters -DifferentialMigration $false -ShowProgress $false

$newB1Attempts = @($script:documentWrites | Where-Object {{
    $_.indexName -eq "index-b" -and $_.documents.id -contains "new-b-1"
}}).Count
$newB2Attempts = @($script:documentWrites | Where-Object {{
    $_.indexName -eq "index-b" -and $_.documents.id -contains "new-b-2"
}}).Count
if ($newB1Attempts -ne 1 -or $newB2Attempts -ne 2) {{
    throw "Batch resume repeated committed writes or failed to retry the uncommitted write."
}}

$completedInterruptedState = [IO.File]::ReadAllText($interruptedStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
$completedInterruptedCheckpoint = $completedInterruptedState.resources["index:index-b"]
if (
    $completedInterruptedState.status -ne "completed" -or
    $completedInterruptedCheckpoint.attempt -ne 2 -or
    $completedInterruptedCheckpoint.progress.lastCommittedKey -ne "new-b-2" -or
    $completedInterruptedCheckpoint.progress.processedCount -ne 2
) {{
    throw "Resumed index did not complete from its acknowledged key checkpoint."
}}

$armParameters = $commonParameters.Clone()
$armParameters.SourceAdminKey = " "
$armParameters.DestinationAdminKey = " "
$armParameters.StateFilePath = $armStatePath
& $scriptPath @armParameters -DifferentialMigration $true

if (@($script:armKeyPaths).Count -ne 2) {{
    throw "Automatic admin-key resolution did not query both Search services."
}}
if ($script:armKeyPaths[0] -notmatch "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/source-rg/.*/source-search/listAdminKeys\?api-version=2025-05-01$") {{
    throw "Source admin-key lookup used an unexpected ARM path: $($script:armKeyPaths[0])"
}}
if ($script:armKeyPaths[1] -notmatch "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/destination-rg/.*/destination-search/listAdminKeys\?api-version=2025-05-01$") {{
    throw "Destination admin-key lookup used an unexpected ARM path: $($script:armKeyPaths[1])"
}}

$overallMidpoint = @($script:progressRecords | Where-Object {{
    $_.Id -eq 0 -and
    $_.PercentComplete -eq 50 -and
    $_.Status -eq "Indexes: 1/2 | Remaining: 1 | 50%"
}})
if ($overallMidpoint.Count -eq 0) {{
    throw "Overall migration progress did not report the expected 50 percent midpoint."
}}

$indexMidpoint = @($script:progressRecords | Where-Object {{
    $_.Id -eq 1 -and
    $_.ParentId -eq 0 -and
    $_.PercentComplete -eq 50 -and
    $_.Status -eq "Source documents: 1/2 | Remaining: 1 | 50%" -and
    $_.CurrentOperation -match "Copied: \d+ \| Skipped: \d+ \| Batches: \d+ \| Buffered: \d+"
}})
if ($indexMidpoint.Count -eq 0) {{
    throw "Per-index progress did not report document percentage and counters."
}}

$destinationComparison = @($script:progressRecords | Where-Object {{
    $_.Id -eq 1 -and
    $_.Status -eq "Destination keys: 1/2 | Remaining: 1 | 50%"
}})
if ($destinationComparison.Count -eq 0) {{
    throw "Differential progress did not report destination-key comparison."
}}

if (@($script:progressRecords | Where-Object {{ $_.Id -eq 0 -and $_.Completed }}).Count -eq 0) {{
    throw "Overall progress was not marked complete."
}}
if (@($script:progressRecords | Where-Object {{ $_.Id -eq 1 -and $_.Completed }}).Count -eq 0) {{
    throw "Per-index progress was not marked complete."
}}
if (@($script:progressRecords | Where-Object {{ $_.Id -gt 1 }}).Count -gt 0) {{
    throw "Migration should not create a noisy per-document progress bar."
}}

[IO.Directory]::Delete($stateDirectory, $true)
Write-Output "AI Search mock migration checks passed."
'''

    result = subprocess.run(
        [powershell, "-NoProfile", "-Command", "-"],
        input=harness,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    if result.returncode != 0:
        raise AssertionError(
            "Mock AI Search migration failed.\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    if "AI Search mock migration checks passed." not in result.stdout:
        raise AssertionError(f"Expected success output was missing:\n{result.stdout}")


if __name__ == "__main__":
    try:
        test_ai_search_all_indexes_migration()
    except Exception as exc:
        print(f"Test failed: {exc}")
        raise

    print("AI Search all-index migration test passed")
    sys.exit(0)