# test_cosmos_parallel_document_writes.py
#!/usr/bin/env python3
"""
Functional test for parallel Azure Cosmos DB document migration.
Version: 0.250.072
Implemented in: 0.250.069
Backpressured feed-order coverage added in: 0.250.070
Source document total coverage added in: 0.250.071
Simplified progress coverage added in: 0.250.072

This test ensures bounded parallel writes preserve differential and full mode
semantics, honor Cosmos retry-after responses, and report concurrent progress.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "Migration-Cosmos.ps1"


def test_cosmos_parallel_document_writes() -> None:
    """Exercise the real parallel runspace path against a deterministic mock API."""
    powershell = shutil.which("pwsh")
    if not powershell:
        raise AssertionError("PowerShell 7 is required to test parallel migration.")

    script_path = str(SCRIPT_PATH).replace("'", "''")
    test_directory = Path(tempfile.mkdtemp(prefix="simplechat-cosmos-parallel-"))
    test_directory_path = str(test_directory).replace("'", "''")
    harness = rf'''
$ErrorActionPreference = "Stop"
$scriptPath = '{script_path}'
$testDirectory = '{test_directory_path}'
[IO.Directory]::CreateDirectory($testDirectory) | Out-Null
$env:SIMPLECHAT_COSMOS_PARALLEL_TEST_DIR = $testDirectory
$env:SIMPLECHAT_COSMOS_PARALLEL_TEST_MODE = "differential"
$global:mockParallelProgressRecords = @()

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

    $global:mockParallelProgressRecords = @($global:mockParallelProgressRecords) + [pscustomobject]@{{
        Id = $Id
        ParentId = $ParentId
        Activity = $Activity
        Status = $Status
        CurrentOperation = $CurrentOperation
        PercentComplete = $PercentComplete
        Completed = $Completed.IsPresent
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

    function New-MockResponse {{
        param(
            [int]$StatusCode,
            [AllowNull()]
            [object]$ResponseBody = $null,
            [hashtable]$ResponseHeaders = @{{}}
        )

        $content = if ($null -eq $ResponseBody) {{
            ""
        }}
        elseif ($ResponseBody -is [string]) {{
            $ResponseBody
        }}
        else {{
            ConvertTo-Json -InputObject $ResponseBody -Depth 100 -Compress
        }}
        return [pscustomobject]@{{
            StatusCode = $StatusCode
            Headers = $ResponseHeaders
            Content = $content
        }}
    }}

    $container = [pscustomobject]@{{
        id = "documents"
        partitionKey = [pscustomobject]@{{
            paths = @("/user_id")
            kind = "Hash"
            version = 2
        }}
        indexingPolicy = [pscustomobject]@{{
            automatic = $true
            indexingMode = "consistent"
            includedPaths = @([pscustomobject]@{{ path = "/*" }})
            excludedPaths = @()
        }}
        statistics = @([pscustomobject]@{{ documentCount = 4; id = "0" }})
    }}

    if ($Method -eq "GET" -and $Uri -match "/dbs/SimpleChat$") {{
        return New-MockResponse -StatusCode 200 -ResponseBody @{{ id = "SimpleChat" }}
    }}
    if ($Method -eq "GET" -and $Uri -match "/dbs/SimpleChat/colls$") {{
        return New-MockResponse `
            -StatusCode 200 `
            -ResponseBody @{{ DocumentCollections = @($container) }}
    }}
    if ($Method -eq "PUT" -and $Uri -match "/dbs/SimpleChat/colls/documents$") {{
        return New-MockResponse `
            -StatusCode 200 `
            -ResponseBody ($Body | ConvertFrom-Json -Depth 100)
    }}
    if ($Method -eq "GET" -and $Uri -match "/dbs/SimpleChat/colls/documents/docs$") {{
        $documents = @(
            [pscustomobject]@{{ id = "existing"; user_id = "user-a"; value = 1 }}
            [pscustomobject]@{{ id = "new-a"; user_id = "user-b"; value = 2 }}
            [pscustomobject]@{{ id = "retry-me"; user_id = "user-c"; value = 3 }}
            [pscustomobject]@{{ id = "new-b"; user_id = "user-d"; value = 4 }}
        )
        $mode = [string]$env:SIMPLECHAT_COSMOS_PARALLEL_TEST_MODE
        $continuation = [string]$Headers["x-ms-continuation"]
        if ($continuation -eq "2") {{
            $firstPageWriteMarkers = @(Get-ChildItem `
                -LiteralPath $env:SIMPLECHAT_COSMOS_PARALLEL_TEST_DIR `
                -Filter "$mode-write-*.marker")
            if ($firstPageWriteMarkers.Count -eq 0) {{
                [IO.File]::WriteAllText(
                    (Join-Path $env:SIMPLECHAT_COSMOS_PARALLEL_TEST_DIR "$mode-buffered-before-page2.marker"),
                    "buffered"
                )
            }}
        }}
        $offset = if ([string]::IsNullOrWhiteSpace($continuation)) {{
            0
        }}
        else {{
            [int]$continuation
        }}
        $pageSize = [int]$Headers["x-ms-max-item-count"]
        $page = @($documents | Select-Object -Skip $offset -First $pageSize)
        $nextOffset = $offset + $page.Count
        $responseHeaders = @{{}}
        if ($nextOffset -lt $documents.Count) {{
            $responseHeaders["x-ms-continuation"] = [string]$nextOffset
        }}
        return New-MockResponse `
            -StatusCode 200 `
            -ResponseBody @{{ Documents = $page; _count = $page.Count }} `
            -ResponseHeaders $responseHeaders
    }}
    if ($Method -eq "POST" -and $Uri -match "/dbs/SimpleChat/colls/documents/docs$") {{
        $document = $Body | ConvertFrom-Json -Depth 100
        $mode = [string]$env:SIMPLECHAT_COSMOS_PARALLEL_TEST_MODE
        $attemptPath = Join-Path `
            $env:SIMPLECHAT_COSMOS_PARALLEL_TEST_DIR `
            "$mode-$($document.id).attempts"
        [IO.File]::AppendAllText($attemptPath, "attempt`n")
        [IO.File]::WriteAllText(
            (Join-Path $env:SIMPLECHAT_COSMOS_PARALLEL_TEST_DIR "$mode-write-$($document.id).marker"),
            "written"
        )

        $isUpsert = $Headers.ContainsKey("x-ms-documentdb-is-upsert")
        if ($mode -eq "full" -and -not $isUpsert) {{
            return New-MockResponse `
                -StatusCode 400 `
                -ResponseBody @{{ code = "MissingUpsert" }}
        }}
        if ($mode -eq "differential" -and $isUpsert) {{
            return New-MockResponse `
                -StatusCode 400 `
                -ResponseBody @{{ code = "UnexpectedUpsert" }}
        }}
        if ($mode -eq "differential" -and $document.id -eq "existing") {{
            return New-MockResponse -StatusCode 409 -ResponseBody @{{ code = "Conflict" }}
        }}
        if ($mode -eq "differential" -and $document.id -eq "retry-me") {{
            $attemptCount = @([IO.File]::ReadAllLines($attemptPath)).Count
            if ($attemptCount -eq 1) {{
                return New-MockResponse `
                    -StatusCode 429 `
                    -ResponseBody @{{ code = "TooManyRequests" }} `
                    -ResponseHeaders @{{ "x-ms-retry-after-ms" = "1" }}
            }}
        }}
        $statusCode = if ($isUpsert -and $document.id -eq "existing") {{ 200 }} else {{ 201 }}
        return New-MockResponse -StatusCode $statusCode -ResponseBody $document
    }}

    throw "Unexpected mock request: $Method $Uri"
}}

$commonParameters = @{{
    SourceCosmosAccount = "source-cosmos"
    SourceResourceGroup = "source-rg"
    SourceSubscriptionId = "00000000-0000-0000-0000-000000000001"
    SourceDatabaseName = "SimpleChat"
    DestinationCosmosAccount = "destination-cosmos"
    DestinationResourceGroup = "destination-rg"
    DestinationSubscriptionId = "00000000-0000-0000-0000-000000000002"
    DestinationDatabaseName = "SimpleChat"
    SourcePrimaryKey = "c291cmNlLWtleQ=="
    DestinationPrimaryKey = "ZGVzdGluYXRpb24ta2V5"
    Containers = @("documents")
    PageSize = 2
    ProgressUpdateInterval = 1
    MaxConcurrentDocuments = 2
    MaxRetryCount = 3
    ShowProgress = $true
}}

$differentialStatePath = Join-Path $testDirectory "differential-state.json"
$differentialParameters = $commonParameters.Clone()
$differentialParameters.StateFilePath = $differentialStatePath
& $scriptPath @differentialParameters -DifferentialMigration $true

$differentialState = [IO.File]::ReadAllText($differentialStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
$differentialResult = $differentialState.resources.documents.result
if (
    $differentialState.status -ne "completed" -or
    $differentialResult.CopiedCount -ne 3 -or
    $differentialResult.SkippedCount -ne 1 -or
    $differentialResult.ProcessedCount -ne 4 -or
    $differentialResult.RetryCount -ne 1
) {{
    throw "Parallel differential migration recorded unexpected results: status=$($differentialState.status), copied=$($differentialResult.CopiedCount), skipped=$($differentialResult.SkippedCount), processed=$($differentialResult.ProcessedCount), retries=$($differentialResult.RetryCount)."
}}
if (@([IO.File]::ReadAllLines((Join-Path $testDirectory "differential-retry-me.attempts"))).Count -ne 2) {{
    throw "Parallel differential migration did not retry the throttled document exactly once."
}}
if (Test-Path -LiteralPath (Join-Path $testDirectory "differential-buffered-before-page2.marker")) {{
    throw "Parallel migration buffered the source feed instead of writing page 1 before requesting page 2."
}}
if (@($global:mockParallelProgressRecords | Where-Object {{
    $_.CurrentOperation -match "In flight:|Retries:|Retrying document"
}}).Count -gt 0) {{
    throw "Parallel progress exposed internal in-flight or retry details."
}}
if (@($global:mockParallelProgressRecords | Where-Object {{
    $_.Status -eq "Source documents: 2/4 | Remaining: 2 | 50%"
}}).Count -eq 0) {{
    throw "Parallel progress did not report the source document total and percentage."
}}

$env:SIMPLECHAT_COSMOS_PARALLEL_TEST_MODE = "full"
$global:mockParallelProgressRecords = @()
$fullStatePath = Join-Path $testDirectory "full-state.json"
$fullParameters = $commonParameters.Clone()
$fullParameters.StateFilePath = $fullStatePath
& $scriptPath @fullParameters -DifferentialMigration $false

$fullState = [IO.File]::ReadAllText($fullStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
$fullResult = $fullState.resources.documents.result
if (
    $fullState.status -ne "completed" -or
    $fullResult.CopiedCount -ne 4 -or
    $fullResult.SkippedCount -ne 0 -or
    $fullResult.ProcessedCount -ne 4 -or
    $fullResult.RetryCount -ne 0
) {{
    throw "Parallel full migration recorded unexpected results."
}}

Remove-Item Env:SIMPLECHAT_COSMOS_PARALLEL_TEST_DIR
Remove-Item Env:SIMPLECHAT_COSMOS_PARALLEL_TEST_MODE
[IO.Directory]::Delete($testDirectory, $true)
Write-Output "Parallel Cosmos document migration checks passed."
'''

    try:
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
                f"Parallel Cosmos migration harness failed with exit code {result.returncode}."
            )
        if "Parallel Cosmos document migration checks passed." not in result.stdout:
            raise AssertionError(f"Expected success output was missing:\n{result.stdout}")
    finally:
        shutil.rmtree(test_directory, ignore_errors=True)


if __name__ == "__main__":
    test_cosmos_parallel_document_writes()
    print("Cosmos parallel document writes test passed.")
