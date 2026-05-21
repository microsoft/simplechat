# test_deployer_background_tasks_app_setting.py
#!/usr/bin/env python3
"""
Functional test for SimpleChat background task deployment settings.
Version: 0.241.069
Implemented in: 0.241.057
Updated in: 0.241.069

This test ensures deployment paths configure SIMPLECHAT_RUN_BACKGROUND_TASKS=1
so queued background schedulers run in deployed containers.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_SERVICE_BICEP = REPO_ROOT / "deployers" / "bicep" / "modules" / "appService.bicep"
MAIN_JSON = REPO_ROOT / "deployers" / "bicep" / "main.json"
AZURE_YAML = REPO_ROOT / "deployers" / "azure.yaml"
AZURE_CLI_DEPLOY = REPO_ROOT / "deployers" / "azurecli" / "deploy-simplechat.ps1"
DEPLOYER_VERSION = REPO_ROOT / "deployers" / "version.txt"


def read_text(path):
    """Read a workspace file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def assert_contains(source_text, expected_text, description):
    """Assert that expected deployment wiring is present."""
    if expected_text not in source_text:
        raise AssertionError(f"Missing {description}: {expected_text}")


def test_bicep_app_service_enables_background_tasks():
    """Validate azd provision/up App Service settings enable scheduler loops."""
    source_text = read_text(APP_SERVICE_BICEP)
    assert_contains(
        source_text,
        "{ name: 'SIMPLECHAT_RUN_BACKGROUND_TASKS', value: '1' }",
        "Bicep App Service background task app setting",
    )


def test_shipped_arm_template_enables_background_tasks():
    """Validate the one-click ARM template includes the app setting."""
    source_text = read_text(MAIN_JSON)
    assert_contains(
        source_text,
        "createObject('name', 'SIMPLECHAT_RUN_BACKGROUND_TASKS', 'value', '1')",
        "ARM template background task app setting",
    )


def test_azd_deploy_hook_enables_background_tasks():
    """Validate azd deploy reinforces the setting before app restart."""
    source_text = read_text(AZURE_YAML)
    assert_contains(
        source_text,
        "--settings SIMPLECHAT_RUN_BACKGROUND_TASKS=1",
        "azd deploy background task app setting command",
    )
    assert_contains(source_text, "SimpleChat background tasks enabled", "azd deploy confirmation output")


def test_azurecli_deploy_enables_background_tasks():
    """Validate the legacy Azure CLI deploy script configures the setting."""
    source_text = read_text(AZURE_CLI_DEPLOY)
    assert_contains(
        source_text,
        '"SIMPLECHAT_RUN_BACKGROUND_TASKS=1"',
        "Azure CLI deploy background task app setting",
    )


def test_deployer_version_bumped():
    """Validate deployer version tracking was updated for this deployer change."""
    deployer_version = read_text(DEPLOYER_VERSION).strip()
    if deployer_version != "1.0.4":
        raise AssertionError(f"Expected deployer version 1.0.4, found {deployer_version}")


def main():
    """Run all deployment setting checks."""
    tests = [
        test_bicep_app_service_enables_background_tasks,
        test_shipped_arm_template_enables_background_tasks,
        test_azd_deploy_hook_enables_background_tasks,
        test_azurecli_deploy_enables_background_tasks,
        test_deployer_version_bumped,
    ]
    results = []

    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)