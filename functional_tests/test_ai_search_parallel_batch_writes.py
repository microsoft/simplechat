# test_ai_search_parallel_batch_writes.py
#!/usr/bin/env python3
"""
Functional test for parallel Azure AI Search batch migration.
Version: 0.250.073
Implemented in: 0.250.073

This test ensures bounded parallel indexing batches preserve differential and
full migration semantics, apply source-feed backpressure, retry transient
failures, and checkpoint only fully acknowledged batch windows.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "Migration-AISearch.ps1"


def test_ai_search_parallel_batch_writes() -> None:
    """Exercise the real parallel runspace path against a deterministic mock API."""
    powershell = shutil.which("pwsh")
    if not powershell:
        raise AssertionError("PowerShell 7 is required to test parallel migration.")

    script_path = str(SCRIPT_PATH).replace("'", "''")
    test_directory = Path(tempfile.mkdtemp(prefix="simplechat-search-parallel-"))
    test_directory_path = str(test_directory).replace("'", "''")
    harness = r'''
$ErrorActionPreference = "Stop"
$scriptPath = '__SCRIPT_PATH__'
$testDirectory = '__TEST_DIRECTORY__'
[IO.Directory]::CreateDirectory($testDirectory) | Out-Null
$env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_DIR = $testDirectory
$env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_MODE = "success"
$env:SIMPLECHAT_AISEARCH_FAIL_KEY = ""

function New-MockIndex {
    return [pscustomobject]@{
        name = "parallel-index"
        fields = @(
            [pscustomobject]@{
                name = "id"
                type = "Edm.String"
                key = $true
                retrievable = $true
                filterable = $true
                sortable = $true
            }
            [pscustomobject]@{
                name = "content"
                type = "Edm.String"
                key = $false
                retrievable = $true
                filterable = $false
                sortable = $false
            }
        )
    }
}

$global:mockSourceIndex = New-MockIndex
$global:mockSourceDocuments = @(
    [pscustomobject]@{ id = "doc-a"; content = "A" }
    [pscustomobject]@{ id = "doc-b"; content = "B" }
    [pscustomobject]@{ id = "doc-c"; content = "C" }
    [pscustomobject]@{ id = "doc-d"; content = "D" }
    [pscustomobject]@{ id = "retry-me"; content = "Retry" }
)
$global:mockDestinationDocuments = @(
    [pscustomobject]@{ id = "doc-a"; content = "Existing" }
)

function Start-Sleep {
    [CmdletBinding()]
    param([int]$Seconds)
}

function Invoke-RestMethod {
    [CmdletBinding()]
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers,
        [string]$ContentType,
        [AllowNull()]
        [string]$Body,
        [int]$TimeoutSec
    )

    if ($Method -eq "GET" -and $Uri -match "/synonymmaps\?api-version=") {
        return [pscustomobject]@{ value = @() }
    }
    if ($Method -eq "GET" -and $Uri -match "/indexes\?api-version=") {
        return [pscustomobject]@{ value = @($global:mockSourceIndex) }
    }
    if ($Method -eq "PUT" -and $Uri -match "/indexes/parallel-index\?api-version=") {
        return $Body | ConvertFrom-Json -Depth 100
    }
    if ($Method -eq "GET" -and $Uri -match '/indexes/parallel-index/docs/\$count\?api-version=') {
        if ($Uri.StartsWith("https://source-search.")) {
            return [long]$global:mockSourceDocuments.Count
        }
        return [long]$global:mockDestinationDocuments.Count
    }
    if ($Method -eq "POST" -and $Uri -match "/indexes/parallel-index/docs/search\?api-version=") {
        $request = $Body | ConvertFrom-Json -Depth 100
        $documents = if ($Uri.StartsWith("https://source-search.")) {
            @($global:mockSourceDocuments)
        }
        else {
            @($global:mockDestinationDocuments)
        }
        if ($request.filter -match "^id gt '((?:''|[^'])*)'$") {
            $lastKey = $Matches[1].Replace("''", "'")
            if (
                $Uri.StartsWith("https://source-search.") -and
                $env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_MODE -eq "success" -and
                $lastKey -eq "doc-c" -and
                @(Get-ChildItem -LiteralPath $env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_DIR -Filter "success-write-*.marker").Count -eq 0
            ) {
                [IO.File]::WriteAllText(
                    (Join-Path $env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_DIR "success-buffered.marker"),
                    "buffered"
                )
            }
            $documents = @($documents | Where-Object { $_.id -gt $lastKey })
        }
        $documents = @($documents | Sort-Object id | Select-Object -First $request.top)
        return [pscustomobject]@{ value = $documents }
    }
    if ($Method -eq "POST" -and $Uri -match "/indexes/parallel-index/docs/index\?api-version=") {
        $payload = $Body | ConvertFrom-Json -Depth 100
        $documents = @($payload.value)
        $mode = [string]$env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_MODE
        $results = foreach ($document in $documents) {
            $attemptPath = Join-Path `
                $env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_DIR `
                "$mode-$($document.id).attempts"
            [IO.File]::AppendAllText($attemptPath, "attempt`n")
            $attemptCount = @([IO.File]::ReadAllLines($attemptPath)).Count
            [IO.File]::WriteAllText(
                (Join-Path $env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_DIR "$mode-started-$($document.id).marker"),
                "started"
            )

            $parallelPair = if ($mode -eq "success") {
                @("doc-b", "doc-c")
            }
            else {
                @("doc-a", "doc-b")
            }
            if ($attemptCount -eq 1 -and $document.id -in $parallelPair) {
                $stopwatch = [Diagnostics.Stopwatch]::StartNew()
                while (
                    @(Get-ChildItem -LiteralPath $env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_DIR -Filter "$mode-started-*.marker").Count -lt 2 -and
                    $stopwatch.Elapsed.TotalSeconds -lt 3
                ) {
                    [Threading.Thread]::Sleep(10)
                }
                if (@(Get-ChildItem -LiteralPath $env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_DIR -Filter "$mode-started-*.marker").Count -lt 2) {
                    [IO.File]::WriteAllText(
                        (Join-Path $env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_DIR "$mode-no-overlap.marker"),
                        "sequential"
                    )
                }
            }

            [IO.File]::WriteAllText(
                (Join-Path $env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_DIR "$mode-write-$($document.id).marker"),
                "written"
            )
            if ($document.id -eq $env:SIMPLECHAT_AISEARCH_FAIL_KEY) {
                [pscustomobject]@{
                    key = $document.id
                    status = $false
                    statusCode = 400
                    errorMessage = "Forced permanent failure"
                }
                continue
            }
            if ($document.id -eq "retry-me" -and $attemptCount -eq 1) {
                [pscustomobject]@{
                    key = $document.id
                    status = $false
                    statusCode = 503
                    errorMessage = "Forced transient failure"
                }
                continue
            }
            [pscustomobject]@{
                key = $document.id
                status = $true
                statusCode = 201
            }
        }
        return [pscustomobject]@{ value = @($results) }
    }

    throw "Unexpected mock request: $Method $Uri"
}

$commonParameters = @{
    SourceSearchService = "source-search"
    SourceResourceGroup = "source-rg"
    SourceSubscriptionId = "00000000-0000-0000-0000-000000000001"
    DestinationSearchService = "destination-search"
    DestinationResourceGroup = "destination-rg"
    DestinationSubscriptionId = "00000000-0000-0000-0000-000000000002"
    SourceAdminKey = "source-key"
    DestinationAdminKey = "destination-key"
    PageSize = 1
    BatchSize = 1
    MaxConcurrentBatches = 2
    ProgressUpdateInterval = 1
    MaxRetryCount = 3
    ShowProgress = $false
}

$differentialStatePath = Join-Path $testDirectory "differential-state.json"
$differentialParameters = $commonParameters.Clone()
$differentialParameters.StateFilePath = $differentialStatePath
& $scriptPath @differentialParameters -DifferentialMigration $true

$differentialState = [IO.File]::ReadAllText($differentialStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
$differentialResult = $differentialState.resources["index:parallel-index"].result
if (
    $differentialState.status -ne "completed" -or
    $differentialResult.CopiedCount -ne 4 -or
    $differentialResult.SkippedCount -ne 1 -or
    $differentialResult.ProcessedCount -ne 5 -or
    $differentialResult.BatchCount -ne 4
) {
    throw "Parallel differential migration recorded unexpected results."
}
if (Test-Path -LiteralPath (Join-Path $testDirectory "success-doc-a.attempts")) {
    throw "Parallel differential migration overwrote an existing destination key."
}
if (@([IO.File]::ReadAllLines((Join-Path $testDirectory "success-retry-me.attempts"))).Count -ne 2) {
    throw "Parallel migration did not retry the transient batch exactly once."
}
if (Test-Path -LiteralPath (Join-Path $testDirectory "success-no-overlap.marker")) {
    throw "AI Search batches did not execute concurrently."
}
if (Test-Path -LiteralPath (Join-Path $testDirectory "success-buffered.marker")) {
    throw "Parallel migration requested another source page before draining its bounded batch window."
}

$env:SIMPLECHAT_AISEARCH_PARALLEL_TEST_MODE = "failure"
$env:SIMPLECHAT_AISEARCH_FAIL_KEY = "doc-b"
$failureStatePath = Join-Path $testDirectory "failure-state.json"
$failureParameters = $commonParameters.Clone()
$failureParameters.StateFilePath = $failureStatePath
$failureObserved = $false
try {
    & $scriptPath @failureParameters -DifferentialMigration $false
}
catch {
    if ($_ -match "Document indexing failed for index 'parallel-index'") {
        $failureObserved = $true
    }
    else {
        throw
    }
}
if (-not $failureObserved) {
    throw "Forced parallel batch failure did not stop the migration."
}

$failedState = [IO.File]::ReadAllText($failureStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
$failedProgress = $failedState.resources["index:parallel-index"].progress
if (
    $failedState.status -ne "failed" -or
    $failedProgress.processedCount -ne 0 -or
    $failedProgress.copiedCount -ne 0 -or
    -not [string]::IsNullOrEmpty([string]$failedProgress.lastCommittedKey)
) {
    throw "A partially failed parallel window advanced the migration checkpoint."
}

$env:SIMPLECHAT_AISEARCH_FAIL_KEY = ""
& $scriptPath @failureParameters -DifferentialMigration $false

$completedState = [IO.File]::ReadAllText($failureStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
$completedCheckpoint = $completedState.resources["index:parallel-index"]
if (
    $completedState.status -ne "completed" -or
    $completedCheckpoint.attempt -ne 2 -or
    $completedCheckpoint.result.CopiedCount -ne 5 -or
    $completedCheckpoint.progress.lastCommittedKey -ne "retry-me"
) {
    throw "Parallel migration did not resume and complete its unacknowledged window."
}
foreach ($replayedKey in @("doc-a", "doc-b")) {
    $attemptPath = Join-Path $testDirectory "failure-$replayedKey.attempts"
    if (@([IO.File]::ReadAllLines($attemptPath)).Count -ne 2) {
        throw "Unacknowledged document '$replayedKey' was not replayed exactly once."
    }
}

Write-Output "Parallel AI Search batch migration checks passed."
'''.replace("__SCRIPT_PATH__", script_path).replace(
        "__TEST_DIRECTORY__", test_directory_path
    )

    try:
        result = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-Command", harness],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(
                "Parallel AI Search migration harness failed.\n"
                f"STDOUT:\n{result.stdout}\n"
                f"STDERR:\n{result.stderr}"
            )
        if "Parallel AI Search batch migration checks passed." not in result.stdout:
            raise AssertionError(f"Expected success output was missing:\n{result.stdout}")
    finally:
        shutil.rmtree(test_directory, ignore_errors=True)


if __name__ == "__main__":
    test_ai_search_parallel_batch_writes()
    print("AI Search parallel batch writes test passed.")
    sys.exit(0)