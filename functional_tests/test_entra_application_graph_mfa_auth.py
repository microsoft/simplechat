# test_entra_application_graph_mfa_auth.py
#!/usr/bin/env python3
"""
Functional test for Entra application Microsoft Graph MFA authentication handling.
Version: 0.241.018
Implemented in: 0.241.010

This test ensures that Initialize-EntraApplication.ps1 validates Microsoft Graph
Azure CLI access before app registration operations, recovers from interactive
MFA challenges, and preserves the existing non-MFA cached-token workflow.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "deployers" / "Initialize-EntraApplication.ps1"
CONFIG_PATH = REPO_ROOT / "application" / "single_app" / "config.py"
FIX_DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "explanation"
    / "fixes"
    / "v0.241.010"
    / "ENTRA_APPLICATION_GRAPH_MFA_AUTH_FIX.md"
)


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def require_not_contains(content: str, unexpected: str, description: str) -> None:
    if unexpected in content:
        raise AssertionError(f"Unexpected {description}: {unexpected}")


def test_entra_application_graph_mfa_auth_flow() -> bool:
    print("Testing Entra application Microsoft Graph MFA authentication handling")
    print("=" * 80)

    script_content = SCRIPT_PATH.read_text(encoding="utf-8")
    config_content = CONFIG_PATH.read_text(encoding="utf-8")
    fix_doc_content = FIX_DOC_PATH.read_text(encoding="utf-8")

    require_contains(
        script_content,
        "function Test-AzureCliInteractionRequiredMessage",
        "interaction-required detector",
    )
    require_contains(script_content, "AADSTS50076", "MFA challenge detection")
    require_contains(script_content, "invalid_grant", "invalid grant detection")
    require_contains(
        script_content,
        "function Ensure-AzureCliGraphAuthenticated",
        "Microsoft Graph Azure CLI preflight helper",
    )
    require_contains(
        script_content,
        "az account get-access-token `\n        --tenant $TenantId `\n        --resource $GraphResource",
        "non-interactive Graph token preflight",
    )
    require_contains(
        script_content,
        "az login --tenant $TenantId --scope $GraphScope",
        "interactive Graph-scoped login recovery",
    )
    require_contains(
        script_content,
        "Ensure-AzureCliGraphAuthenticated -TenantId $tenantId -GraphUrl $graphUrl",
        "preflight invocation before Graph app operations",
    )
    require_contains(
        script_content,
        "function Invoke-AzureCliJson",
        "checked Azure CLI JSON wrapper",
    )
    require_contains(
        script_content,
        "Check app registration '$appRegistrationName'",
        "checked app registration lookup",
    )
    require_not_contains(
        script_content,
        "az ad app list --display-name $appRegistrationName --output json | ConvertFrom-Json",
        "unchecked app registration lookup pipeline",
    )

    require_contains(config_content, 'VERSION = "0.241.018"', "config version bump")
    require_contains(
        fix_doc_content,
        "Fixed/Implemented in version: **0.241.010**",
        "versioned fix documentation",
    )

    print("Graph token preflight is present")
    print("Interactive MFA recovery uses a Graph-scoped Azure CLI login")
    print("Existing non-MFA cached-token runs can continue without re-login")
    print("App registration lookup no longer treats Azure CLI errors as empty JSON")
    return True


if __name__ == "__main__":
    try:
        success = test_entra_application_graph_mfa_auth_flow()
    except Exception as exc:
        print(f"Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)