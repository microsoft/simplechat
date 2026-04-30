# test_azd_private_dns_zone_config_wiring.py
#!/usr/bin/env python3
"""
Functional test for AZD private DNS zone config wiring.
Version: 0.240.006
Implemented in: 0.240.006

This test ensures that AZD deployments can pass private DNS zone reuse settings
through the PRIVATE_DNS_ZONE_CONFIGS environment value instead of silently
forcing privateDnsZoneConfigs to an empty object.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "application" / "single_app" / "config.py"
PARAMETERS_PATH = REPO_ROOT / "deployers" / "bicep" / "main.parameters.json"
PREREQUISITES_PATH = REPO_ROOT / "deployers" / "bicep" / "validate_azd_prerequisites.py"
README_PATH = REPO_ROOT / "deployers" / "bicep" / "README.md"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_azd_private_dns_zone_configs_are_wired() -> bool:
    print("🧪 Testing AZD private DNS zone config parameter wiring")
    print("=" * 70)

    parameters_content = PARAMETERS_PATH.read_text(encoding="utf-8")
    prerequisites_content = PREREQUISITES_PATH.read_text(encoding="utf-8")
    readme_content = README_PATH.read_text(encoding="utf-8")
    config_content = CONFIG_PATH.read_text(encoding="utf-8")

    require_contains(
        parameters_content,
        '"value": "${PRIVATE_DNS_ZONE_CONFIGS}"',
        "AZD parameter pass-through for privateDnsZoneConfigs",
    )
    require_contains(
        prerequisites_content,
        "AZURE_ENV_PRIVATE_DNS_ZONE_CONFIGS",
        "preprovision AZD environment variable lookup",
    )
    require_contains(
        prerequisites_content,
        "PRIVATE_DNS_ZONE_CONFIGS",
        "preprovision local environment variable lookup",
    )
    require_contains(
        readme_content,
        "PRIVATE_DNS_ZONE_CONFIGS",
        "README guidance for AZD private DNS zone configuration",
    )
    require_contains(
        config_content,
        'VERSION = "0.240.006"',
        "config version bump",
    )

    print("✅ AZD parameters file passes PRIVATE_DNS_ZONE_CONFIGS into Bicep")
    print("✅ Preprovision validation reads PRIVATE_DNS_ZONE_CONFIGS before deployment")
    print("✅ README documents the AZD environment variable path")
    print("✅ Config version was updated for the fix")
    return True


if __name__ == "__main__":
    try:
        success = test_azd_private_dns_zone_configs_are_wired()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)