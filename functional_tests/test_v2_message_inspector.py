#!/usr/bin/env python3
"""
Functional test for V2 per-message intelligence.
Version: 0.261.013
Implemented in: 0.261.013

The V2 chat page could not answer three questions about a response that the classic UI can:
what sources it cited, how it reasoned, and how it was produced. Reasoning was visible only
while it streamed and was lost once the message finished.

This adds an inspector below each message with Details, Sources and Reasoning, reached from
the hover action row rather than the overflow menu.

Two contracts here are easy to get wrong and are asserted against the route source:

1. `GET /api/message/<id>/metadata` answers with a DIFFERENT shape depending on the message's
   role: a user message returns its nested `metadata` alone, while every other role returns
   the whole document.
2. Reasoning steps are NOT stored on the message. They come from a separate endpoint and use
   different field names than the live stream frames.

This test ensures both are handled and that untrusted citation URLs cannot become links.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2_SRC = os.path.join(REPO_ROOT, "application", "v2_ui", "src")
APP = os.path.join(REPO_ROOT, "application", "single_app")


def read(*parts):
    with open(os.path.join(*parts), "r", encoding="utf-8") as handle:
        return handle.read()


def test_message_metadata_shape_is_role_dependent():
    """A user message returns bare metadata; other roles return the whole document."""
    print("Testing message metadata handling...")
    try:
        route = read(APP, "route_frontend_conversations.py")
        assert "/api/message/<message_id>/metadata" in route
        # The branch that makes the response shape differ.
        assert "if message_role == 'user':" in route, (
            "The route is expected to branch on role"
        )
        assert "return jsonify(metadata)" in route, (
            "A user message returns its nested metadata object alone"
        )

        details = read(V2_SRC, "lib", "messageDetails.ts")
        assert "isFullDocument" in details, (
            "The client must distinguish a whole document from a bare metadata object"
        )
        assert "innerMetadata" in details, (
            "The nested metadata must be found wherever it lives"
        )

        print("Message metadata shape test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_reasoning_is_fetched_not_read_from_the_message():
    """Thoughts are stored separately and must be requested per message."""
    print("Testing reasoning retrieval...")
    try:
        route = read(APP, "route_backend_thoughts.py")
        assert (
            "/api/conversations/<conversation_id>/messages/<message_id>/thoughts" in route
        ), "The persisted-thoughts endpoint is expected at this path"
        # The response distinguishes "none recorded" from "capture is off".
        assert "'thoughts': [], 'enabled': False" in route, (
            "The endpoint reports when thought capture is disabled"
        )
        for field in ("step_type", "detail", "activity", "duration_ms"):
            assert field in route, f"Expected {field} on a persisted thought"

        endpoints = read(V2_SRC, "lib", "endpoints.ts")
        assert "fetchMessageThoughts" in endpoints
        assert "/messages/${encodeURIComponent(messageId)}/thoughts" in endpoints, (
            "Reasoning must be fetched per message"
        )

        inspector = read(V2_SRC, "components", "chat", "MessageInspector.tsx")
        assert "enabled" in inspector, (
            "A deployment with reasoning capture off must say so, not show an empty list"
        )

        print("Reasoning retrieval test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_persisted_and_live_reasoning_render_identically():
    """Historical reasoning uses the same renderer as reasoning being generated."""
    print("Testing reasoning presentation...")
    try:
        shared = read(V2_SRC, "components", "chat", "ThoughtsList.tsx")
        assert "export function ThoughtsList" in shared, (
            "A single renderer should serve both cases"
        )
        assert "normalizePersistedThought" in shared, (
            "The stored shape must be mapped onto the streamed one"
        )
        # step_type is the stored equivalent of the live frame's title.
        assert "step_type" in shared

        message_list = read(V2_SRC, "components", "chat", "MessageList.tsx")
        inspector = read(V2_SRC, "components", "chat", "MessageInspector.tsx")
        assert "<ThoughtsList" in message_list, (
            "The streaming panel must use the shared renderer"
        )
        assert "<ThoughtsList" in inspector, (
            "The historical panel must use the same renderer, so the same information does "
            "not look like a different feature after the fact"
        )

        print("Reasoning presentation test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_sources_come_from_the_message_document():
    """Citations are on the message already and need no extra request."""
    print("Testing source reading...")
    try:
        classic = read(APP, "static", "js", "chat", "chat-messages.js")
        # Establish the field names rather than assuming them.
        assert "function createCitationsHtml" in classic
        for field in ("hybridCitations", "webCitations", "agentCitations"):
            assert field in classic, f"Expected {field} in the classic citation renderer"
        assert "cite.tool_name" in classic, "Tool calls are identified by tool_name"

        details = read(V2_SRC, "lib", "messageDetails.ts")
        for field in ("hybrid_citations", "web_search_citations", "agent_citations"):
            assert field in details, f"Expected {field} to be read from the message"

        print("Source reading test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_untrusted_citation_urls_cannot_become_links():
    """A citation URL is attacker-influenced and must be scheme-checked."""
    print("Testing citation URL safety...")
    try:
        inspector = read(V2_SRC, "components", "chat", "MessageInspector.tsx")
        # xss-check: ignore - this is assertion prose in a test that verifies the scheme
        # allowlist exists. No URL is constructed or rendered here.
        assert "/^https?:\\/\\//i.test(url)" in inspector, (
            "Only http(s) may become a live link; other schemes must not"
        )
        assert 'rel="noopener noreferrer"' in inspector, (
            "An outbound link must not hand the opener to the target page"
        )
        assert 'target="_blank"' in inspector

        print("Citation URL safety test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_capability_usage_separates_enabled_from_used():
    """Whether a capability was available differs from whether it was exercised."""
    print("Testing capability reporting...")
    try:
        details = read(V2_SRC, "lib", "messageDetails.ts")
        assert "capability_usage" in details
        assert "Enabled, not used" in details, (
            "A capability that was available but unused explains an answer without it, so "
            "it must be distinguishable from one that was never enabled"
        )
        assert "Not enabled" in details
        assert "Enabled and used" in details

        # The history audit trail is the most useful and least discoverable part.
        assert "history_context" in details
        for field in (
            "final_api_message_count",
            "skipped_inactive_message_refs",
            "skipped_masked_message_refs",
        ):
            assert field in details, f"Expected {field} in the history summary"

        print("Capability reporting test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_inspector_is_reachable_from_the_action_row():
    """The controls are inline on hover, not buried in the overflow menu."""
    print("Testing action row placement...")
    try:
        actions = read(V2_SRC, "components", "chat", "MessageActions.tsx")
        for label in ("Show sources", "Show reasoning", "Message details"):
            assert label in actions, f"Expected a {label!r} control in the action row"

        # Grouped by purpose rather than rendered as one undifferentiated strip.
        assert "gap-3" in actions, (
            "Groups should be separated by a wider gap than the buttons within them"
        )

        # Sources and reasoning only exist for a generated response.
        assert "{!isUser && (" in actions

        message_list = read(V2_SRC, "components", "chat", "MessageList.tsx")
        assert "MessageInspector" in message_list
        assert "inspector ? 'opacity-100'" in message_list, (
            "An open panel must stay visible when the pointer leaves the message"
        )

        print("Action row placement test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_version_is_at_least_implementation_version():
    """The feature must be present in at least the version that introduced it."""
    print("Testing application version...")
    try:
        assert_app_version_at_least("0.261.013")
        print("Application version test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_message_metadata_shape_is_role_dependent,
        test_reasoning_is_fetched_not_read_from_the_message,
        test_persisted_and_live_reasoning_render_identically,
        test_sources_come_from_the_message_document,
        test_untrusted_citation_urls_cannot_become_links,
        test_capability_usage_separates_enabled_from_used,
        test_inspector_is_reachable_from_the_action_row,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
