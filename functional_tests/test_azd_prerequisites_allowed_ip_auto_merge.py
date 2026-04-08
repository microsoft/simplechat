#!/usr/bin/env python3
# test_azd_prerequisites_allowed_ip_auto_merge.py
"""
Functional test for AZD prerequisite runner IP auto-merge.
Version: 0.237.056
Implemented in: 0.237.056

This test ensures the preprovision prerequisite script can add the deployment
runner public IP into the AZD environment before private-network firewall rules
are created and that it documents propagation delays for manual firewall edits.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PREREQUISITES = REPO_ROOT / "deployers" / "bicep" / "validate_azd_prerequisites.py"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_azd_prerequisites_auto_merges_runner_ip() -> bool:
    print("🧪 Testing AZD prerequisite runner IP auto-merge")
    print("=" * 70)

    content = PREREQUISITES.read_text(encoding="utf-8")

    require_contains(content, "azd', 'env', 'set', 'ALLOWED_IP_RANGES'", "AZD environment persistence")
    require_contains(content, "https://api.ipify.org", "deployment runner public IP lookup")
    require_contains(content, "Added deployment runner public IP", "auto-merge status message")
    require_contains(content, "allow up to 30 minutes", "manual firewall propagation guidance")
    require_contains(content, "ALLOWED_IP_RANGES", "allowed IP ranges environment variable handling")

    print("✅ Prerequisite script persists ALLOWED_IP_RANGES through azd env set")
    print("✅ Prerequisite script resolves the deployment runner public IP")
    print("✅ Prerequisite script reports the auto-merge behavior")
    print("✅ Prerequisite script warns about manual firewall propagation delay")
    return True


if __name__ == "__main__":
    try:
        success = test_azd_prerequisites_auto_merges_runner_ip()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)