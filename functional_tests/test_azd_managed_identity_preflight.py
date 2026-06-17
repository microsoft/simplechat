#!/usr/bin/env python3
# test_azd_managed_identity_preflight.py
"""
Functional test for AZD managed identity RBAC preflight.
Version: 0.242.066
Implemented in: 0.242.057

This test ensures managed identity deployments fail before provisioning when
the deployment identity cannot create required RBAC assignments, and that users
are told they can switch to key-based authentication if desired.
"""

from pathlib import Path
import runpy
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PREREQUISITES = REPO_ROOT / "deployers" / "bicep" / "validate_azd_prerequisites.py"
README = REPO_ROOT / "deployers" / "bicep" / "README.md"
DEPLOYER_VERSION = REPO_ROOT / "deployers" / "version.txt"
FIX_DOC = REPO_ROOT / "docs" / "explanation" / "fixes" / "AZD_MANAGED_IDENTITY_PREFLIGHT_FIX.md"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_azd_managed_identity_preflight() -> bool:
    print("Testing AZD managed identity RBAC preflight")
    print("=" * 70)

    prerequisites_content = PREREQUISITES.read_text(encoding="utf-8")
    readme_content = README.read_text(encoding="utf-8")
    deployer_version = DEPLOYER_VERSION.read_text(encoding="utf-8").strip()
    fix_doc_content = FIX_DOC.read_text(encoding="utf-8")
    prerequisites_namespace = runpy.run_path(str(PREREQUISITES))
    permissions_allow_action = prerequisites_namespace["_permissions_allow_action"]

    require_contains(
        prerequisites_content,
        "AZURE_ENV_AUTHENTICATION_TYPE",
        "AZD managed identity auth environment lookup",
    )
    require_contains(
        prerequisites_content,
        "Microsoft.Authorization/roleAssignments/write",
        "role assignment write preflight action",
    )
    require_contains(
        prerequisites_content,
        "Microsoft.Authorization/roleDefinitions/write",
        "role definition write preflight action",
    )
    require_contains(
        prerequisites_content,
        "permissions?api-version=2022-04-01",
        "effective permissions REST query",
    )
    require_contains(
        prerequisites_content,
        "azd env set AUTHENTICATION_TYPE key",
        "key authentication remediation guidance",
    )
    require_contains(
        readme_content,
        "managed_identity",
        "README managed identity guidance",
    )
    require_contains(
        readme_content,
        "azd env set AUTHENTICATION_TYPE key",
        "README key fallback guidance",
    )
    require_contains(
        fix_doc_content,
        "Deployer version: **1.0.15**",
        "fix documentation deployer version",
    )

    assert deployer_version == "1.0.15", "Expected deployers/version.txt to be bumped to 1.0.15."
    assert permissions_allow_action(
        [{"actions": ["*"], "notActions": []}],
        "Microsoft.Authorization/roleAssignments/write",
    )
    assert permissions_allow_action(
        [{"actions": ["Microsoft.Authorization/roleAssignments/*"], "notActions": []}],
        "Microsoft.Authorization/roleAssignments/write",
    )
    assert not permissions_allow_action(
        [
            {
                "actions": ["Microsoft.Authorization/*"],
                "notActions": ["Microsoft.Authorization/roleAssignments/write"],
            }
        ],
        "Microsoft.Authorization/roleAssignments/write",
    )

    print("Managed identity preflight checks auth selection and effective RBAC permissions.")
    print("Failure guidance tells users how to switch to key-based authentication.")
    return True


if __name__ == "__main__":
    try:
        success = test_azd_managed_identity_preflight()
    except Exception as ex:
        print(f"Test failed: {ex}")
        raise

    sys.exit(0 if success else 1)