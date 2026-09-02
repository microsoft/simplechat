#!/usr/bin/env python3
"""
Functional test for the V2 chat Phase 1 parity fixes.
Version: 0.261.012
Implemented in: 0.261.012

Six reported problems in the V2 chat page, each traced to a specific mismatch between what
the client sent or read and what the Flask routes actually accept or return:

1. Word, PowerPoint and email export did nothing, because the client submitted an HTML form
   to endpoints that require a JSON body.
2. Generated images rendered as a raw URL, because the client read a field the payload has
   never had.
3. Every message claimed to be attempt "2 of 2", because thread_attempt is one-based and the
   client added one to it.
4. The badge beside the conversation title never changed, because it showed the user's
   globally active group rather than anything about the conversation.
5. Selecting an agent had no effect, because the server reads `agent_info` as a dict and the
   client sent `agent_selection` as a string.
6. Newlines rendered differently depending on who sent the message.

This test ensures each fix stays in place and that none of the underlying API contracts are
re-guessed.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2_SRC = os.path.join(REPO_ROOT, "application", "v2_ui", "src")
APP = os.path.join(REPO_ROOT, "application", "single_app")


def read(*parts):
    with open(os.path.join(*parts), "r", encoding="utf-8") as handle:
        return handle.read()


def test_exports_send_json_not_a_form():
    """The export endpoints reject anything that is not a JSON body."""
    print("Testing export request shape...")
    try:
        route = read(APP, "route_backend_conversation_export.py")

        # Establish the server's requirement rather than assuming it.
        assert "request.get_json(silent=True)" in route, (
            "The export routes are expected to read a JSON body"
        )
        assert "'Request body is required'" in route, (
            "The export routes are expected to reject a request with no JSON body"
        )

        endpoints = read(V2_SRC, "lib", "endpoints.ts")
        assert "'Content-Type': 'application/json'" in endpoints, (
            "Exports must be sent as JSON, or the server answers 400"
        )
        assert "response.blob()" in endpoints, (
            "Word and PowerPoint stream the document itself and must be read as a blob"
        )

        actions = read(V2_SRC, "components", "chat", "MessageActions.tsx")
        # The original defect: a form submission cannot carry a JSON body.
        assert "createElement('form')" not in actions, (
            "A form POST cannot send JSON, which is why exports returned 400"
        )
        assert "form.submit()" not in actions, "The hidden-form export must be gone"

        print("Export request shape test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_email_export_is_not_a_file_download():
    """Email returns a JSON draft, not a document, and needs its own handling."""
    print("Testing email draft handling...")
    try:
        route = read(APP, "route_backend_conversation_export.py")
        assert "jsonify(draft_payload), 200" in route, (
            "The email draft endpoint returns JSON, unlike the other two exports"
        )

        endpoints = read(V2_SRC, "lib", "endpoints.ts")
        assert "emailDraftMailtoUrl" in endpoints, (
            "The draft must be turned into a mailto: URL"
        )
        assert "mailto:?subject=" in endpoints, "Expected a mailto: URL to be constructed"
        assert "saveEmailDraftAttachments" in endpoints, (
            "A mailto: URL cannot carry attachments, so the images are saved separately"
        )
        assert "encodeURIComponent" in endpoints, (
            "Subject and body must be encoded before going into a URL"
        )

        print("Email draft test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_images_are_read_from_content():
    """An image message carries its image in content, not in a separate field."""
    print("Testing image resolution...")
    try:
        hydrate = read(APP, "functions_image_messages.py")
        # The server writes the image into content in all three of its forms.
        assert "message['content'] = image_url_builder(message_id)" in hydrate, (
            "The server rewrites content to /api/image/<id> for blob-backed images"
        )
        assert "def is_external_image_url" in hydrate

        images = read(V2_SRC, "lib", "images.ts")
        for form in ("data:image/", "/api/image/"):
            assert form in images, f"Expected the {form} form to be recognised"
        assert re.search(r"https\?:\\/\\/", images), (
            "An externally hosted image arrives as a plain http(s) URL"
        )

        message_list = read(V2_SRC, "components", "chat", "MessageList.tsx")
        # The original defect: gating on a field the payload never had meant the image
        # message fell through to the text renderer.
        assert "message.image_url" not in message_list, (
            "image_url does not exist on the payload; the image is in content"
        )
        assert "resolveImageSource" in message_list, (
            "The image message must resolve its source from content"
        )
        assert "onError" in message_list, (
            "An image that fails to load should say so rather than showing a broken icon"
        )

        print("Image resolution test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_attempt_numbering_is_one_based():
    """thread_attempt counts from 1, and the total cannot come from the message list."""
    print("Testing attempt numbering...")
    try:
        # Every creation site in the application writes 1 for a first attempt.
        operations = read(APP, "functions_simplechat_operations.py")
        assert '"thread_attempt": 1' in operations, (
            "thread_attempt is one-based at creation"
        )

        conversations = read(APP, "route_backend_conversations.py")
        assert "'available_attempts': available_attempts" in conversations, (
            "switch-attempt is the only endpoint reporting the full attempt set"
        )

        threads = read(V2_SRC, "lib", "threads.ts")
        # The original defect was `(thread_attempt ?? 0) + 1`, which reported 2 for a
        # first-and-only attempt.
        assert not re.search(r"thread_attempt\s*\?\?\s*0\s*\)\s*\+\s*1", threads), (
            "thread_attempt is one-based and must not have one added to it"
        )
        assert "attemptsByThread" in threads, (
            "The total must come from the server, not the filtered message list"
        )

        actions = read(V2_SRC, "components", "chat", "MessageActions.tsx")
        assert "attemptState(" in actions, "The shared attempt rule should be used"
        assert "attempts.show" in actions, (
            "The control must be hidden when only one attempt is known to exist"
        )

        store = read(V2_SRC, "stores", "chatStore.ts")
        assert "available_attempts" in store, (
            "The reported attempt set must be remembered when switching"
        )

        print("Attempt numbering test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_title_badge_comes_from_the_conversation():
    """The badge describes the conversation, not the user's active group."""
    print("Testing title badge source...")
    try:
        page = read(V2_SRC, "pages", "ChatPage.tsx")
        # The original defect: a global value rendered in a per-conversation slot.
        assert "active_group_name" not in page, (
            "The header must not show the globally active group as a conversation property"
        )
        assert "ConversationBadges" in page

        badges = read(V2_SRC, "lib", "conversationBadges.ts")
        # Rules mirrored from addChatTypeBadges in chat-conversations.js.
        assert "personal_multi_user" in badges, "Shared conversations get a 'shared' badge"
        assert "startsWith('group')" in badges, "Group conversations show the group name"
        assert "startsWith('public')" in badges, "Public conversations show the workspace"
        assert "public - " in badges, "Public badges are labelled 'public - <name>'"
        assert "type === 'primary'" in badges, (
            "The name comes from the primary context"
        )
        assert "scope_locked" in badges, "The scope lock indicator is part of the row"

        classic = read(APP, "static", "js", "chat", "chat-conversations.js")
        assert "function addChatTypeBadges" in classic, (
            "The classic rules this mirrors should still exist"
        )

        # Everything needed is already on the metadata response.
        route = read(APP, "route_backend_conversations.py")
        for key in ('"chat_type"', '"context"', '"classification"', '"scope_locked"'):
            assert key in route, f"Expected {key} on the conversation metadata response"

        print("Title badge test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_agent_selection_is_sent_as_agent_info():
    """The server reads agent_info as a dict; a string is silently discarded."""
    print("Testing agent selection payload...")
    try:
        chats = read(APP, "route_backend_chats.py")
        assert "data.get('agent_info')" in chats, (
            "The chat route reads the selection from agent_info"
        )
        assert "isinstance(data.get('agent_info'), dict)" in chats, (
            "agent_info must be a dict or the server ignores it"
        )

        agents = read(V2_SRC, "lib", "agents.ts")
        for field in (
            "id",
            "name",
            "display_name",
            "is_global",
            "is_group",
            "group_id",
            "group_name",
        ):
            assert field in agents, f"agent_info should carry {field}"

        store = read(V2_SRC, "stores", "chatStore.ts")
        # agent_info now reaches the request through the shared selection rule, which is
        # also what stops a model identity travelling with it. Following the indirection
        # keeps this about the guarantee rather than about a particular call site.
        assert "buildSelectionFields" in store, (
            "The chat request must send agent_info"
        )
        selection = read(V2_SRC, "lib", "chatRequestSelection.ts")
        assert "agent_info" in selection, (
            "The selection rule must emit agent_info, which is the key the server reads"
        )
        # The original defect.
        assert "agent_selection =" not in store, (
            "agent_selection is not a key the server reads"
        )

        # The catalog has no selection_key; that is a model concept.
        catalog = read(APP, "functions_agent_catalog.py")
        assert "selection_key" not in catalog, (
            "Agent records carry no selection_key, so it must not be used to identify one"
        )
        composer = read(V2_SRC, "components", "chat", "Composer.tsx")
        assert "agent.selection_key" not in composer, (
            "The agent picker must not key off a field agents do not have"
        )

        print("Agent selection test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_newlines_render_the_same_for_both_roles():
    """A single newline is a line break regardless of who sent the message."""
    print("Testing newline rendering...")
    try:
        # The markdown renderer lives in its own module; the thread around it does not.
        assistant_markdown = read(V2_SRC, "components", "chat", "AssistantMarkdown.tsx")
        assert "remarkBreaks" in assistant_markdown, (
            "Assistant markdown must treat a single newline as a line break"
        )
        assert "remarkPlugins={[remarkGfm, remarkBreaks]}" in assistant_markdown, (
            "remark-breaks must actually be registered, not just imported"
        )
        # User messages already preserved newlines; that is the behaviour being matched.
        message_list = read(V2_SRC, "components", "chat", "MessageList.tsx")
        assert "whitespace-pre-wrap" in message_list

        citations = read(V2_SRC, "lib", "citations.ts")
        assert r"\n{3,}" in citations, (
            "Runs of blank lines are collapsed, as the classic client does, so an "
            "unclipped run does not open a large gap"
        )

        package = read(REPO_ROOT, "application", "v2_ui", "package.json")
        assert "remark-breaks" in package, "remark-breaks must be a declared dependency"

        print("Newline rendering test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_conversation_summary_uses_the_content_key():
    """The stored summary body is under `content`, not `text`."""
    print("Testing summary field name...")
    try:
        export = read(APP, "route_backend_conversation_export.py")
        assert "'content': summary_text" in export, (
            "The generated summary stores its body under content"
        )

        details = read(V2_SRC, "components", "chat", "ConversationDetails.tsx")
        assert "summary?.content" in details, (
            "The details panel must read summary.content"
        )
        assert "summary.text" not in details, (
            "summary.text does not exist, so the summary would never display"
        )

        types = read(V2_SRC, "lib", "types.ts")
        assert "content?: string" in types

        print("Summary field name test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_failures_are_reported_to_the_user():
    """A server-side action that fails must say so rather than looking inert."""
    print("Testing failure reporting...")
    try:
        actions = read(V2_SRC, "components", "chat", "MessageActions.tsx")
        assert "toast.error" in actions, (
            "An export failure must be surfaced; a silent failure is what made these "
            "buttons look broken in the first place"
        )
        assert "toast.success" in actions

        toaster = read(V2_SRC, "components", "ui", "Toaster.tsx")
        assert "aria-live" in toaster, (
            "Notifications must be announced, since the user cannot see the action happen"
        )
        assert "role={item.tone === 'error' ? 'alert' : 'status'}" in toaster

        shell = read(V2_SRC, "components", "layout", "AppShell.tsx")
        assert "<Toaster />" in shell, "The toaster must actually be mounted"

        print("Failure reporting test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_version_is_at_least_implementation_version():
    """The fixes must be present in at least the version that introduced them."""
    print("Testing application version...")
    try:
        assert_app_version_at_least("0.261.012")
        print("Application version test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_exports_send_json_not_a_form,
        test_email_export_is_not_a_file_download,
        test_images_are_read_from_content,
        test_attempt_numbering_is_one_based,
        test_title_badge_comes_from_the_conversation,
        test_agent_selection_is_sent_as_agent_info,
        test_newlines_render_the_same_for_both_roles,
        test_conversation_summary_uses_the_content_key,
        test_failures_are_reported_to_the_user,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
