# test_migration_state_checkpoint.py
#!/usr/bin/env python3
"""
Functional test for shared migration JSON checkpoints.
Version: 0.250.064
Implemented in: 0.250.064

This test ensures migration state is atomic, configuration-bound, resumable,
resettable only by explicit request, and safe for failure recovery.
"""

from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "Migration-State.ps1"


def test_migration_state_checkpoint() -> None:
    """Exercise the shared checkpoint lifecycle in PowerShell."""
    powershell = shutil.which("pwsh")
    if not powershell:
        raise AssertionError("PowerShell 7 is required to test migration state.")

    script_path = str(SCRIPT_PATH).replace("'", "''")
    harness = rf'''
$ErrorActionPreference = "Stop"
. '{script_path}'

$stateDirectory = Join-Path ([IO.Path]::GetTempPath()) "simplechat-state-helper-$PID-$([Guid]::NewGuid().ToString('N'))"
[IO.Directory]::CreateDirectory($stateDirectory) | Out-Null
$statePath = Join-Path $stateDirectory "checkpoint.json"
$configurationA = [ordered]@{{
    source = "source-a"
    destination = "destination-a"
    mode = "differential"
}}
$configurationB = [ordered]@{{
    source = "source-a"
    destination = "destination-b"
    mode = "differential"
}}

$context = Initialize-MigrationState `
    -MigrationType "test" `
    -StateFilePath $statePath `
    -Configuration $configurationA
Start-MigrationResourceCheckpoint -Context $context -ResourceName "resource-a"

$inProgressState = [IO.File]::ReadAllText($statePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if (
    $inProgressState.status -ne "in_progress" -or
    $inProgressState.resources["resource-a"].status -ne "in_progress"
) {{
    throw "Started resource was not persisted as in progress."
}}

$resumedContext = Initialize-MigrationState `
    -MigrationType "test" `
    -StateFilePath $statePath `
    -Configuration $configurationA
if (Test-MigrationResourceCompleted -Context $resumedContext -ResourceName "resource-a") {{
    throw "An interrupted resource was incorrectly treated as completed."
}}
Start-MigrationResourceCheckpoint -Context $resumedContext -ResourceName "resource-a"
Complete-MigrationResourceCheckpoint `
    -Context $resumedContext `
    -ResourceName "resource-a" `
    -Result @{{ CopiedCount = 4 }}
Complete-MigrationState -Context $resumedContext -Summary @{{ ResourceCount = 1 }}

$completedState = [IO.File]::ReadAllText($statePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if (
    $completedState.status -ne "completed" -or
    $completedState.resumeCount -ne 1 -or
    $completedState.resources["resource-a"].attempt -ne 2 -or
    $completedState.resources["resource-a"].result.CopiedCount -ne 4
) {{
    throw "Completed resource state did not retain resume metadata and results."
}}

$mismatchRejected = $false
try {{
    Initialize-MigrationState `
        -MigrationType "test" `
        -StateFilePath $statePath `
        -Configuration $configurationB | Out-Null
}}
catch {{
    if ($_ -match "does not match the current source, destination, or mode") {{
        $mismatchRejected = $true
    }}
    else {{
        throw
    }}
}}
if (-not $mismatchRejected) {{
    throw "A checkpoint from different configuration was accepted."
}}

$resetContext = Initialize-MigrationState `
    -MigrationType "test" `
    -StateFilePath $statePath `
    -Configuration $configurationB `
    -Reset
if ($resetContext.Data.resources.Count -ne 0 -or $resetContext.Data.resumeCount -ne 0) {{
    throw "Explicit reset retained resources from the old checkpoint."
}}
Start-MigrationResourceCheckpoint -Context $resetContext -ResourceName "resource-b"
Set-MigrationStateFailure `
    -Context $resetContext `
    -ResourceName "resource-b" `
    -ErrorMessage "mock failure"
$failedState = [IO.File]::ReadAllText($statePath) |
    ConvertFrom-Json -AsHashtable -Depth 100
if (
    $failedState.status -ne "failed" -or
    $failedState.resources["resource-b"].status -ne "failed" -or
    $failedState.lastError -ne "mock failure"
) {{
    throw "Failure state was not persisted for restart."
}}
if (@(Get-ChildItem -LiteralPath $stateDirectory -Filter "*.tmp").Count -ne 0) {{
    throw "Atomic state writes left a temporary file behind."
}}

[IO.Directory]::Delete($stateDirectory, $true)
Write-Output "Migration state helper checks passed."
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
            f"Migration state helper harness failed with exit code {result.returncode}."
        )
    if "Migration state helper checks passed." not in result.stdout:
        raise AssertionError(f"Expected success output was missing:\n{result.stdout}")


if __name__ == "__main__":
    test_migration_state_checkpoint()
    print("Migration state checkpoint test passed.")