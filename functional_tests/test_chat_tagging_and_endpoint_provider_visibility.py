# test_chat_tagging_and_endpoint_provider_visibility.py
#!/usr/bin/env python3
"""
Functional test for chat tagging and endpoint provider visibility.
Version: 0.239.167
Implemented in: 0.239.167

This test ensures unsupported New Foundry endpoints remain hidden from user-
facing endpoint payloads, streaming group-agent conversations preserve group
metadata, personal conversations no longer render visible tags, the active
conversation header shows the full group name, and the sidebar shows the first
8 characters of the group name.
"""

import os
import sys


sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _read_text(relative_path):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(repo_root, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


def test_endpoint_provider_visibility_guard():
    """Verify only supported endpoint providers are exposed to frontend flows."""
    print("🔍 Testing endpoint provider visibility guard...")

    try:
        settings_text = _read_text("application/single_app/functions_settings.py")

        required_snippets = [
            "def is_frontend_visible_model_endpoint_provider(provider):",
            'return normalized_provider in {"aoai", "aifoundry"}',
            'if not is_frontend_visible_model_endpoint_provider(endpoint.get("provider")):',
            'if is_frontend_visible_model_endpoint_provider(endpoint.get("provider")):',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in settings_text]
        if missing:
            print(f"❌ Missing endpoint visibility snippets: {', '.join(missing)}")
            return False

        print("✅ Frontend endpoint provider filtering is wired")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_group_agent_tagging_and_personal_badge_removal():
    """Verify group-agent metadata survives streaming and UI tags render correctly."""
    print("🔍 Testing group-agent tagging and personal badge removal...")

    try:
        chat_conversations_text = _read_text("application/single_app/static/js/chat/chat-conversations.js")
        chat_details_text = _read_text("application/single_app/static/js/chat/chat-conversation-details.js")
        chat_sidebar_text = _read_text("application/single_app/static/js/chat/chat-sidebar-conversations.js")
        chat_backend_text = _read_text("application/single_app/route_backend_chats.py")

        required_snippets = [
            'selected_agent=agent_name_used if use_agent_streaming else None',
            'selected_agent_details=selected_agent_metadata if use_agent_streaming else None',
            'return normalizedName.slice(0, 8);',
            "groupBadge.textContent = (groupName || 'group').trim() || 'group';",
            "badge.textContent = getShortGroupLabel(groupName);",
            'return `<span class="badge bg-info" title="${escapeHtml(groupName)}">${escapeHtml(groupName)}</span>`;',
            "return '<span class=\"text-muted\">personal</span>';",
        ]
        missing = [
            snippet
            for snippet in required_snippets
            if snippet not in f"{chat_conversations_text}\n{chat_details_text}\n{chat_sidebar_text}\n{chat_backend_text}"
        ]
        if missing:
            print(f"❌ Missing tagging snippets: {', '.join(missing)}")
            return False

        if 'badge.textContent = \'personal\'' in chat_sidebar_text:
            print("❌ Personal conversations still render a visible personal badge in the sidebar")
            return False

        print("✅ Group-agent metadata and conversation tag rendering are wired correctly")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_endpoint_provider_visibility_guard,
        test_group_agent_tagging_and_personal_badge_removal,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(tests)} tests passed")
    sys.exit(0 if success else 1)