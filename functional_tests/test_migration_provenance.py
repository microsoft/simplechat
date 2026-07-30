#!/usr/bin/env python3
"""
Functional test for migration provenance metadata.
Version: 0.250.078
Implemented in: 0.250.074

This test ensures that migration IDs, timestamps, success states, and replay
eligibility are represented consistently for Cosmos, AI Search, and Storage.
"""

import json
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_SCRIPT = REPO_ROOT / "scripts" / "Migration-Provenance.ps1"
STATE_SCRIPT = REPO_ROOT / "scripts" / "Migration-State.ps1"


def run_provenance_script(command: str) -> dict:
    """Run a focused PowerShell provenance check and parse its JSON result."""
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    assert powershell, "PowerShell 7 or Windows PowerShell is required for this test."

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_migration_provenance_metadata_and_skip_rules() -> None:
    """Verify one provenance contract across all migrated resource types."""
    script_path = str(PROVENANCE_SCRIPT).replace("'", "''")
    state_script_path = str(STATE_SCRIPT).replace("'", "''")
    command = f"""
    $ErrorActionPreference = 'Stop'
    . '{script_path}'
    . '{state_script_path}'
    $context = New-MigrationProvenanceContext `
        -MigrationId '11111111-1111-1111-1111-111111111111' `
        -MigratedAtUtc '2026-07-24T10:00:00.0000000+00:00' `
        -SkipMigratedWithinHours 24
    $statePath = Join-Path ([IO.Path]::GetTempPath()) "simplechat-provenance-$([Guid]::NewGuid().ToString('N')).json"
    $stateConfiguration = [ordered]@{{ source = 'source'; destination = 'destination' }}
    $initialState = Initialize-MigrationState `
        -MigrationType 'provenance' `
        -StateFilePath $statePath `
        -Configuration $stateConfiguration `
        -MigrationId $context.MigrationId `
        -Reset
    $resumedState = Initialize-MigrationState `
        -MigrationType 'provenance' `
        -StateFilePath $statePath `
        -Configuration $stateConfiguration `
        -MigrationId $context.MigrationId
    $record = New-MigrationProvenanceRecord -Context $context
    $cosmosDocument = [ordered]@{{ id = 'document-1' }}
    Add-CosmosMigrationProvenance -Document $cosmosDocument -Context $context
    $searchDocument = [pscustomobject]@{{ id = 'document-1'; '@search.action' = 'upload' }}
    Add-AISearchMigrationProvenance -Document $searchDocument -Context $context
    $storageMetadata = Merge-StorageMigrationProvenance `
        -Metadata ([ordered]@{{ custom = 'preserved' }}) `
        -Context $context
    $recentRecord = [ordered]@{{
        migrationId = '22222222-2222-2222-2222-222222222222'
        migratedAtUtc = [DateTimeOffset]::UtcNow.AddHours(-1).ToString('o')
        status = 'succeeded'
    }}
    $staleRecord = [ordered]@{{
        migrationId = '33333333-3333-3333-3333-333333333333'
        migratedAtUtc = [DateTimeOffset]::UtcNow.AddHours(-25).ToString('o')
        status = 'succeeded'
    }}
    $failedRecord = [ordered]@{{
        migrationId = $context.MigrationId
        migratedAtUtc = $context.MigratedAtUtc
        status = 'failed'
    }}
    [ordered]@{{
        migrationId = $context.MigrationId
        stateMigrationId = $initialState.Data.migrationId
        resumedStateMigrationId = $resumedState.Data.migrationId
        record = $record
        sameMigrationSkipped = Test-MigrationProvenanceSkip -Provenance $record -Context $context
        recentMigrationSkipped = Test-MigrationProvenanceSkip -Provenance $recentRecord -Context $context
        staleMigrationSkipped = Test-MigrationProvenanceSkip -Provenance $staleRecord -Context $context
        failedMigrationSkipped = Test-MigrationProvenanceSkip -Provenance $failedRecord -Context $context
        cosmos = Get-CosmosMigrationProvenance -Document $cosmosDocument
        search = Get-AISearchMigrationProvenance -Document $searchDocument
        storage = Get-StorageMigrationProvenance -Metadata $storageMetadata
        customStorageMetadata = $storageMetadata['custom']
    }} | ConvertTo-Json -Depth 10 -Compress
    Remove-Item -LiteralPath $statePath -Force
    """

    result = run_provenance_script(command)

    assert result["migrationId"] == "11111111-1111-1111-1111-111111111111"
    assert result["stateMigrationId"] == result["migrationId"]
    assert result["resumedStateMigrationId"] == result["migrationId"]
    assert result["record"]["status"] == "succeeded"
    assert result["sameMigrationSkipped"] is True
    assert result["recentMigrationSkipped"] is True
    assert result["staleMigrationSkipped"] is False
    assert result["failedMigrationSkipped"] is False
    assert result["cosmos"] == result["record"]
    assert result["search"] == result["record"]
    assert result["storage"] == result["record"]
    assert result["customStorageMetadata"] == "preserved"