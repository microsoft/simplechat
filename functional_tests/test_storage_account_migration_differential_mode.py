# test_storage_account_migration_differential_mode.py
#!/usr/bin/env python3
"""
Functional test for robust storage account migration.
Version: 0.250.064
Implemented in: 0.250.062
Resume-state coverage added in: 0.250.064

This test ensures that differential migration uses AzCopy sync without deleting
destination blobs, full migration retains overwrite behavior, and migration
setup handles parameters, contexts, destination containers, and failures.
"""

from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "Migration-StorageAccount.ps1"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_storage_account_migration_differential_mode() -> None:
    """Validate robust setup and differential/full AzCopy command contracts."""
    print("Testing differential storage account migration")
    print("=" * 60)

    powershell = shutil.which("pwsh")
    if not powershell:
        raise AssertionError("PowerShell 7 is required to test the migration script.")

    script_content = SCRIPT_PATH.read_text(encoding="utf-8")
    differential_marker = "        if ($DifferentialMigration) {"
    full_marker = "        else {"
    invocation_marker = "        & azcopy @azCopyArguments"

    require_contains(
        script_content,
        "[bool]$DifferentialMigration = $true",
        "enabled-by-default differential migration parameter",
    )
    for expected_default in (
        '[string]$SourceStorageAccount = "<source-account>"',
        '[string]$SourceSubscriptionId = "<source-subscription-id>"',
        '[string]$DestinationStorageAccount = "<destination-account>"',
        '[string]$DestinationSubscriptionId = "<destination-subscription-id>"',
    ):
        require_contains(script_content, expected_default, "editable parameter default")
    require_contains(script_content, differential_marker, "differential branch")
    require_contains(script_content, full_marker, "full migration branch")
    require_contains(script_content, invocation_marker, "AzCopy invocation")

    differential_branch = script_content.split(differential_marker, maxsplit=1)[1].split(
        full_marker,
        maxsplit=1,
    )[0]
    full_branch = script_content.split(full_marker, maxsplit=1)[1].split(
        invocation_marker,
        maxsplit=1,
    )[0]

    require_contains(differential_branch, '"sync"', "differential AzCopy operation")
    require_contains(
        differential_branch,
        '"--delete-destination=false"',
        "destination deletion protection",
    )
    if '"--overwrite=true"' in differential_branch:
        raise AssertionError("Differential migration must not force overwrites")

    require_contains(full_branch, '"copy"', "full migration AzCopy operation")
    require_contains(full_branch, '"--overwrite=true"', "full migration overwrite behavior")
    if '"--delete-destination=false"' in full_branch:
        raise AssertionError("Full migration must not use sync-only arguments")

    require_contains(script_content, "$LASTEXITCODE -ne 0", "AzCopy failure handling")

    script_path = str(SCRIPT_PATH).replace("'", "''")
    harness = rf'''
$ErrorActionPreference = "Stop"
$scriptPath = '{script_path}'
$sourceSubscriptionId = "00000000-0000-0000-0000-000000000001"
$destinationSubscriptionId = "00000000-0000-0000-0000-000000000002"
$script:currentSubscription = $null
$script:connectCount = 0
$script:contextCreations = @()
$script:setContextCalls = @()
$script:createdContainers = @()
$script:sasRecords = @()
$script:azCopyCalls = @()
$script:azCopyExitCode = 0
$script:progressRecords = @()
$script:destinationContainers = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
[void]$script:destinationContainers.Add("user-documents")

function Write-Progress {{
    [CmdletBinding()]
    param(
        [int]$Id,
        [string]$Activity,
        [string]$Status,
        [string]$CurrentOperation,
        [int]$PercentComplete,
        [switch]$Completed
    )

    $script:progressRecords += [pscustomobject]@{{
        Id = $Id
        Activity = $Activity
        Status = $Status
        CurrentOperation = $CurrentOperation
        PercentComplete = $PercentComplete
        Completed = $Completed.IsPresent
    }}
}}

function Connect-AzAccount {{
    [CmdletBinding()]
    param()

    $script:connectCount++
}}

function Set-AzContext {{
    [CmdletBinding()]
    param([string]$SubscriptionId)

    $script:currentSubscription = $SubscriptionId
    $script:setContextCalls += $SubscriptionId
    return [pscustomobject]@{{ SubscriptionId = $SubscriptionId }}
}}

function New-AzStorageContext {{
    [CmdletBinding()]
    param(
        [string]$StorageAccountName,
        [switch]$UseConnectedAccount
    )

    $script:contextCreations += [pscustomobject]@{{
        StorageAccountName = $StorageAccountName
        SubscriptionId = $script:currentSubscription
        UsesConnectedAccount = $UseConnectedAccount.IsPresent
    }}
    return [pscustomobject]@{{ StorageAccountName = $StorageAccountName }}
}}

function Get-AzStorageContainer {{
    [CmdletBinding()]
    param(
        [string]$Name,
        [object]$Context
    )

    if ($Context.StorageAccountName -eq "sourceacct") {{
        return [pscustomobject]@{{ Name = $Name }}
    }}
    if ($script:destinationContainers.Contains($Name)) {{
        return [pscustomobject]@{{ Name = $Name }}
    }}
    return $null
}}

function New-AzStorageContainer {{
    [CmdletBinding()]
    param(
        [string]$Name,
        [object]$Context
    )

    [void]$script:destinationContainers.Add($Name)
    $script:createdContainers += [pscustomobject]@{{
        Name = $Name
        StorageAccountName = $Context.StorageAccountName
    }}
    return [pscustomobject]@{{ Name = $Name }}
}}

function New-AzStorageContainerSASToken {{
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

    $script:sasRecords += [pscustomobject]@{{
        Name = $Name
        StorageAccountName = $Context.StorageAccountName
        Permission = $Permission
        Protocol = $Protocol
        StartTime = $StartTime
        ExpiryTime = $ExpiryTime
        FullUri = $FullUri.IsPresent
    }}
    return "https://$($Context.StorageAccountName).blob.core.windows.net/$Name`?sig=$Permission"
}}

function azcopy {{
    [CmdletBinding()]
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    $script:azCopyCalls += ,@($Arguments)
    $global:LASTEXITCODE = $script:azCopyExitCode
}}

$stateDirectory = Join-Path ([IO.Path]::GetTempPath()) "simplechat-storage-state-$PID-$([Guid]::NewGuid().ToString('N'))"
[IO.Directory]::CreateDirectory($stateDirectory) | Out-Null
$differentialStatePath = Join-Path $stateDirectory "differential.json"
$fullStatePath = Join-Path $stateDirectory "full.json"
$failureStatePath = Join-Path $stateDirectory "failure.json"
$commonParameters = @{{
    SourceStorageAccount = "sourceacct"
    SourceSubscriptionId = $sourceSubscriptionId
    DestinationStorageAccount = "destinationacct"
    DestinationSubscriptionId = $destinationSubscriptionId
    Containers = @("user-documents", "group-documents")
    SasExpiryHours = 2
    StateFilePath = $differentialStatePath
}}

& $scriptPath @commonParameters -DifferentialMigration $true -ShowProgress $true

if ($script:connectCount -ne 1) {{
    throw "Migration did not connect exactly once."
}}
if ($script:contextCreations.Count -ne 2) {{
    throw "Migration did not create exactly two storage contexts."
}}
if (
    $script:contextCreations[0].StorageAccountName -ne "sourceacct" -or
    $script:contextCreations[0].SubscriptionId -ne $sourceSubscriptionId -or
    -not $script:contextCreations[0].UsesConnectedAccount
) {{
    throw "Source context was not created under the source subscription."
}}
if (
    $script:contextCreations[1].StorageAccountName -ne "destinationacct" -or
    $script:contextCreations[1].SubscriptionId -ne $destinationSubscriptionId -or
    -not $script:contextCreations[1].UsesConnectedAccount
) {{
    throw "Destination context was not created under the destination subscription."
}}
if (
    $script:createdContainers.Count -ne 1 -or
    $script:createdContainers[0].Name -ne "group-documents" -or
    $script:createdContainers[0].StorageAccountName -ne "destinationacct"
) {{
    throw "Migration did not create only the missing destination container."
}}
if ($script:azCopyCalls.Count -ne 2) {{
    throw "Differential migration did not invoke AzCopy once per container."
}}
foreach ($arguments in $script:azCopyCalls) {{
    if ($arguments[0] -ne "sync") {{
        throw "Differential migration did not use AzCopy sync."
    }}
    if ($arguments -notcontains "--delete-destination=false") {{
        throw "Differential migration did not disable destination deletion."
    }}
    if ($arguments -contains "--overwrite=true") {{
        throw "Differential migration unexpectedly forced overwrites."
    }}
    if (
        $arguments[1] -notmatch '^https://sourceacct\.blob\.core\.windows\.net/' -or
        $arguments[2] -notmatch '^https://destinationacct\.blob\.core\.windows\.net/'
    ) {{
        throw "Explicit account parameters did not override script defaults."
    }}
}}
if ($script:sasRecords.Count -ne 4) {{
    throw "Migration did not create source and destination SAS URLs for each container."
}}
foreach ($sasRecord in $script:sasRecords) {{
    $sasDurationHours = ($sasRecord.ExpiryTime - $sasRecord.StartTime).TotalHours
    if ([Math]::Abs($sasDurationHours - 2.25) -gt 0.02) {{
        throw "Configured SAS lifetime was not honored."
    }}
    if ($sasRecord.Protocol -ne "HttpsOnly" -or -not $sasRecord.FullUri) {{
        throw "SAS URL security options were not applied."
    }}
}}
if (@($script:progressRecords | Where-Object {{
    $_.PercentComplete -eq 50 -and
    $_.Status -eq "Containers: 1/2 | Remaining: 1 | 50%"
}}).Count -eq 0) {{
    throw "Migration did not report the expected container midpoint."
}}
if (@($script:progressRecords | Where-Object {{ $_.Completed }}).Count -eq 0) {{
    throw "Migration progress was not marked complete."
}}

$differentialStateJson = [IO.File]::ReadAllText($differentialStatePath)
$differentialState = $differentialStateJson | ConvertFrom-Json -AsHashtable -Depth 100
if ($differentialState.status -ne "completed" -or $differentialState.resources.Count -ne 2) {{
    throw "Differential Storage state did not record both completed containers."
}}
if (@($differentialState.resources.Values | Where-Object {{ $_.status -ne "completed" }}).Count -gt 0) {{
    throw "Differential Storage state contains a non-completed container."
}}
if ($differentialStateJson -match "sig=|racwdlt") {{
    throw "Storage migration state persisted a SAS URL or permission token."
}}

$azCopyCountBeforeResume = $script:azCopyCalls.Count
& $scriptPath @commonParameters -DifferentialMigration $true -ShowProgress $false
if ($script:azCopyCalls.Count -ne $azCopyCountBeforeResume) {{
    throw "Resumed Storage migration repeated a completed container transfer."
}}
$resumedState = [IO.File]::ReadAllText($differentialStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if ($resumedState.status -ne "completed" -or $resumedState.resumeCount -ne 1) {{
    throw "Resumed Storage migration did not retain and complete its state."
}}

$script:azCopyCalls = @()
$progressRecordCount = $script:progressRecords.Count
$fullParameters = $commonParameters.Clone()
$fullParameters.StateFilePath = $fullStatePath
& $scriptPath @fullParameters -DifferentialMigration $false -ShowProgress $false

if ($script:azCopyCalls.Count -ne 2) {{
    throw "Full migration did not invoke AzCopy once per container."
}}
foreach ($arguments in $script:azCopyCalls) {{
    if ($arguments[0] -ne "copy" -or $arguments -notcontains "--overwrite=true") {{
        throw "Full migration did not use overwriting AzCopy copy."
    }}
    if ($arguments -contains "--delete-destination=false") {{
        throw "Full migration unexpectedly used sync-only arguments."
    }}
}}
if ($script:progressRecords.Count -ne $progressRecordCount) {{
    throw "ShowProgress false did not suppress progress records."
}}

$placeholderRejected = $false
try {{
    & $scriptPath -ShowProgress $false
}}
catch {{
    if ($_ -match "Set 'SourceStorageAccount'") {{
        $placeholderRejected = $true
    }}
    else {{
        throw
    }}
}}
if (-not $placeholderRejected) {{
    throw "Unresolved hardcoded placeholders were not rejected."
}}

$script:azCopyExitCode = 17
$azCopyFailurePropagated = $false
try {{
    & $scriptPath @commonParameters `
        -Containers @("user-documents") `
        -DifferentialMigration $true `
        -StateFilePath $failureStatePath `
        -ShowProgress $false
}}
catch {{
    if ($_ -match "AzCopy failed for container 'user-documents' with exit code 17") {{
        $azCopyFailurePropagated = $true
    }}
    else {{
        throw
    }}
}}
$global:LASTEXITCODE = 0
if (-not $azCopyFailurePropagated) {{
    throw "AzCopy failure did not stop the migration with container context."
}}
$failureState = [IO.File]::ReadAllText($failureStatePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if (
    $failureState.status -ne "failed" -or
    $failureState.resources["user-documents"].status -ne "failed"
) {{
    throw "Storage migration failure was not recorded for restart."
}}

[IO.Directory]::Delete($stateDirectory, $true)
Write-Output "Storage migration mock checks passed."
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
            "Mock storage migration failed.\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    if "Storage migration mock checks passed." not in result.stdout:
        raise AssertionError(f"Expected success output was missing:\n{result.stdout}")

    print("Differential migration uses non-destructive AzCopy sync")
    print("Full migration retains overwrite behavior")


if __name__ == "__main__":
    try:
        test_storage_account_migration_differential_mode()
    except Exception as exc:
        print(f"Test failed: {exc}")
        raise

    sys.exit(0)