# test_new_foundry_version_metadata.py
#!/usr/bin/env python3
"""
Functional test for New Foundry version metadata handling.
Version: 0.239.180
Implemented in: 0.239.180

This test ensures that published New Foundry application versions are read from
the fetched payload, shown in the selector label, and no longer require manual
entry in the agent modal.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def assert_not_contains(file_path: Path, forbidden: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if forbidden in content:
        raise AssertionError(f"Did not expect to find {forbidden!r} in {file_path}")


def test_new_foundry_version_metadata() -> None:
    print("Testing New Foundry version metadata handling...")

    runtime_path = ROOT / "application" / "single_app" / "foundry_agent_runtime.py"
    modal_js_path = ROOT / "application" / "single_app" / "static" / "js" / "agent_modal_stepper.js"
    modal_html_path = ROOT / "application" / "single_app" / "templates" / "_agent_modal.html"
    config_path = ROOT / "application" / "single_app" / "config.py"

    assert_contains(runtime_path, '_extract_nested_version_value(item.get("versions"))')
    assert_contains(runtime_path, '_extract_nested_version_value(properties.get("versions"))')
    assert_contains(modal_js_path, 'const versionSuffix = agent.application_version ? ` (v${agent.application_version})` : \'\';')
    assert_contains(modal_html_path, 'id="agent-new-foundry-application-version"')
    assert_contains(modal_html_path, 'type="hidden" id="agent-new-foundry-application-version"')
    assert_not_contains(modal_html_path, '<label for="agent-new-foundry-application-version" class="form-label">Version</label>')
    assert_contains(config_path, 'VERSION = "0.239.180"')

    print("✅ New Foundry version metadata handling verified.")


if __name__ == "__main__":
    success = True
    try:
        test_new_foundry_version_metadata()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        success = False

    raise SystemExit(0 if success else 1)