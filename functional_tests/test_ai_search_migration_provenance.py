#!/usr/bin/env python3
"""
Functional test for AI Search migration provenance.
Version: 0.250.067
Implemented in: 0.250.074

This test ensures AI Search migrations add provenance fields, tag copied
documents, and skip destination documents migrated within the configured window.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "Migration-AISearch.ps1"


def powershell_single_quote(value: Path) -> str:
    """Escape a path for a PowerShell single-quoted string."""
    return str(value).replace("'", "''")


def test_ai_search_migration_provenance() -> None:
    """Exercise schema tagging and recent destination document bypass behavior."""
    powershell = shutil.which("pwsh")
    assert powershell, "PowerShell 7 is required to test the AI Search migration script."

    with tempfile.TemporaryDirectory(prefix="simplechat-ai-search-provenance-") as temp_dir:
        state_path = Path(temp_dir) / "migration-state.json"
        harness = r'''
$ErrorActionPreference = "Stop"
$scriptPath = '__SCRIPT_PATH__'
$statePath = '__STATE_PATH__'
$global:updatedIndex = $null
$global:writtenDocuments = [System.Collections.Generic.List[object]]::new()
$global:provenanceQueryCount = 0

function Convert-MockRequestBody {
    param(
        [AllowNull()]
        [object]$Body
    )

    if ($Body -is [string]) {
        return $Body | ConvertFrom-Json -Depth 100
    }
    return $Body
}

function Invoke-RestMethod {
    [CmdletBinding()]
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers,
        [AllowNull()]
        [object]$Body,
        [string]$ContentType,
        [int]$TimeoutSec
    )

    $isSource = $Uri.StartsWith("https://source-search.")
    $isDestination = $Uri.StartsWith("https://destination-search.")
    if (-not $isSource -and -not $isDestination) {
        throw "Unexpected endpoint: $Uri"
    }

    if ($Method -eq "GET" -and $Uri -match "/synonymmaps\?") {
        return [pscustomobject]@{ value = @() }
    }

    if ($Method -eq "GET" -and $Uri -match "/indexes\?") {
        $index = [pscustomobject]@{
            name = "documents"
            fields = @(
                [pscustomobject]@{
                    name = "id"
                    type = "Edm.String"
                    key = $true
                    filterable = $true
                    sortable = $true
                    retrievable = $true
                },
                [pscustomobject]@{
                    name = "content"
                    type = "Edm.String"
                    searchable = $true
                    retrievable = $true
                }
            )
        }
        return [pscustomobject]@{ value = @($index) }
    }

    if ($Method -eq "GET" -and $Uri -match "/indexes/documents/docs/\$count\?") {
        if ($isSource) {
            return 2
        }
        return 1
    }

    if ($Method -eq "PUT" -and $isDestination -and $Uri -match "/indexes/documents\?") {
        $global:updatedIndex = Convert-MockRequestBody -Body $Body
        return [pscustomobject]@{}
    }

    if ($Method -eq "POST" -and $isDestination -and $Uri -match "/indexes/documents/docs/search\?") {
        $request = Convert-MockRequestBody -Body $Body
        if ([string]$request.filter -notmatch "simplechatMigrationStatus") {
            throw "Destination provenance lookup did not include the migration filter."
        }
        $global:provenanceQueryCount++
        return [pscustomobject]@{
            value = @([pscustomobject]@{ id = "recent-migrated-doc" })
        }
    }

    if ($Method -eq "POST" -and $isSource -and $Uri -match "/indexes/documents/docs/search\?") {
        return [pscustomobject]@{
            value = @(
                [pscustomobject]@{ id = "recent-migrated-doc"; content = "skip" },
                [pscustomobject]@{ id = "copy-doc"; content = "copy" }
            )
        }
    }

    if ($Method -eq "POST" -and $isDestination -and $Uri -match "/indexes/documents/docs/index\?") {
        $request = Convert-MockRequestBody -Body $Body
        foreach ($document in @($request.value)) {
            $global:writtenDocuments.Add($document)
        }
        return [pscustomobject]@{
            value = @($request.value | ForEach-Object {
                [pscustomobject]@{
                    key = $_.id
                    status = $true
                    statusCode = 200
                    errorMessage = ""
                }
            })
        }
    }

    throw "Unexpected mock request: $Method $Uri"
}

$parameters = @{
    SourceSearchService = "source-search"
    SourceResourceGroup = "source-rg"
    SourceSubscriptionId = "00000000-0000-0000-0000-000000000001"
    SourceAdminKey = "source-admin-key"
    DestinationSearchService = "destination-search"
    DestinationResourceGroup = "destination-rg"
    DestinationSubscriptionId = "00000000-0000-0000-0000-000000000002"
    DestinationAdminKey = "destination-admin-key"
    DifferentialMigration = $false
    MigrationId = "11111111-1111-1111-1111-111111111111"
    SkipMigratedWithinHours = 24
    ShowProgress = $false
    BatchSize = 100
    MaxConcurrentBatches = 1
    PageSize = 100
    StateFilePath = $statePath
}

& $scriptPath @parameters | Out-Null
$state = [IO.File]::ReadAllText($statePath) | ConvertFrom-Json -AsHashtable -Depth 100
$fieldNames = @($global:updatedIndex.fields | ForEach-Object { $_.name })
$writtenDocuments = @($global:writtenDocuments)

if (
    $state.status -ne "completed" -or
    $state.migrationId -ne $parameters.MigrationId -or
    $state.summary.CopiedCount -ne 1 -or
    $state.summary.SkippedCount -ne 1
) {
    throw "Unexpected migration state: $($state | ConvertTo-Json -Compress -Depth 100)"
}
if (
    $global:provenanceQueryCount -ne 1 -or
    @("simplechatMigrationId", "simplechatMigratedAtUtc", "simplechatMigrationStatus" | Where-Object {
        $fieldNames -notcontains $_
    }).Count -ne 0
) {
    throw "The destination index was not updated with migration provenance fields: $($global:updatedIndex | ConvertTo-Json -Compress -Depth 100)"
}
if ($writtenDocuments.Count -ne 1 -or $writtenDocuments[0].id -ne "copy-doc") {
    throw "Recently migrated documents were not bypassed: $($writtenDocuments | ConvertTo-Json -Compress -Depth 100)"
}
$writtenDocument = $writtenDocuments[0]
if (
    $writtenDocument.simplechatMigrationId -ne $parameters.MigrationId -or
    $writtenDocument.simplechatMigrationStatus -ne "succeeded" -or
    [string]::IsNullOrWhiteSpace([string]$writtenDocument.simplechatMigratedAtUtc)
) {
    throw "Copied document did not include migration provenance: $($writtenDocument | ConvertTo-Json -Compress -Depth 100)"
}
'''
        harness = harness.replace(
            "__SCRIPT_PATH__", powershell_single_quote(SCRIPT_PATH)
        ).replace("__STATE_PATH__", powershell_single_quote(state_path))

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
            f"AI Search migration provenance harness failed with exit code {result.returncode}."
        )


if __name__ == "__main__":
    test_ai_search_migration_provenance()
    print("AI Search migration provenance test passed.")