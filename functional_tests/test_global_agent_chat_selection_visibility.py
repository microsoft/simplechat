# test_global_agent_chat_selection_visibility.py
"""
Functional test for global agent chat selection visibility.
Version: 0.241.122
Implemented in: 0.241.122

This test ensures global agents are exposed in chat when app agents are enabled
and chat does not silently fall back to a stored default agent when the request
does not explicitly select one.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(text, expected, label):
    if expected not in text:
        raise AssertionError(f"Missing expected {label}: {expected}")


def assert_not_contains(text, unexpected, label):
    if unexpected in text:
        raise AssertionError(f"Unexpected {label}: {unexpected}")


def test_global_agent_button_visible_when_agents_enabled():
    """Verify the chat agent button is not limited to workspace mode."""
    template = read_repo_file("application/single_app/templates/chats.html")
    button_index = template.index('<button id="enable-agents-btn"')
    button_condition = template[max(0, button_index - 140):button_index]

    assert_contains(
        button_condition,
        "{% if settings.enable_semantic_kernel %}",
        "global agent button condition",
    )
    assert_not_contains(
        button_condition,
        "per_user_semantic_kernel",
        "workspace-only agent button condition",
    )


def test_global_agents_preloaded_for_global_mode():
    """Verify global agents are included in the chat agent catalog outside workspace mode."""
    frontend_route = read_repo_file("application/single_app/route_frontend_chats.py")

    assert_contains(frontend_route, "include_global_agents = settings.get('enable_semantic_kernel', False)", "global agent preload flag")
    assert_contains(frontend_route, "not settings.get('per_user_semantic_kernel', False)", "global mode preload condition")
    assert_contains(frontend_route, "chat_agent_options.append(_serialize_chat_agent_option(agent, is_global=True))", "global agent serialization")


def test_chat_requires_explicit_agent_selection():
    """Verify chat no longer falls back to stored selected agents when no request agent is present."""
    backend_route = read_repo_file("application/single_app/route_backend_chats.py")

    assert_contains(
        backend_route,
        "No explicit request agent selected; proceeding in model-only mode",
        "model-only no-agent log",
    )
    assert_contains(
        backend_route,
        "if selected_agent and kernel:",
        "selected-agent-gated kernel fallback",
    )
    assert_contains(
        backend_route,
        "and agent_name_to_select and \"orchestrator\" in all_agents",
        "explicit-agent-gated orchestrator fallback",
    )

    forbidden_fallbacks = [
        "Global mode: selected_agent from global_selected_agent",
        "Per-user mode: selected_agent from user_settings",
        "selected_agent_info = settings.get('global_selected_agent')",
    ]
    for fallback_text in forbidden_fallbacks:
        assert_not_contains(backend_route, fallback_text, "silent agent fallback")


def run_tests():
    tests = [
        test_global_agent_button_visible_when_agents_enabled,
        test_global_agents_preloaded_for_global_mode,
        test_chat_requires_explicit_agent_selection,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"PASS: {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {test.__name__}: {exc}")
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)