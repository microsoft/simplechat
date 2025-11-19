#!/usr/bin/env python3
# test_group_agent_conversation_metadata_fix.py
"""
Functional test for group agent conversation metadata fix.
Version: 0.233.161
Implemented in: 0.233.161

This test ensures that conversations using group agents receive the correct
primary context and chat type metadata even when no documents are retrieved.
"""

import sys
import os
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def test_group_agent_primary_context():
    """Validate that group agents promote group context metadata."""
    print("🔍 Testing group agent conversation metadata context...")

    try:
        from functions_conversation_metadata import collect_conversation_metadata

        conversation_item = {
            "context": [],
            "tags": [],
            "strict": False
        }

        agent_details = {
            "is_group": True,
            "group_id": "group-456",
            "group_name": "TestGroup"
        }

        with patch("functions_conversation_metadata.get_current_user_info", return_value={
            "userId": "user-123",
            "displayName": "Test User",
            "email": "user@test.com"
        }), patch("functions_conversation_metadata.find_group_by_id", return_value={
            "id": "group-456",
            "name": "TestGroup"
        }):
            updated = collect_conversation_metadata(
                user_message="Test message",
                conversation_id="conversation-123",
                user_id="user-123",
                selected_agent="GroupAgent",
                selected_agent_details=agent_details,
                conversation_item=conversation_item
            )

        contexts = updated.get("context", [])
        primary_context = next((ctx for ctx in contexts if ctx.get("type") == "primary"), None)

        if not primary_context:
            print("❌ No primary context found after group agent metadata update")
            return False

        if primary_context.get("scope") != "group" or primary_context.get("id") != "group-456":
            print("❌ Primary context does not reference the expected group")
            return False

        if updated.get("chat_type") != "group-single-user":
            print("❌ Chat type was not updated to group-single-user")
            return False

        agent_tags = [tag for tag in updated.get("tags", []) if tag.get("category") == "agent"]
        if not agent_tags:
            print("❌ Agent tag missing from conversation metadata")
            return False

        print("✅ Group agent metadata correctly updates conversation context and chat type")
        return True

    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🧪 Testing Group Agent Conversation Metadata Fix...")
    print("=" * 70)

    tests = [
        test_group_agent_primary_context
    ]

    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(tests)} tests passed")

    if success:
        print("✅ All group agent metadata tests passed!")
    else:
        print("❌ Some tests failed. Please review the group agent metadata changes.")

    sys.exit(0 if success else 1)
