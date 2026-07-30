#!/usr/bin/env python3
"""
Functional test for Storage Account migration provenance.
Version: 0.250.078
Implemented in: 0.250.074

This test ensures successful blob copies retain existing metadata, receive
migration provenance metadata, and are skipped on a later run with the same ID.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "Migration-StorageAccount.ps1"


def powershell_single_quote(value: Path) -> str:
    """Escape a path for a PowerShell single-quoted string."""
    return str(value).replace("'", "''")


def test_storage_migration_provenance() -> None:
    """Exercise blob metadata stamping and remote provenance replay avoidance."""
    powershell = shutil.which("pwsh")
    assert powershell, "PowerShell 7 is required to test the Storage migration script."

    with tempfile.TemporaryDirectory(prefix="simplechat-storage-provenance-") as temp_dir:
        state_path = Path(temp_dir) / "migration-state.json"
        harness = r'''
$ErrorActionPreference = "Stop"
$scriptPath = '__SCRIPT_PATH__'
$statePath = '__STATE_PATH__'
$global:azCopyInvocationCount = 0
$global:metadataSetCount = 0

$destinationCloudBlob = [pscustomobject]@{
    Name = "documents/report.txt"
    Metadata = [ordered]@{ existing = "preserved" }
    FetchCount = 0
}
$destinationCloudBlob | Add-Member -MemberType ScriptMethod -Name FetchAttributes -Value {
    $this.FetchCount++
}
$destinationCloudBlob | Add-Member -MemberType ScriptMethod -Name SetMetadata -Value {
    $global:metadataSetCount++
}
$global:sourceBlob = [pscustomobject]@{
    Name = "documents/report.txt"
}
$global:destinationBlob = [pscustomobject]@{
    Name = "documents/report.txt"
    ICloudBlob = $destinationCloudBlob
}

function Connect-AzAccount {
    [CmdletBinding()]
    param()
}

function Set-AzContext {
    [CmdletBinding()]
    param(
        [string]$SubscriptionId
    )
}

function New-AzStorageContext {
    [CmdletBinding()]
    param(
        [string]$StorageAccountName,
        [switch]$UseConnectedAccount
    )

    return [pscustomobject]@{ AccountName = $StorageAccountName }
}

function Get-AzStorageContainer {
    [CmdletBinding()]
    param(
        [string]$Name,
        [object]$Context
    )

    return [pscustomobject]@{ Name = $Name }
}

function New-AzStorageContainer {
    [CmdletBinding()]
    param(
        [string]$Name,
        [object]$Context
    )

    return [pscustomobject]@{ Name = $Name }
}

function New-AzStorageContainerSASToken {
    [CmdletBinding()]
    param(
        [string]$Name,
        [object]$Context,
        [string]$Permission,
        [string]$Protocol,
        [datetime]$StartTime,
        [datetime]$ExpiryTime,
        [switch]$FullUri
    )

    return "https://$($Context.AccountName).blob.core.windows.net/$Name?sig=mock"
}

function Get-AzStorageBlob {
    [CmdletBinding()]
    param(
        [string]$Container,
        [string]$Blob,
        [object]$Context
    )

    if ($Context.AccountName -eq "sourcestorage") {
        return @($global:sourceBlob)
    }
    if ($Context.AccountName -eq "destinationstorage") {
        return $global:destinationBlob
    }
    throw "Unexpected storage context: $($Context.AccountName)"
}

function azcopy {
    [CmdletBinding()]
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [object[]]$Arguments
    )

    $global:azCopyInvocationCount++
    $global:LASTEXITCODE = 0
}

$parameters = @{
    SourceStorageAccount = "sourcestorage"
    SourceSubscriptionId = "00000000-0000-0000-0000-000000000001"
    DestinationStorageAccount = "destinationstorage"
    DestinationSubscriptionId = "00000000-0000-0000-0000-000000000002"
    Containers = @("user-documents")
    DifferentialMigration = $true
    MigrationId = "11111111-1111-1111-1111-111111111111"
    SkipMigratedWithinHours = 24
    ShowProgress = $false
    StateFilePath = $statePath
}

& $scriptPath @parameters | Out-Null
$firstState = [IO.File]::ReadAllText($statePath) | ConvertFrom-Json -AsHashtable -Depth 100
$secondStatePath = "$($statePath).second"
$parameters.StateFilePath = $secondStatePath
& $scriptPath @parameters | Out-Null
$secondState = [IO.File]::ReadAllText($secondStatePath) | ConvertFrom-Json -AsHashtable -Depth 100
$firstResult = $firstState.resources["user-documents"].result
$secondResult = $secondState.resources["user-documents"].result

if (
    $firstState.status -ne "completed" -or
    $firstState.migrationId -ne $parameters.MigrationId -or
    $firstResult.SourceBlobCount -ne 1 -or
    $firstResult.TaggedBlobCount -ne 1 -or
    $firstResult.SkippedByProvenance -ne $false
) {
    throw "Unexpected first migration state: $($firstState | ConvertTo-Json -Compress -Depth 100)"
}
if (
    $destinationCloudBlob.Metadata["existing"] -ne "preserved" -or
    $destinationCloudBlob.Metadata["simplechatMigrationId"] -ne $parameters.MigrationId -or
    $destinationCloudBlob.Metadata["simplechatMigrationStatus"] -ne "succeeded" -or
    [string]::IsNullOrWhiteSpace([string]$destinationCloudBlob.Metadata["simplechatMigratedAtUtc"])
) {
    throw "Blob metadata was not preserved and stamped correctly: $($destinationCloudBlob.Metadata | ConvertTo-Json -Compress)"
}
if (
    $secondState.status -ne "completed" -or
    $secondResult.SkippedByProvenance -ne $true -or
    $secondResult.SourceBlobCount -ne 1 -or
    $global:azCopyInvocationCount -ne 1 -or
    $global:metadataSetCount -ne 1
) {
    throw "The same migration ID did not bypass the already marked blob: $($secondState | ConvertTo-Json -Compress -Depth 100)"
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
            f"Storage migration provenance harness failed with exit code {result.returncode}."
        )


if __name__ == "__main__":
    test_storage_migration_provenance()
    print("Storage migration provenance test passed.")