#!/usr/bin/env python3
"""
Functional test for V2 conversation details and composer gating.
Version: 0.261.015
Implemented in: 0.261.015

Two related problems:

1. The V2 conversation details panel flattened the metadata `tags` array into a single list
   of chips. Every tag carries a `category`, and the useful fields differ per category, so
   documents ended up mixed in with model names, participants and topics. Source documents
   were reduced to a count.

2. Every composer control was shown whenever its capability was enabled, which made the row
   crowded and offered "Read URLs" when there was no URL to read. The classic client gates
   two of these on what is currently typed.

This test ensures tags are split by category, source documents are their own paged section
with an honest note about citation tracking, and the gating rules match the classic client.
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


def test_tags_are_split_by_category():
    """Tags are heterogeneous and must not be rendered as one list."""
    print("Testing tag categorisation...")
    try:
        route = read(APP, "route_backend_conversations.py")
        assert '"tags": conversation_item.get(\'tags\', [])' in route, (
            "Tags come from the metadata endpoint"
        )

        details = read(V2_SRC, "lib", "conversationDetails.ts")
        for category in (
            "document",
            "model",
            "agent",
            "participant",
            "semantic",
            "web",
        ):
            assert f"'{category}'" in details, f"Expected the {category} category"
        assert "tagsOfCategory" in details

        panel = read(V2_SRC, "components", "chat", "ConversationDetails.tsx")
        for section in ("Models and agents", "Participants", "Topics", "Web sources"):
            assert section in panel, f"Expected a {section!r} section"

        print("Tag categorisation test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_source_documents_have_their_own_section():
    """Documents are the most useful part and were previously reduced to a count."""
    print("Testing source documents...")
    try:
        details = read(V2_SRC, "lib", "conversationDetails.ts")
        assert "readSourceDocuments" in details
        # The fallback order the classic client uses.
        assert "used_documents_tracking_version" in details, (
            "Whether citations were tracked determines which source is authoritative"
        )
        assert "legacy_used_documents" in details, (
            "Older conversations fall back to the legacy list"
        )

        panel = read(V2_SRC, "components", "chat", "ConversationDetails.tsx")
        assert "Source documents" in panel
        assert "DOCUMENTS_PER_PAGE" in panel, (
            "A long conversation can draw on dozens of documents"
        )
        assert "predates citation tracking" in panel, (
            "A conversation with no citation tracking must say so rather than showing "
            "every document as uncited"
        )

        print("Source documents test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_summary_can_be_generated_on_demand():
    """The summary is produced by a model and is not created automatically."""
    print("Testing summary generation...")
    try:
        route = read(APP, "route_backend_conversations.py")
        assert "/api/conversations/<conversation_id>/summary" in route
        assert "'summary': summary_data" in route

        endpoints = read(V2_SRC, "lib", "endpoints.ts")
        assert "generateConversationSummary" in endpoints

        panel = read(V2_SRC, "components", "chat", "ConversationDetails.tsx")
        assert "Generate summary" in panel and "Regenerate summary" in panel
        assert "loadMetadata(metadata.conversation_id)" in panel, (
            "The panel should re-read the conversation rather than trust the response"
        )

        print("Summary generation test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_url_access_is_gated_on_a_url_being_present():
    """Read URLs needs both the capability and something to read."""
    print("Testing URL access gating...")
    try:
        classic = read(APP, "static", "js", "chat", "chat-input-actions.js")
        assert "enable_url_access" in classic
        assert "getPromptUrls" in classic, (
            "The classic client gates this on URLs found in the prompt"
        )

        gating = read(V2_SRC, "lib", "composerGating.ts")
        assert "promptUrls" in gating
        assert "enable_url_access" in gating
        assert "hasUrls" in gating, "Presence of a URL must be part of the condition"

        composer = read(V2_SRC, "components", "chat", "Composer.tsx")
        assert "gating.showUrlAccess" in composer
        # A control that disappears must not leave its option set.
        assert "next.urlAccess = false" in composer, (
            "An option whose control is no longer visible must be cleared, or the request "
            "carries a capability the user cannot see they enabled"
        )

        print("URL access gating test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_deep_research_is_gated_on_having_a_source():
    """Deep research needs somewhere to research: the web, or supplied URLs."""
    print("Testing deep research gating...")
    try:
        classic = read(APP, "static", "js", "chat", "chat-input-actions.js")
        assert "updateDeepResearchAvailability" in classic

        gating = read(V2_SRC, "lib", "composerGating.ts")
        assert "webSearchActive" in gating
        assert "urlAccessActive" in gating
        assert "enable_source_review" in gating

        composer = read(V2_SRC, "components", "chat", "Composer.tsx")
        assert "gating.showDeepResearch" in composer
        assert "next.deepResearch = false" in composer

        print("Deep research gating test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_image_generation_is_mutually_exclusive():
    """The image endpoint ignores retrieval options and takes no chat model."""
    print("Testing image generation exclusivity...")
    try:
        classic = read(APP, "static", "js", "chat", "chat-input-actions.js")
        assert "syncImageGenerationDependentControls" in classic, (
            "The classic client disables the other controls while generating an image"
        )

        gating = read(V2_SRC, "lib", "composerGating.ts")
        assert "disabledByImageGeneration" in gating
        assert "showModelPicker" in gating

        composer = read(V2_SRC, "components", "chat", "Composer.tsx")
        assert "gating.disabledByImageGeneration" in composer
        assert "gating.showModelPicker" in composer

        print("Image generation exclusivity test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_chat_width_is_a_persisted_preference():
    """Neither a fixed measure nor full width suits everyone."""
    print("Testing chat width preference...")
    try:
        store = read(V2_SRC, "stores", "uiStore.ts")
        assert "chatWidth" in store
        assert "toggleChatWidth" in store
        assert "simplechat.v2.chat-width" in store, (
            "The preference must persist, like the theme and rail state"
        )

        width = read(V2_SRC, "lib", "chatWidth.ts")
        assert "chatWidthClass" in width and "bubbleWidthClass" in width

        # The thread and the composer must agree, or the composer stays cramped.
        message_list = read(V2_SRC, "components", "chat", "MessageList.tsx")
        composer = read(V2_SRC, "components", "chat", "Composer.tsx")
        assert "chatWidthClass(chatWidth)" in message_list
        assert "chatWidthClass(chatWidth)" in composer, (
            "Widening the thread without the composer leaves the controls just as crowded"
        )

        print("Chat width test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_untrusted_tag_values_cannot_become_links():
    """A web tag value originates in model output."""
    print("Testing web tag safety...")
    try:
        details = read(V2_SRC, "lib", "conversationDetails.ts")
        assert "/^https?:\\/\\//i.test(label)" in details, (
            "Only http(s) values may become links"
        )

        panel = read(V2_SRC, "components", "chat", "ConversationDetails.tsx")
        assert 'rel="noopener noreferrer"' in panel
        assert "source.href ? (" in panel, (
            "A value without a safe URL should render as text, not a link"
        )

        print("Web tag safety test passed!")
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
        assert_app_version_at_least("0.261.015")
        print("Application version test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_tags_are_split_by_category,
        test_source_documents_have_their_own_section,
        test_summary_can_be_generated_on_demand,
        test_url_access_is_gated_on_a_url_being_present,
        test_deep_research_is_gated_on_having_a_source,
        test_image_generation_is_mutually_exclusive,
        test_chat_width_is_a_persisted_preference,
        test_untrusted_tag_values_cannot_become_links,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
