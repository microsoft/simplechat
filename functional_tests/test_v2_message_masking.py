#!/usr/bin/env python3
"""
Functional test for V2 message masking.
Version: 0.261.014
Implemented in: 0.261.014

Masking hides part or all of a message from the model and from other readers. It is a real
capability of the application -- the server strips masked content from the history it sends
to the model -- and the V2 interface did not implement it at all.

The contract has three details that are easy to get wrong:

1. The endpoint takes an `action`, and only a fixed set of values is accepted.
2. The server does NOT trust the offsets it is sent. It resolves the selection against the
   stored content, falling back to a markdown-stripped projection, and rejects a selection it
   cannot place uniquely. A client that assumes success will show a mask that does not exist.
3. The response reports only `masked` and `masked_ranges`. It does not return who applied a
   whole-message mask, so the client cannot read the attribution back from it.

This test ensures the client matches all three, and that masked text never reaches the DOM.
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


def test_all_mask_actions_are_supported():
    """Every action the server accepts should be reachable from the interface."""
    print("Testing mask actions...")
    try:
        functions = read(APP, "functions_message_masking.py")
        for action in (
            "mask_all",
            "mask_selection",
            "unmask_message",
            "clear_all_masks",
        ):
            assert f"'{action}'" in functions, f"Expected {action} to be a server action"

        masking = read(V2_SRC, "lib", "masking.ts")
        for action in ("mask_all", "mask_selection", "unmask_message", "clear_all_masks"):
            assert action in masking, f"Expected the client to know about {action}"

        endpoints = read(V2_SRC, "lib", "endpoints.ts")
        assert "/mask`" in endpoints, "Expected the mask endpoint to be called"
        assert "maskMessage" in endpoints

        route = read(APP, "route_backend_chats.py")
        assert "/api/message/<message_id>/mask" in route

        print("Mask actions test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_selection_carries_text_not_just_offsets():
    """The server resolves the selection by text, so the text must be sent."""
    print("Testing selection payload...")
    try:
        functions = read(APP, "functions_message_masking.py")
        # The offsets are only a fast path; the text is what the server falls back to.
        assert "_resolve_selection_offsets_from_projected_markdown" in functions, (
            "The server resolves a selection against a markdown-stripped projection"
        )
        assert "Selection no longer matches the stored message content" in functions, (
            "A selection that cannot be placed is rejected rather than guessed at"
        )

        masking = read(V2_SRC, "lib", "masking.ts")
        for field in (
            "start",
            "end",
            "text",
            "display_start",
            "display_end",
            "display_text",
        ):
            assert field in masking, f"Expected {field} in the selection payload"

        assert "buildSelection" in masking
        assert "getSelection()" in masking, (
            "Offsets come from the user's actual DOM selection"
        )

        print("Selection payload test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_rejection_is_explained_to_the_user():
    """A selection the server cannot place must not look like a dead button."""
    print("Testing rejection handling...")
    try:
        store = read(V2_SRC, "stores", "chatStore.ts")
        assert "error.status === 400" in store, (
            "A rejected selection is a 400 and needs its own message"
        )
        assert "could not be matched" in store, (
            "The user should be told why the mask did not apply"
        )
        assert "error.status === 403" in store, (
            "Masking someone else's message is a 403"
        )
        assert "toast.error" in store

        print("Rejection handling test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_masked_text_is_never_rendered():
    """A redaction that only hides text with CSS is not a redaction."""
    print("Testing that masked content is removed...")
    try:
        masking = read(V2_SRC, "lib", "masking.ts")
        assert "applyMasks" in masking
        # Masked spans are cut out of the content by offset before rendering.
        assert "content.slice(cursor, range.start)" in masking, (
            "Masked spans must be cut out of the content, not hidden after rendering"
        )
        assert "MASK_PLACEHOLDER" in masking, (
            "A placeholder keeps the redaction out of the markdown pipeline"
        )

        span = read(V2_SRC, "components", "chat", "MaskedSpan.tsx")
        # The component receives only the range metadata, never the text.
        assert "range.text" not in span, (
            "The masked text must not be handed to the component that stands in for it"
        )

        message_list = read(V2_SRC, "components", "chat", "MessageList.tsx")
        assert "masks.fullyMasked" in message_list, (
            "A fully masked message must not render its body at all"
        )

        print("Masked content test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_masks_apply_before_citation_parsing():
    """Mask offsets are canonical positions and citation parsing rewrites the string."""
    print("Testing mask and citation ordering...")
    try:
        assistant_markdown = read(V2_SRC, "components", "chat", "AssistantMarkdown.tsx")
        applied_at = assistant_markdown.index("applyMasks(content")
        parsed_at = assistant_markdown.index("parseCitations(masked.text")
        assert applied_at < parsed_at, (
            "Masks must be applied before citations are parsed, or the canonical offsets "
            "no longer match the string they index into"
        )

        print("Ordering test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_mask_ownership_is_shown():
    """A reader should be able to tell whose redaction they are looking at."""
    print("Testing mask attribution...")
    try:
        functions = read(APP, "functions_message_masking.py")
        for field in ("display_name", "masked_by_display_name", "masked_timestamp"):
            assert field in functions, f"Expected {field} to be stored with a mask"

        masking = read(V2_SRC, "lib", "masking.ts")
        assert "describeMask" in masking
        assert "Masked by" in masking, "The tooltip should name who applied the mask"

        # The response does not return the attribution, so the client fills it in itself.
        route = read(APP, "route_backend_chats.py")
        mask_response = route[route.index("'masked': message_doc['metadata']") :][:300]
        assert "masked_by_display_name" not in mask_response, (
            "The mask response is expected NOT to return attribution; if that changes, "
            "the client should read it from the response instead of inferring it"
        )

        store = read(V2_SRC, "stores", "chatStore.ts")
        assert "masked_by_display_name" in store, (
            "The acting user supplies the attribution the response omits"
        )

        print("Mask attribution test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_permission_rule_mirrors_the_server():
    """There is no can_* field, so the client mirrors the rule and handles a 403."""
    print("Testing mask permissions...")
    try:
        route = read(APP, "route_backend_chats.py")
        assert "You can only mask your own messages" in route
        assert "metadata', {}).get('user_info', {}).get('user_id')" in route, (
            "The author is read from metadata.user_info.user_id"
        )

        masking = read(V2_SRC, "lib", "masking.ts")
        assert "canMask" in masking
        assert "user_info" in masking, (
            "The client mirrors the server's author check"
        )

        actions = read(V2_SRC, "components", "chat", "MessageActions.tsx")
        assert "maskingAllowed" in actions, (
            "The control should only be offered when the user may use it"
        )

        print("Mask permissions test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_selection_popup_stays_on_screen():
    """A control rendered outside the viewport cannot be used."""
    print("Testing popup placement...")
    try:
        span = read(V2_SRC, "components", "chat", "MaskedSpan.tsx")
        assert "window.innerHeight" in span, (
            "Placement must consider the viewport, since a selection can sit anywhere"
        )
        assert "Math.max(" in span and "Math.min(" in span, (
            "The position must be clamped to stay on screen"
        )
        assert "VIEWPORT_MARGIN" in span

        print("Popup placement test passed!")
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
        assert_app_version_at_least("0.261.014")
        print("Application version test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_all_mask_actions_are_supported,
        test_selection_carries_text_not_just_offsets,
        test_rejection_is_explained_to_the_user,
        test_masked_text_is_never_rendered,
        test_masks_apply_before_citation_parsing,
        test_mask_ownership_is_shown,
        test_permission_rule_mirrors_the_server,
        test_selection_popup_stays_on_screen,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
