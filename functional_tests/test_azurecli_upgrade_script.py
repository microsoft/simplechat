#!/usr/bin/env python3
# test_azurecli_upgrade_script.py
"""
Functional test for Azure CLI code-only upgrade script.
Version: 0.241.095
Implemented in: 0.241.079

This test ensures that the Azure CLI deployer includes a standalone upgrade
script and documentation for building a new image in ACR and updating the
existing App Service container configuration.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
UPGRADE_SCRIPT = REPO_ROOT / "deployers" / "azurecli" / "upgrade-simplechat.ps1"
DEPLOYER_README = REPO_ROOT / "deployers" / "azurecli" / "README.md"
REFERENCE_DOC = REPO_ROOT / "docs" / "reference" / "deploy" / "azurecli_powershell_deploy.md"
UPGRADE_GUIDE = REPO_ROOT / "docs" / "how-to" / "upgrade_paths.md"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_azurecli_upgrade_script() -> bool:
    print("🧪 Testing Azure CLI PowerShell upgrade script")
    print("=" * 70)

    script_content = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    readme_content = DEPLOYER_README.read_text(encoding="utf-8")
    reference_content = REFERENCE_DOC.read_text(encoding="utf-8")
    upgrade_guide_content = UPGRADE_GUIDE.read_text(encoding="utf-8")

    require_contains(
        script_content,
        "function Invoke-AcrContainerBuild",
        "ACR build helper",
    )
    require_contains(
        script_content,
        "az acr build",
        "Azure CLI ACR build command",
    )
    require_contains(
        script_content,
        "az webapp config container set",
        "Azure CLI web app container update command",
    )
    require_contains(
        script_content,
        "az webapp restart",
        "Azure CLI web app restart command",
    )
    require_contains(
        script_content,
        'ResourceGroupName = "sc-$($BaseName)-$($Environment)-rg".ToLower()',
        "default Azure CLI deployer resource-group naming",
    )
    require_contains(
        script_content,
        "Specify either both -ResourceGroupName and -WebAppName, or both -BaseName and -Environment.",
        "target resolution guidance",
    )

    require_contains(
        readme_content,
        "upgrade-simplechat.ps1",
        "README upgrade script reference",
    )
    require_contains(
        reference_content,
        "upgrade-simplechat.ps1",
        "deployment reference upgrade script reference",
    )
    require_contains(
        upgrade_guide_content,
        "upgrade-simplechat.ps1",
        "upgrade guide Azure CLI upgrade script reference",
    )

    print("✅ Azure CLI upgrade script includes ACR build and web app container update flow")
    print("✅ Azure CLI deployment docs reference the PowerShell upgrade path")
    return True


if __name__ == "__main__":
    try:
        success = test_azurecli_upgrade_script()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)
