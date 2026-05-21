# test_deep_research_explicit_toggle.py
#!/usr/bin/env python3
"""
Functional test for explicit Deep Research activation.
Version: 0.241.082
Implemented in: 0.241.079
Updated in: 0.241.081; 0.241.082

This test ensures that Web Search alone does not auto-enable Deep Research or
Source Review. Deep Research should run only when the user explicitly selects it.
"""

import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
ROUTE_BACKEND_CHATS = os.path.join(APP_ROOT, "route_backend_chats.py")
ADMIN_TEMPLATE = os.path.join(APP_ROOT, "templates", "admin_settings.html")

sys.path.insert(0, APP_ROOT)

from functions_source_review import get_source_review_config, should_auto_enable_source_review  # noqa: E402


def read_text(path):
    """Read text content for static regression checks."""
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def test_web_search_does_not_auto_enable_deep_research():
    """Web Search should not trigger Deep Research unless explicitly selected."""
    print("Testing Web Search does not auto-enable Deep Research...")

    source_settings = get_source_review_config({})
    assert source_settings["source_review_default_mode"] == "manual"

    stale_auto_settings = {
        "enable_source_review": True,
        "source_review_default_mode": "auto_with_web_search",
    }
    normalized_auto_settings = get_source_review_config(stale_auto_settings)
    assert normalized_auto_settings["source_review_default_mode"] == "manual"

    should_enable = should_auto_enable_source_review(
        stale_auto_settings,
        user_id="test-user",
        user_message="who won the superbowl",
        web_search_enabled=True,
    )
    assert should_enable is False

    print("Web Search does not auto-enable Deep Research.")
    return True


def test_chat_backend_uses_explicit_deep_research_toggle():
    """Chat routes should not call the deprecated auto-enable helper."""
    print("Testing chat backend explicit Deep Research toggle handling...")
    route_source = read_text(ROUTE_BACKEND_CHATS)

    assert "should_auto_enable_source_review" not in route_source
    assert "deep_research_requested = bool(source_review_enabled) or bool(deep_research_enabled)" in route_source
    assert "deep_research_enabled = source_review_allowed_for_user and deep_research_requested" in route_source
    assert "source_review_enabled = bool(deep_research_enabled or url_access_enabled)" in route_source

    print("Chat backend explicit toggle handling verified.")
    return True


def test_admin_settings_describes_manual_activation():
    """Admin Settings should not advertise automatic Deep Research activation modes."""
    print("Testing Admin Settings Deep Research activation copy...")
    template_source = read_text(ADMIN_TEMPLATE)

    assert 'name="source_review_default_mode" value="manual"' in template_source
    assert "Deep Research runs only when the user selects it for the message." in template_source
    assert "Auto with URLs or web search" not in template_source
    assert "Auto when message has URLs" not in template_source

    print("Admin Settings manual activation copy verified.")
    return True


def main():
    """Run all regression checks."""
    tests = [
        test_web_search_does_not_auto_enable_deep_research,
        test_chat_backend_uses_explicit_deep_research_toggle,
        test_admin_settings_describes_manual_activation,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())