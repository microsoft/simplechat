# test_new_foundry_ui_visibility.py
#!/usr/bin/env python3
"""
Functional test for New Foundry UI visibility.
Version: 0.239.180
Implemented in: 0.239.180

This test ensures that New Foundry is exposed again in the agent modal,
the endpoint modal, and frontend endpoint sanitization so the browser UI can
configure and select New Foundry resources.
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


def test_new_foundry_ui_visibility() -> None:
    print("Testing New Foundry UI visibility...")

    agent_modal = ROOT / "application" / "single_app" / "templates" / "_agent_modal.html"
    endpoint_modal = ROOT / "application" / "single_app" / "templates" / "_multiendpoint_modal.html"
    settings_file = ROOT / "application" / "single_app" / "functions_settings.py"
    config_file = ROOT / "application" / "single_app" / "config.py"

    assert_contains(agent_modal, 'id="agent-type-new-foundry"')
    assert_not_contains(agent_modal, '{% if false %}')

    assert_contains(endpoint_modal, '<option value="new_foundry">New Foundry</option>')
    assert_contains(settings_file, 'return normalized_provider in {"aoai", "aifoundry", "new_foundry"}')
    assert_contains(config_file, 'VERSION = "0.239.180"')

    print("✅ New Foundry UI visibility verified.")


if __name__ == "__main__":
    success = True
    try:
        test_new_foundry_ui_visibility()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        success = False

    raise SystemExit(0 if success else 1)