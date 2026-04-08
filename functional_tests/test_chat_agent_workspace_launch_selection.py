# test_chat_agent_workspace_launch_selection.py
#!/usr/bin/env python3
"""
Functional test for workspace agent chat launch selection.
Version: 0.240.075
Implemented in: 0.240.075

This test ensures that launching chat from workspace or group agent views keeps
the selected agent active by explicitly enabling agent mode before redirecting
to the chat page.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def test_workspace_agent_chat_launch_enables_agent_mode():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    backend_path = os.path.join(
        repo_root, "application", "single_app", "route_backend_agents.py"
    )
    workspace_agents_path = os.path.join(
        repo_root, "application", "single_app", "static", "js", "workspace", "workspace_agents.js"
    )
    group_agents_path = os.path.join(
        repo_root, "application", "single_app", "static", "js", "workspace", "group_agents.js"
    )
    config_path = os.path.join(
        repo_root, "application", "single_app", "config.py"
    )

    backend_content = read_file_text(backend_path)
    workspace_agents_content = read_file_text(workspace_agents_path)
    group_agents_content = read_file_text(group_agents_path)
    config_content = read_file_text(config_path)

    assert "settings_to_update['selected_agent'] = agent" in backend_content, (
        "Expected the selected-agent API to persist the chosen agent before redirecting to chat."
    )
    assert "settings_to_update['enable_agents'] = True" in backend_content, (
        "Expected the selected-agent API to enable agent mode so chat opens with the chosen agent active."
    )
    assert "id: agent.id || null" in workspace_agents_content, (
        "Expected personal workspace chat launches to include the canonical agent ID in the selection payload."
    )
    assert "display_name: agent.display_name || agent.displayName || agentName" in workspace_agents_content, (
        "Expected personal workspace chat launches to send the display name used by chat selection UI."
    )
    assert "is_group: false" in workspace_agents_content, (
        "Expected personal workspace launches to explicitly preserve personal-agent scope."
    )
    assert "id: agent.id || null" in group_agents_content, (
        "Expected group workspace chat launches to include the canonical group agent ID in the selection payload."
    )
    assert "group_id: currentContext.activeGroupId" in group_agents_content, (
        "Expected group workspace launches to preserve the originating group scope when redirecting to chat."
    )
    assert 'VERSION = "0.240.075"' in config_content, (
        "Expected config.py version 0.240.075 for the workspace agent chat launch selection fix."
    )

    print("✅ Workspace and group agent chat launch selection wiring verified.")


def run_tests():
    tests = [test_workspace_agent_chat_launch_enables_agent_mode]
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
    raise SystemExit(0 if run_tests() else 1)