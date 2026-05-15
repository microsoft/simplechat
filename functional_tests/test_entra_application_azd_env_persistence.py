# test_entra_application_azd_env_persistence.py
#!/usr/bin/env python3
"""
Functional test for Entra application azd environment persistence.
Version: 0.241.018
Implemented in: 0.241.011

This test ensures that Initialize-EntraApplication.ps1 can persist app
registration values into the active azd environment so azd up does not prompt
for values that were already created by the registration workflow.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "deployers" / "Initialize-EntraApplication.ps1"
PARAMETERS_PATH = REPO_ROOT / "deployers" / "bicep" / "main.parameters.json"
CONFIG_PATH = REPO_ROOT / "application" / "single_app" / "config.py"
FIX_DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "explanation"
    / "fixes"
    / "v0.241.011"
    / "ENTRA_APPLICATION_AZD_ENV_PERSISTENCE_FIX.md"
)


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_entra_application_azd_env_persistence() -> bool:
    print("Testing Entra application azd environment persistence")
    print("=" * 70)

    script_content = SCRIPT_PATH.read_text(encoding="utf-8")
    parameters_content = PARAMETERS_PATH.read_text(encoding="utf-8")
    config_content = CONFIG_PATH.read_text(encoding="utf-8")
    fix_doc_content = FIX_DOC_PATH.read_text(encoding="utf-8")

    require_contains(script_content, "[string]$AzdEnvironmentName", "azd environment override parameter")
    require_contains(script_content, "[switch]$SkipAzdEnvironmentUpdate", "azd persistence skip switch")
    require_contains(script_content, "function Resolve-AzdEnvironmentName", "azd environment resolver")
    require_contains(script_content, "AZURE_ENV_NAME", "AZURE_ENV_NAME environment fallback")
    require_contains(script_content, ".azure\\config.json", "azd default environment fallback")
    require_contains(script_content, "function Save-EntraRegistrationToAzdEnvironment", "azd persistence helper")
    require_contains(script_content, "azd env set --environment $EnvironmentName", "azd env set command")
    require_contains(script_content, "ENTERPRISE_APP_CLIENT_ID", "client id azd variable")
    require_contains(script_content, "ENTERPRISE_APP_SERVICE_PRINCIPAL_ID", "service principal id azd variable")
    require_contains(script_content, "ENTERPRISE_APP_CLIENT_SECRET", "client secret azd variable")
    require_contains(script_content, "Saving app registration values to azd environment", "save progress message")

    require_contains(parameters_content, '"value": "${ENTERPRISE_APP_CLIENT_ID}"', "client id parameter mapping")
    require_contains(
        parameters_content,
        '"value": "${ENTERPRISE_APP_SERVICE_PRINCIPAL_ID}"',
        "service principal parameter mapping",
    )
    require_contains(
        parameters_content,
        '"value": "${ENTERPRISE_APP_CLIENT_SECRET}"',
        "client secret parameter mapping",
    )
    require_contains(config_content, 'VERSION = "0.241.018"', "config version bump")
    require_contains(
        fix_doc_content,
        "Fixed/Implemented in version: **0.241.011**",
        "versioned fix documentation",
    )

    print("azd environment override and skip controls are present")
    print("Entra outputs are saved using azd env set")
    print("Bicep parameters already consume the saved azd values")
    return True


if __name__ == "__main__":
    try:
        success = test_entra_application_azd_env_persistence()
    except Exception as exc:
        print(f"Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)