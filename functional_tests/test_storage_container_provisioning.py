# test_storage_container_provisioning.py
"""Private deployment container parity and real CLI block execution over a fake az.

Version: 0.261.396
Implemented in: 0.261.396
"""

from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
from blob_container_readiness import APPLICATION_BLOB_CONTAINERS


SCRIPT = ROOT / "deployers" / "azurecli" / "deploy-simplechat.ps1"


def provisioning_block():
    source = SCRIPT.read_text(encoding="utf-8")
    return source.split("# --- Ensure private application containers", 1)[1].split(
        "# --- Create User-Assigned Managed Identity ---", 1,
    )[0].split("\n", 1)[1]


def test_bicep_and_cli_inventory_match_application():
    source = (ROOT / "deployers" / "bicep" / "modules" / "storageAccount.bicep").read_text(encoding="utf-8")
    containers = re.findall(
        r"resource \w+ 'Microsoft\.Storage/storageAccounts/blobServices/containers@[^']+' = \{(.*?)\n\}",
        source, re.DOTALL,
    )
    names = {re.search(r"name: '([^']+)'", block).group(1) for block in containers}
    assert names == set(APPLICATION_BLOB_CONTAINERS)
    assert all("publicAccess: 'None'" in block for block in containers)
    block = provisioning_block()
    inventory = block.split("$existingStorageContainersJson", 1)[0]
    assert set(re.findall(r"'([a-z-]+)'", inventory)) == names
    assert "container-rm" in block and "list-keys" not in block and "--public-access off" in block
    upgrade = (ROOT / "deployers" / "azurecli" / "upgrade-simplechat.ps1").read_text(encoding="utf-8")
    assert "container-rm" not in upgrade


@pytest.mark.parametrize("existing", [[], ["user-documents", "group-documents"]])
def test_full_deploy_creates_only_missing_containers(existing):
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is needed to execute the deployment snippet.")
    names = ",".join(f"'{name}'" for name in existing)
    probe = r'''
$ErrorActionPreference = 'Stop'
$global:stored = @(__EXISTING__)
$global:created = @()
function az {
    $global:LASTEXITCODE = 0
    if ($args[2] -eq 'list') { ConvertTo-Json -InputObject @($global:stored) -Compress; return }
    if ($args[2] -ne 'create') { throw 'Unexpected Azure command' }
    $name = $args[4]
    if ($global:stored -contains $name) { throw 'Recreated an existing container' }
    $global:created += $name
    $global:stored += $name
}
$storageAccountName = 'fixture'
$resourceGroupName = 'fixture-rg'
__BLOCK__
$count = $global:created.Count
if ($count -ne __COUNT__) { throw 'Incorrect missing container count' }
__BLOCK__
if ($global:created.Count -ne $count) { throw 'Deployment was not idempotent' }
'''
    probe = probe.replace("__EXISTING__", names).replace("__BLOCK__", provisioning_block()).replace(
        "__COUNT__", str(5 - len(existing)),
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", probe],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
