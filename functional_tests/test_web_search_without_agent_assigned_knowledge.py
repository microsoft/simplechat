# test_web_search_without_agent_assigned_knowledge.py
#!/usr/bin/env python3
"""
Functional test for Web Search chat-agent isolation.
Version: 0.241.079
Implemented in: 0.241.073

This test ensures that Web Search can use its configured Azure AI Foundry agent
without causing an unselected chat request to fall into Semantic Kernel chat-agent
or Assigned Knowledge paths.
"""

import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_BACKEND_CHATS = os.path.join(
    REPO_ROOT,
    "application",
    "single_app",
    "route_backend_chats.py",
)


def read_route_source():
    """Read the chat backend source for static regression checks."""
    with open(ROUTE_BACKEND_CHATS, "r", encoding="utf-8") as source_file:
        return source_file.read()


def test_web_search_agent_is_not_chat_agent_fallback():
    """Verify unselected chat requests do not auto-select default or first agents."""
    print("Testing Web Search chat-agent isolation...")
    source = read_route_source()

    forbidden_snippets = [
        "agent_knowledge_binding",
        "selected_agent fallback to first agent",
        "selected_agent found by default_agent=True",
        "Using default agent:",
        "Using first agent:",
    ]
    for snippet in forbidden_snippets:
        assert snippet not in source, f"Unexpected chat-agent fallback or stale binding found: {snippet}"

    required_snippets = [
        "def _has_chat_agent_selection(agent_selection):",
        "force_enable_agents = _has_chat_agent_selection(request_agent_info)",
        "[SKChat] No chat agent selected for this request; proceeding in model-only mode",
        "[Streaming] No chat agent selected for this request; using model-only response path",
        "perform_research_web_searches(",
        "execute_foundry_agent(",
    ]
    for snippet in required_snippets:
        assert snippet in source, f"Expected Web Search chat-agent isolation snippet missing: {snippet}"

    print("Web Search chat-agent isolation verified.")
    return True


def main():
    """Run all regression checks."""
    tests = [test_web_search_agent_is_not_chat_agent_fallback]
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