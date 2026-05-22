# test_url_access_admin_policy_test.py
#!/usr/bin/env python3
"""
Functional test for URL Access admin policy testing.
Version: 0.241.094
Implemented in: 0.241.094

This test ensures the Admin Settings URL Access policy tester evaluates unsaved
allowed and blocked domain rules, reports blocked URLs as successful policy
evaluations, and rejects malformed or disabled test requests clearly.
"""

import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_url_access_policy_test.py"


def load_module_with_stubs():
    """Load functions_url_access_policy_test.py with a lightweight App Insights stub."""
    appinsights_stub = types.ModuleType("functions_appinsights")
    appinsights_stub.log_event = lambda *args, **kwargs: None
    appinsights_stub.debug_print = lambda *args, **kwargs: None
    appinsights_stub.is_debug_enabled = lambda *args, **kwargs: False

    original_modules = {
        name: sys.modules.get(name)
        for name in [
            "functions_appinsights",
            "functions_debug",
            "functions_source_review",
        ]
    }
    original_path = list(sys.path)
    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))
    sys.modules["functions_appinsights"] = appinsights_stub

    try:
        spec = importlib.util.spec_from_file_location(
            "functions_url_access_policy_test_under_test",
            MODULE_PATH,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original_module
        sys.path = original_path


def test_blocked_domain_is_successful_policy_evaluation():
    """Validate blocked domains return a 200 evaluation with allowed=false."""
    print("Testing blocked URL Access domain policy result...")
    module = load_module_with_stubs()

    response, status_code = module.run_url_access_policy_test(
        {
            "enabled": True,
            "url": "https://blocked.example.com/page",
            "url_access_allowed_domains": "",
            "url_access_blocked_domains": "example.com",
        },
        global_settings={},
    )

    assert status_code == 200
    assert response["success"] is True
    assert response["allowed"] is False
    assert response["status"] == "domain_blocked"
    assert response["domain_policy"]["blocked_domains"] == ["example.com"]
    assert "blocked list" in response["message"]
    print("Blocked domain checks passed")


def test_allow_list_blocks_unlisted_domain():
    """Validate allow lists block domains that do not match."""
    print("Testing URL Access allow-list policy result...")
    module = load_module_with_stubs()

    response, status_code = module.run_url_access_policy_test(
        {
            "enabled": True,
            "url": "https://example.com/page",
            "url_access_allowed_domains": "contoso.com",
            "url_access_blocked_domains": "",
        },
        global_settings={},
    )

    assert status_code == 200
    assert response["success"] is True
    assert response["allowed"] is False
    assert response["status"] == "domain_not_allowed"
    assert response["domain_policy"]["allowed_domains"] == ["contoso.com"]
    assert any("Allowed Domains" in detail for detail in response["details"])
    print("Allow-list checks passed")


def test_unsaved_blank_allow_list_overrides_saved_settings():
    """Validate blank unsaved form fields override saved allow lists for tests."""
    print("Testing unsaved URL Access policy overrides...")
    module = load_module_with_stubs()

    response, status_code = module.run_url_access_policy_test(
        {
            "enabled": True,
            "url": "https://blocked.example.com/page",
            "url_access_allowed_domains": "",
            "url_access_blocked_domains": "example.com",
        },
        global_settings={
            "url_access_allowed_domains": ["contoso.com"],
            "source_review_allowed_domains": ["contoso.com"],
        },
    )

    assert status_code == 200
    assert response["domain_policy"]["allowed_domains"] == []
    assert response["domain_policy"]["blocked_domains"] == ["example.com"]
    print("Unsaved override checks passed")


def test_invalid_url_returns_actionable_error():
    """Validate unsupported URL schemes return a clear 400 response."""
    print("Testing invalid URL policy result...")
    module = load_module_with_stubs()

    response, status_code = module.run_url_access_policy_test(
        {
            "enabled": True,
            "url": "ftp://example.com/file.txt",
            "url_access_allowed_domains": "",
            "url_access_blocked_domains": "",
        },
        global_settings={},
    )

    assert status_code == 400
    assert response["success"] is False
    assert response["allowed"] is False
    assert response["status"] == "unsupported_scheme"
    assert any("http:// or https://" in item for item in response["guidance"])
    print("Invalid URL checks passed")


def test_disabled_url_access_returns_configuration_error():
    """Validate disabled URL Access blocks test execution."""
    print("Testing disabled URL Access policy result...")
    module = load_module_with_stubs()

    response, status_code = module.run_url_access_policy_test(
        {
            "enabled": False,
            "url": "https://example.com/page",
        },
        global_settings={},
    )

    assert status_code == 400
    assert response["success"] is False
    assert response["status"] == "configuration_error"
    assert "disabled" in response["message"]
    print("Disabled policy checks passed")


def main():
    """Run all URL Access admin policy test checks."""
    tests = [
        test_blocked_domain_is_successful_policy_evaluation,
        test_allow_list_blocks_unlisted_domain,
        test_unsaved_blank_allow_list_overrides_saved_settings,
        test_invalid_url_returns_actionable_error,
        test_disabled_url_access_returns_configuration_error,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print(f"Test passed: {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())