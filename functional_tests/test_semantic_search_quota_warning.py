#!/usr/bin/env python3
# test_semantic_search_quota_warning.py
"""
Functional test for Semantic Ranker quota warning surfacing.
Version: 0.241.086
Implemented in: 0.241.086

This test ensures Azure AI Search Semantic Ranker free quota exhaustion is
recorded as service health, returned as a user-visible chat warning, and shown
on workspace and admin pages instead of silently continuing with no augmentation.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"


def read_workspace_file(relative_path: str) -> str:
    """Read a workspace file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(content: str, expected: str, description: str) -> None:
    """Assert that expected text exists in content with a useful message."""
    assert expected in content, f"Expected {description}: {expected}"


def test_semantic_search_quota_warning() -> bool:
    """Validate semantic quota warning detection, persistence, and rendering hooks."""
    print("Testing semantic search quota warning surfacing")
    print("=" * 70)

    config_content = read_workspace_file("application/single_app/config.py")
    service_health_content = read_workspace_file("application/single_app/functions_service_health.py")
    settings_content = read_workspace_file("application/single_app/functions_settings.py")
    search_content = read_workspace_file("application/single_app/functions_search.py")
    chat_route_content = read_workspace_file("application/single_app/route_backend_chats.py")
    warning_partial = read_workspace_file("application/single_app/templates/_semantic_search_health_warning.html")

    assert_contains(config_content, 'VERSION = "0.241.086"', "current version bump")
    assert_contains(settings_content, "'service_health': get_default_service_health()", "default service-health settings")

    helper_expectations = [
        "SEMANTIC_SEARCH_QUOTA_WARNING_TYPE = \"semantic_search_quota_exceeded\"",
        "Free Query Semantic Usage exceeded for the month.",
        "def is_semantic_search_quota_error(error):",
        "def record_semantic_search_quota_exceeded(error=None, source=\"hybrid_search\"):",
        "def clear_semantic_search_quota_warning(source=\"hybrid_search\"):",
        "class SemanticSearchQuotaExceededError(RuntimeError):",
    ]
    for expected in helper_expectations:
        assert_contains(service_health_content, expected, "service-health helper behavior")

    search_expectations = [
        "is_semantic_search_quota_error(search_error)",
        "record_semantic_search_quota_exceeded(search_error, source=\"hybrid_search\")",
        "raise SemanticSearchQuotaExceededError() from search_error",
        "clear_semantic_search_quota_warning(source=\"hybrid_search\")",
    ]
    for expected in search_expectations:
        assert_contains(search_content, expected, "hybrid search semantic quota handling")

    chat_expectations = [
        "except SemanticSearchQuotaExceededError as e:",
        "SEMANTIC_SEARCH_QUOTA_WARNING_TYPE",
        "service_health_warning",
        "}), 503",
        "yield emit_thought(",
        "return\n                    except Exception as e:",
    ]
    for expected in chat_expectations:
        assert_contains(chat_route_content, expected, "chat route semantic quota warning response")

    template_expectations = [
        "id=\"semantic-search-health-warning\"",
        "data-testid=\"semantic-search-health-warning\"",
        "role=\"alert\"",
        "Workspace search warning",
        "semantic_search_health.get('status') == 'quota_exceeded'",
    ]
    for expected in template_expectations:
        assert_contains(warning_partial, expected, "semantic warning partial")

    pages_with_warning = [
        "application/single_app/templates/workspace.html",
        "application/single_app/templates/group_workspaces.html",
        "application/single_app/templates/public_workspaces.html",
        "application/single_app/templates/manage_public_workspace.html",
        "application/single_app/templates/admin_settings.html",
        "application/single_app/templates/control_center.html",
    ]
    for page_path in pages_with_warning:
        page_content = read_workspace_file(page_path)
        assert_contains(page_content, '{% include "_semantic_search_health_warning.html" %}', f"warning include in {page_path}")

    assert "|safe" not in warning_partial, "Warning partial must rely on Jinja escaping, not |safe."

    print("Semantic quota warnings are detected, stored, returned to chat, and rendered on workspace/admin pages.")
    return True


if __name__ == "__main__":
    try:
        success = test_semantic_search_quota_warning()
    except Exception as ex:
        print(f"Test failed: {ex}")
        raise

    sys.exit(0 if success else 1)
