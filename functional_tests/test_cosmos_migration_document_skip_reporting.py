# test_cosmos_migration_document_skip_reporting.py
#!/usr/bin/env python3
"""
Functional test for Cosmos migration JSON property and skip reporting.
Version: 0.250.067
Implemented in: 0.250.064

This test ensures documents with empty or case-distinct JSON property names
are copied correctly and document-scoped write failures are recorded without
stopping later writes.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "Migration-Cosmos.ps1"


def _powershell_single_quote(value: Path) -> str:
    """Escape a path for a PowerShell single-quoted string."""
    return str(value).replace("'", "''")


def test_cosmos_migration_document_skip_reporting() -> None:
    """Exercise empty-name JSON fields and nonfatal write rejection reporting."""
    powershell = shutil.which("pwsh")
    if not powershell:
        raise AssertionError("PowerShell 7 is required to test the migration script.")

    with tempfile.TemporaryDirectory(prefix="simplechat-cosmos-skip-") as temp_dir:
        state_path = Path(temp_dir) / "migration-state.json"
        harness = r'''
$ErrorActionPreference = "Stop"
$scriptPath = '__SCRIPT_PATH__'
$statePath = '__STATE_PATH__'
$global:mockFatalWrites = $false
$global:mockThrottleResponsesRemaining = 0
$global:mockSleepRecords = [System.Collections.Generic.List[object]]::new()
$global:mockProvenanceWriteCount = 0
$global:mockDestinationProvenanceQueryCount = 0

function Start-Sleep {
    [CmdletBinding()]
    param(
        [int]$Milliseconds,
        [int]$Seconds
    )

    $global:mockSleepRecords.Add([pscustomobject]@{
        Milliseconds = $Milliseconds
        Seconds = $Seconds
    })
}

function Invoke-WebRequest {
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
    if (-not $isSource -and -not $isDestination) {
        throw "Unexpected endpoint: $Uri"
    }

    if ($Method -eq "GET" -and $Uri -match "/dbs/SimpleChat$") {
        return [pscustomobject]@{
            StatusCode = 200
            Headers = @{}
            Content = '{"id":"SimpleChat"}'
        }
    }

    if ($Method -eq "GET" -and $Uri -match "/dbs/SimpleChat/colls$") {
        return [pscustomobject]@{
            StatusCode = 200
            Headers = @{}
            Content = '{"DocumentCollections":[{"id":"documents","partitionKey":{"paths":["/tenant"],"kind":"Hash","version":2},"statistics":[{"documentCount":5}]}]}'
        }
    }

    if (
        $Method -eq "GET" -and
        $isSource -and
        $Uri -match "/dbs/SimpleChat/colls/documents/docs$"
    ) {
        $recentMigrationTimestamp = [DateTime]::UtcNow.ToString("o")
        return [pscustomobject]@{
            StatusCode = 200
            Headers = @{}
            Content = ('{"Documents":[{"id":"empty-key-doc","tenant":"a","":"root-empty","Name":"upper","name":"lower","nested":{"":"nested-empty"},"_rid":"remove"},{"id":"bad-doc","tenant":"b","content":"reject"},{"tenant":"missing-id","content":"cannot write"},{"id":"after-doc","tenant":"c","content":"continues"},{"id":"recent-migrated-doc","tenant":"d","simplechatMigration":{"migrationId":"22222222-2222-2222-2222-222222222222","migratedAtUtc":"' + $recentMigrationTimestamp + '","status":"succeeded"}}],"_count":5}')
        }
    }

    if (
        $Method -eq "PUT" -and
        $isDestination -and
        $Uri -match "/dbs/SimpleChat/colls/documents$"
    ) {
        return [pscustomobject]@{
            StatusCode = 200
            Headers = @{}
            Content = '{}'
        }
    }

    if (
        $Method -eq "POST" -and
        $isDestination -and
        $Uri -match "/dbs/SimpleChat/colls/documents/docs$" -and
        $Headers.ContainsKey("x-ms-documentdb-isquery")
    ) {
        $global:mockDestinationProvenanceQueryCount++
        $recentDestinationTimestamp = [DateTime]::UtcNow.ToString("o")
        return [pscustomobject]@{
            StatusCode = 200
            Headers = @{}
            Content = ('{"Documents":[{"id":"after-doc","tenant":"c","simplechatMigration":{"migrationId":"11111111-1111-1111-1111-111111111111","migratedAtUtc":"' + $recentDestinationTimestamp + '","status":"succeeded"}}],"_count":1}')
        }
    }

    if (
        $Method -eq "POST" -and
        $isDestination -and
        $Uri -match "/dbs/SimpleChat/colls/documents/docs$"
    ) {
        $document = $Body | ConvertFrom-Json -AsHashtable -Depth 100
        $migrationMetadata = $document["simplechatMigration"]
        if (
            $null -eq $migrationMetadata -or
            $migrationMetadata["migrationId"] -ne "11111111-1111-1111-1111-111111111111" -or
            $migrationMetadata["status"] -ne "succeeded" -or
            [string]::IsNullOrWhiteSpace([string]$migrationMetadata["migratedAtUtc"])
        ) {
            throw "Migration provenance metadata was missing or incomplete: $Body"
        }
        if ($document.id -eq "recent-migrated-doc") {
            $global:mockProvenanceWriteCount++
            throw "A recently migrated document should not have reached the destination writer."
        }
        if ($global:mockFatalWrites -and $document.id -eq "after-doc") {
            return [pscustomobject]@{
                StatusCode = 503
                Headers = @{}
                Content = '{"code":"ServiceUnavailable","message":"mock outage"}'
            }
        }
        if ($document.id -eq "empty-key-doc") {
            if (
                $document[""] -ne "root-empty" -or
                $document.Name -ne "upper" -or
                $document.name -ne "lower" -or
                $document.nested[""] -ne "nested-empty" -or
                $document.Contains("_rid")
            ) {
                throw "The empty-name document was not preserved correctly: $Body"
            }
        }
        if ($document.id -eq "bad-doc") {
            return [pscustomobject]@{
                StatusCode = 400
                Headers = @{}
                Content = '{"code":"BadRequest","message":"mock rejected document"}'
            }
        }
        if (
            $document.id -eq "after-doc" -and
            $global:mockThrottleResponsesRemaining -gt 0
        ) {
            $global:mockThrottleResponsesRemaining--
            return [pscustomobject]@{
                StatusCode = 429
                Headers = @{}
                Content = '{"code":"TooManyRequests","message":"mock throttling"}'
            }
        }
        return [pscustomobject]@{
            StatusCode = 201
            Headers = @{}
            Content = $Body
        }
    }

    throw "Unexpected mock request: $Method $Uri"
}

$parameters = @{
    SourceCosmosAccount = "source-cosmos"
    SourceResourceGroup = "source-rg"
    SourceSubscriptionId = "00000000-0000-0000-0000-000000000001"
    SourceDatabaseName = "SimpleChat"
    SourcePrimaryKey = "c291cmNlLWtleQ=="
    DestinationCosmosAccount = "destination-cosmos"
    DestinationResourceGroup = "destination-rg"
    DestinationSubscriptionId = "00000000-0000-0000-0000-000000000002"
    DestinationDatabaseName = "SimpleChat"
    DestinationPrimaryKey = "ZGVzdGluYXRpb24ta2V5"
    Containers = @("documents")
    DifferentialMigration = $true
    MigrationId = "11111111-1111-1111-1111-111111111111"
    ShowProgress = $false
    PageSize = 100
    MaxConcurrentDocuments = 2
    MaxRetryCount = 2
    StateFilePath = $statePath
}

$migrationOutput = @(& $scriptPath @parameters 3>&1 6>&1)
$outputText = $migrationOutput | Out-String
$state = [IO.File]::ReadAllText($statePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
$result = $state.resources.documents.result
$badSkippedDocument = @($result.SkippedDocuments | Where-Object {
    $_.DocumentId -eq "bad-doc"
})[0]
$missingIdSkippedDocument = @($result.SkippedDocuments | Where-Object {
    $_.DocumentId -eq "<missing id>"
})[0]

if ($state.status -ne "completed") {
    throw "Migration state was not completed: $($state.status)"
}
if (
    $state.migrationId -ne $parameters.MigrationId -or
    [string]::IsNullOrWhiteSpace([string]$state.migrationStartedUtc)
) {
    throw "Migration state did not preserve provenance: $($state | ConvertTo-Json -Compress)"
}
if (
    $result.ProcessedCount -ne 5 -or
    $result.CopiedCount -ne 2 -or
    $result.SkippedCount -ne 3 -or
    $result.ErrorSkippedCount -ne 2 -or
    $global:mockProvenanceWriteCount -ne 0
) {
    throw "Unexpected result counts: $($result | ConvertTo-Json -Compress)"
}
if (
    $badSkippedDocument.ContainerName -ne "documents" -or
    $badSkippedDocument.Stage -ne "Write" -or
    $badSkippedDocument.Attempt -ne 1 -or
    $badSkippedDocument.StatusCode -ne 400 -or
    $badSkippedDocument.Reason -notmatch "mock rejected document" -or
    [string]::IsNullOrWhiteSpace($badSkippedDocument.RecordedUtc) -or
    $missingIdSkippedDocument.ContainerName -ne "documents" -or
    $missingIdSkippedDocument.Stage -ne "Preparation" -or
    $null -ne $missingIdSkippedDocument.StatusCode -or
    $missingIdSkippedDocument.Reason -notmatch "without a valid id" -or
    [string]::IsNullOrWhiteSpace($missingIdSkippedDocument.RecordedUtc)
) {
    throw "Skipped document details were incomplete: $($result.SkippedDocuments | ConvertTo-Json -Compress)"
}
if ($state.summary.ErrorSkippedCount -ne 2) {
    throw "Migration summary did not include the error-skipped count."
}
if (
    $outputText -notmatch "Admin review required: 2 document" -or
    $outputText -notmatch "result\.SkippedDocuments" -or
    $outputText -notmatch "entries in '[^']+migration-state\.json'"
) {
    throw "The final admin warning was missing or incomplete: $outputText"
}

$resumeOutput = @(& $scriptPath @parameters 3>&1 6>&1) | Out-String
$resumedState = [IO.File]::ReadAllText($statePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if (
    $resumedState.status -ne "completed" -or
    $resumedState.resumeCount -ne 1 -or
    $resumedState.summary.ErrorSkippedCount -ne 2 -or
    $resumeOutput -notmatch "Skipping completed container from migration state: documents" -or
    $resumeOutput -notmatch "Admin review required: 2 document"
) {
    throw "Resumed migration did not preserve skipped-document reporting: $resumeOutput"
}

$sequentialStatePath = "$statePath.sequential.json"
$parameters.StateFilePath = $sequentialStatePath
$parameters.MaxConcurrentDocuments = 1
$sequentialOutput = @(& $scriptPath @parameters 3>&1 6>&1) | Out-String
$sequentialState = [IO.File]::ReadAllText($sequentialStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
$sequentialResult = $sequentialState.resources.documents.result
if (
    $sequentialState.status -ne "completed" -or
    $sequentialResult.ProcessedCount -ne 5 -or
    $sequentialResult.CopiedCount -ne 2 -or
    $sequentialResult.SkippedCount -ne 3 -or
    $sequentialResult.ErrorSkippedCount -ne 2 -or
    @($sequentialResult.SkippedDocuments | Where-Object {
        $_.DocumentId -eq "bad-doc"
    }).Count -ne 1 -or
    @($sequentialResult.SkippedDocuments | Where-Object {
        $_.DocumentId -eq "<missing id>"
    }).Count -ne 1
) {
    throw "Sequential migration did not copy and record skips correctly: $($sequentialResult | ConvertTo-Json -Compress)"
}
if ($sequentialOutput -notmatch "Admin review required: 2 document") {
    throw "Sequential migration did not warn the admin about its skipped document."
}

$recoveryStatePath = "$statePath.recovery.json"
$parameters.StateFilePath = $recoveryStatePath
$parameters.MaxConcurrentDocuments = 1
$parameters.MaxRetryCount = 2
$parameters.MaxThrottleRecoveryPauses = 2
$parameters.ThrottleRecoveryPauseSeconds = 1
$global:mockSleepRecords.Clear()
$global:mockThrottleResponsesRemaining = 2
$recoveryOutput = @(& $scriptPath @parameters 3>&1 6>&1) | Out-String
$recoveryState = [IO.File]::ReadAllText($recoveryStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
$recoveryResult = $recoveryState.resources.documents.result
if (
    $recoveryState.status -ne "completed" -or
    $recoveryResult.CopiedCount -ne 2 -or
    $recoveryResult.ThrottleRecoveryPauseCount -ne 1 -or
    $global:mockThrottleResponsesRemaining -ne 0 -or
    @($global:mockSleepRecords | Where-Object { $_.Seconds -eq 1 }).Count -ne 1
) {
    throw "Exhausted 429 retries did not recover correctly: $($recoveryResult | ConvertTo-Json -Compress)"
}
if ($recoveryOutput -notmatch "Recovery pause 1/2 begins now") {
    throw "Throttling recovery warning was missing: $recoveryOutput"
}

$fullProvenanceStatePath = "$statePath.full-provenance.json"
$parameters.StateFilePath = $fullProvenanceStatePath
$parameters.DifferentialMigration = $false
$parameters.MaxConcurrentDocuments = 1
$global:mockDestinationProvenanceQueryCount = 0
$fullProvenanceOutput = @(& $scriptPath @parameters 3>&1 6>&1) | Out-String
$fullProvenanceState = [IO.File]::ReadAllText($fullProvenanceStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
$fullProvenanceResult = $fullProvenanceState.resources.documents.result
if (
    $fullProvenanceState.status -ne "completed" -or
    $fullProvenanceResult.ProcessedCount -ne 5 -or
    $fullProvenanceResult.CopiedCount -ne 1 -or
    $fullProvenanceResult.SkippedCount -ne 4 -or
    $fullProvenanceResult.ErrorSkippedCount -ne 2 -or
    $global:mockDestinationProvenanceQueryCount -ne 1 -or
    $fullProvenanceOutput -notmatch "Skipping 1 recently migrated document"
) {
    throw "Full migration did not skip the destination-marked document: $($fullProvenanceResult | ConvertTo-Json -Compress)"
}
$parameters.DifferentialMigration = $true

$exhaustedRecoveryStatePath = "$statePath.recovery-exhausted.json"
$parameters.StateFilePath = $exhaustedRecoveryStatePath
$parameters.MaxThrottleRecoveryPauses = 1
$global:mockSleepRecords.Clear()
$global:mockThrottleResponsesRemaining = 4
$exhaustedRecoveryError = $null
try {
    & $scriptPath @parameters -ErrorAction Stop 3>&1 6>&1 | Out-Null
}
catch {
    $exhaustedRecoveryError = $_
}
if (
    $null -eq $exhaustedRecoveryError -or
    $exhaustedRecoveryError.Exception.Message -notmatch "throttling recovery exhausted" -or
    $exhaustedRecoveryError.Exception.Message -notmatch "1 recovery pause" -or
    $exhaustedRecoveryError.Exception.Message -notmatch "Reduce -MaxConcurrentDocuments" -or
    @($global:mockSleepRecords | Where-Object { $_.Seconds -eq 1 }).Count -ne 1
) {
    throw "Throttling recovery exhaustion was not reported cleanly: $exhaustedRecoveryError"
}
$exhaustedRecoveryState = [IO.File]::ReadAllText($exhaustedRecoveryStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if (
    $exhaustedRecoveryState.status -ne "failed" -or
    $exhaustedRecoveryState.lastError -notmatch "throttling recovery exhausted"
) {
    throw "Throttling recovery exhaustion did not persist failed state."
}

$fatalStatePath = "$statePath.fatal.json"
$parameters.StateFilePath = $fatalStatePath
$parameters.MaxRetryCount = 1
$global:mockFatalWrites = $true
$fatalError = $null
$fatalOutput = [System.Collections.Generic.List[string]]::new()
try {
    & $scriptPath @parameters -ErrorAction Stop 3>&1 6>&1 |
        ForEach-Object { $fatalOutput.Add([string]$_) }
}
catch {
    $fatalError = $_
}
finally {
    $global:mockFatalWrites = $false
}
if ($null -eq $fatalError -or $fatalError.Exception.Message -notmatch "HTTP 503") {
    throw "A systemic destination failure was incorrectly skipped: $fatalError"
}
$fatalOutputText = $fatalOutput -join "`n"
if (
    $fatalOutputText -notmatch "Admin review required: 2 document" -or
    $fatalOutputText -notmatch "progress\.SkippedDocuments"
) {
    throw "The failed migration did not warn the admin about earlier document skips: $fatalOutputText"
}
$fatalState = [IO.File]::ReadAllText($fatalStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if (
    $fatalState.status -ne "failed" -or
    $fatalState.resources.documents.status -ne "failed" -or
    $fatalState.lastError -notmatch "HTTP 503" -or
    $fatalState.resources.documents.progress.ErrorSkippedCount -ne 2 -or
    @($fatalState.resources.documents.progress.SkippedDocuments | Where-Object {
        $_.DocumentId -eq "bad-doc" -and $_.StatusCode -eq 400
    }).Count -ne 1 -or
    @($fatalState.resources.documents.progress.SkippedDocuments | Where-Object {
        $_.DocumentId -eq "<missing id>" -and $_.Stage -eq "Preparation"
    }).Count -ne 1
) {
    throw "Systemic destination failure was not persisted as failed state: $($fatalState | ConvertTo-Json -Compress -Depth 100)"
}
'''
        harness = harness.replace(
            "__SCRIPT_PATH__", _powershell_single_quote(SCRIPT_PATH)
        ).replace("__STATE_PATH__", _powershell_single_quote(state_path))

        result = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                harness,
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise AssertionError(
            f"Cosmos migration skip-reporting harness failed with exit code {result.returncode}."
        )


if __name__ == "__main__":
    test_cosmos_migration_document_skip_reporting()
    print("Cosmos migration document skip-reporting test passed.")