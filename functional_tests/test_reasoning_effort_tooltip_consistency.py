#!/usr/bin/env python3
# test_reasoning_effort_tooltip_consistency.py
"""
Functional test for reasoning effort tooltip consistency.
Version: 0.239.192
Implemented in: 0.239.192

This test ensures that reasoning effort hover text uses Bootstrap tooltips
instead of browser-native title tooltips so it matches the rest of the chat UI.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_REASONING_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-reasoning.js"
CHAT_TEMPLATE_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "chats.html"
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"


def test_reasoning_tooltips_use_bootstrap_instances() -> bool:
    """Verify the reasoning UI updates Bootstrap tooltip instances rather than raw titles."""
    print("🔍 Testing reasoning tooltip Bootstrap wiring...")

    try:
        content = CHAT_REASONING_FILE.read_text(encoding="utf-8")

        required_snippets = [
            "function setTooltipText(element, text, options = {}) {",
            "const tooltip = bootstrap.Tooltip.getOrCreateInstance(element, options);",
            "element.removeAttribute('title');",
            "setTooltipText(reasoningToggleBtn, labelMap[level] || 'Configure reasoning effort');",
            "setTooltipText(levelDiv, levelDescriptions[level], { placement: 'right' });",
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f"Missing Bootstrap tooltip handling: {missing}"
        assert "reasoningToggleBtn.title =" not in content, "Expected reasoning button to avoid raw title updates"
        assert "levelDiv.title = levelDescriptions[level];" not in content, "Expected reasoning levels to avoid raw title tooltips"

        print("✅ Reasoning tooltip Bootstrap wiring passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_reasoning_button_template_uses_bootstrap_title_attribute() -> bool:
    """Verify the reasoning button markup uses Bootstrap tooltip attributes."""
    print("🔍 Testing reasoning button tooltip markup...")

    try:
        content = CHAT_TEMPLATE_FILE.read_text(encoding="utf-8")

        assert 'id="reasoning-toggle-btn"' in content, "Expected reasoning button markup in chats.html"
        assert 'data-bs-toggle="tooltip"' in content, "Expected Bootstrap tooltip toggle attribute"
        assert 'data-bs-title="Configure reasoning effort"' in content, "Expected Bootstrap tooltip title attribute"

        print("✅ Reasoning button tooltip markup passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_config_version_bumped_for_reasoning_tooltip_fix() -> bool:
    """Verify config version was bumped for the reasoning tooltip style fix."""
    print("🔍 Testing config version bump...")

    try:
        content = CONFIG_FILE.read_text(encoding="utf-8")
        assert 'VERSION = "0.239.192"' in content, 'Expected config.py version 0.239.192'

        print("✅ Config version bump passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_reasoning_tooltips_use_bootstrap_instances,
        test_reasoning_button_template_uses_bootstrap_title_attribute,
        test_config_version_bumped_for_reasoning_tooltip_fix,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)