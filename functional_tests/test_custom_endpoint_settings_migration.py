# test_custom_endpoint_settings_migration.py
"""
Functional test for custom endpoint settings migration.
Version: 0.236.058
Implemented in: 0.236.058

This test ensures legacy custom endpoint settings are migrated to the new
workspace-scoped flags and kept in sync.
"""

import os
import sys

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(repo_root)

from application.single_app.functions_settings import apply_custom_endpoint_setting_migration


def test_custom_endpoint_settings_migration_from_legacy():
    """Ensure legacy custom endpoint flags migrate to new settings."""
    print("🔍 Validating custom endpoint settings migration...")

    settings = {
        "allow_user_custom_agent_endpoints": True,
        "allow_group_custom_agent_endpoints": False
    }

    updated = apply_custom_endpoint_setting_migration(settings)

    assert updated is True
    assert settings["allow_user_custom_endpoints"] is True
    assert settings["allow_group_custom_endpoints"] is False
    assert settings["allow_user_custom_agent_endpoints"] is True
    assert settings["allow_group_custom_agent_endpoints"] is False

    print("✅ Custom endpoint settings migration passed.")


def test_custom_endpoint_settings_migration_syncs_legacy():
    """Ensure legacy flags stay in sync with new settings."""
    print("🔍 Validating legacy flag sync for custom endpoints...")

    settings = {
        "allow_user_custom_endpoints": False,
        "allow_group_custom_endpoints": True,
        "allow_user_custom_agent_endpoints": True,
        "allow_group_custom_agent_endpoints": False
    }

    updated = apply_custom_endpoint_setting_migration(settings)

    assert updated is True
    assert settings["allow_user_custom_agent_endpoints"] is False
    assert settings["allow_group_custom_agent_endpoints"] is True

    print("✅ Legacy flag sync passed.")


def run_tests():
    tests = [
        test_custom_endpoint_settings_migration_from_legacy,
        test_custom_endpoint_settings_migration_syncs_legacy
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
