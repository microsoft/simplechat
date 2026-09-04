#!/usr/bin/env python3
"""
Functional test for the attached-prompt card in the V2 composer.
Version: 0.261.090
Implemented in: 0.261.090

Picking a saved prompt used to paste its text into the composer. Everything below exists
because of what that cost:

  - The prompt stopped being a prompt. It could not be collapsed, taken back off, or have a
    variable corrected without editing prose in the message box.
  - Variables were filled once, in a modal, and flattened. `{{composer}}` -- "what you have
    already typed" -- resolved to nothing, because picking the prompt is the first thing you do.
  - The ordinary chat path sent no `prompt_info` at all. Only orchestration did, so a saved
    prompt used in a normal turn left no record it had been involved.
  - The planner was told the prompt's name and nothing else, and did not count it as a signal
    that the user had pointed at something.

This test asserts the wiring. The behaviour is executed by the companion
test_v2_prompt_composer_card_logic.ts, which this file bundles and runs.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

COMPOSER_TSX = V2_SRC / "components" / "chat" / "Composer.tsx"
CARD_TSX = V2_SRC / "components" / "chat" / "AttachedPromptCard.tsx"
FIELD_TSX = V2_SRC / "components" / "prompts" / "PromptVariableField.tsx"
MESSAGE_LIST_TSX = V2_SRC / "components" / "chat" / "MessageList.tsx"
PROMPT_REQUEST_TS = V2_SRC / "lib" / "promptRequest.ts"
MESSAGE_PROMPT_TS = V2_SRC / "lib" / "messagePrompt.ts"
VARIABLE_VALUES_TS = V2_SRC / "lib" / "usePromptVariableValues.ts"
CHAT_STORE_TS = V2_SRC / "stores" / "chatStore.ts"
TYPES_TS = V2_SRC / "lib" / "types.ts"
MESSAGE_TEXT_TS = V2_SRC / "lib" / "messageText.ts"
CHATS_ROUTE = APP_DIR / "route_backend_chats.py"

LOGIC_CHECK_TS = REPO_ROOT / "functional_tests" / "test_v2_prompt_composer_card_logic.ts"

RETIRED_DIALOG = V2_SRC / "components" / "prompts" / "PromptVariablesDialog.tsx"


def _read(path):
    return path.read_text(encoding="utf-8")


def _strip_comments(source):
    """Remove comments so an assertion cannot be satisfied by prose describing the rule."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*//.*$", "", without_blocks)


def test_version_is_at_least_the_implementing_release():
    """The card and its request contract landed together in one release."""
    print("Testing version...")
    assert_app_version_at_least("0.261.090")
    print("  ok  version is at or past the implementing release")
    return True


def test_the_prompt_is_attached_rather_than_pasted():
    """Pasted, a prompt is indistinguishable from typing and cannot be taken back off."""
    print("Testing attachment...")

    composer = _strip_comments(_read(COMPOSER_TSX))
    assert "const [attachedPrompt, setAttachedPrompt]" in composer, (
        "the composer must hold the prompt as state rather than as text in the box"
    )
    assert "attachPrompt(" in composer, "picking a prompt must attach it"
    assert "insertIntoComposer(content" not in composer, (
        "prompt content must never be written into the message box"
    )
    assert CARD_TSX.exists(), "the attached prompt must have a card to render in"

    card = _strip_comments(_read(CARD_TSX))
    # Collapsed by default: the common case is a prompt whose contents you already know and a
    # message you want room to write.
    assert "useState(false)" in card, "the card must start collapsed"
    assert "aria-expanded={open}" in card, "the disclosure must announce its state"
    assert "onRemove" in card, "an attached prompt must be removable in one action"

    print("  ok  the prompt is attached, not pasted")
    return True


def test_an_edit_applies_to_this_turn_only():
    """A prompt edited in the composer must not silently rewrite the saved one."""
    print("Testing this-turn editing...")

    request = _strip_comments(_read(PROMPT_REQUEST_TS))
    assert "editedContent ?? attached.originalContent" in request, (
        "the edited wording must take precedence while the saved wording is kept"
    )
    assert "attachedPromptIsEdited" in request, "an edit must be reportable as one"

    composer = _strip_comments(_read(COMPOSER_TSX))
    assert "editedContent: null" in composer, (
        "resetting must restore the saved wording rather than a copy of it"
    )
    # Nothing here may reach a prompt write route: this is a turn-local change.
    for forbidden in ("updatePrompt", "savePrompt", "/api/prompts/"):
        assert forbidden not in _strip_comments(_read(CARD_TSX)), (
            f"the card must not write back to the saved prompt ({forbidden})"
        )

    card = _strip_comments(_read(CARD_TSX))
    assert "Edited" in card, "an edited prompt must say so"
    assert "onResetContent" in card, "an edit must be reversible"

    print("  ok  an edit is turn-local, badged and reversible")
    return True


def test_a_prompt_only_turn_can_be_sent():
    """A prompt that needs no further input is already a complete message."""
    print("Testing send gating...")

    composer = _strip_comments(_read(COMPOSER_TSX))
    assert "if (!text.trim() && !attachedPrompt)" in composer, (
        "the send gate must not require typed text when a prompt is attached"
    )
    assert "(!text.trim() && !attachedPrompt) || !canPost" in composer, (
        "the send button must stay enabled for a prompt-only turn"
    )
    assert "if (!text.trim() || streaming || !canPost)" not in composer, (
        "the old typed-text-only gate must be gone"
    )

    print("  ok  a prompt-only turn is sendable")
    return True


def test_the_prompt_is_resolved_against_the_message_it_was_sent_with():
    """Resolved at pick time, `{{composer}}` is empty: nothing has been typed yet."""
    print("Testing send-time resolution...")

    composer = _strip_comments(_read(COMPOSER_TSX))
    assert "promptVariables.resolve(promptContext())" in composer, (
        "the prompt must be resolved against the live composer context at send"
    )
    assert "estimateLargeTabularRun(outgoing.message" in composer, (
        "the large-run estimate must see the whole message, not just what was typed"
    )

    values = _strip_comments(_read(VARIABLE_VALUES_TS))
    assert "resolveBuiltInPromptVariables(override ?? context)" in values, (
        "built-ins must be resolved when resolve() is called, not frozen at mount"
    )
    assert "if (isBuiltInPromptVariable(variableKey))" in values, (
        "a stored value must not be able to shadow a built-in"
    )

    print("  ok  the prompt is resolved at send")
    return True


def test_both_send_paths_report_the_prompt():
    """The chat path reported nothing, so an ordinary turn recorded no prompt at all."""
    print("Testing prompt_info on both paths...")

    store = _strip_comments(_read(CHAT_STORE_TS))
    assert "requestBody.prompt_info = options.promptInfo" in store, (
        "the ordinary chat request must carry the prompt behind the message"
    )
    assert "promptSelectionMetadata(options.promptInfo)" in store, (
        "the optimistic user message must carry the metadata the bubble reads, or it "
        "renders one way and then rearranges when the server echo arrives"
    )

    composer = _strip_comments(_read(COMPOSER_TSX))
    assert "seeds.prompt_info = promptInfo" in composer, (
        "orchestration seeds must carry the same resolved prompt"
    )
    assert composer.count("buildPromptInfo(") >= 1, (
        "both paths must build prompt_info through the one shared builder"
    )

    types = _read(TYPES_TS)
    assert "prompt_info?: Json;" in types, "the request type must declare the field it sends"

    print("  ok  both send paths report the prompt")
    return True


def test_the_server_records_what_the_bubble_needs():
    """Without user_text nothing can tell the prompt and the message apart afterwards."""
    print("Testing stored metadata...")

    route = _read(CHATS_ROUTE)
    # Matched to a closing brace on its own line: the block contains an inline `or {}`, which
    # a non-greedy match to the first brace would stop at.
    block = re.search(
        r"user_metadata\['prompt_selection'\] = \{(.*?)\n\s*\}\n", route, re.DOTALL
    )
    assert block, "prompt_selection must still be written"
    stored = block.group(1)

    # The original contract, unchanged: an older client reads back exactly as it always did.
    for key in (
        "'selected_prompt_index'",
        "'selected_prompt_text'",
        "'prompt_name'",
        "'prompt_id'",
    ):
        assert key in stored, f"the original prompt_selection key {key} must be preserved"

    for key in ("'user_text'", "'original_prompt_text'", "'prompt_variables'", "'prompt_edited'"):
        assert key in stored, f"prompt_selection must record {key}"

    print("  ok  the server records what the bubble needs")
    return True


def test_a_sent_message_shows_the_prompt_apart_from_your_words():
    """One blob buries the question inside the standing instructions it was asked with."""
    print("Testing sent-message rendering...")

    assert MESSAGE_PROMPT_TS.exists(), "the split must live in a module that can be tested"

    messages = _strip_comments(_read(MESSAGE_LIST_TSX))
    assert "readMessagePrompt(message)" in messages, (
        "the user bubble must try to recover the prompt behind the message"
    )
    assert "PromptUsedBlock" in messages, "the recovered prompt must render as its own block"
    # Mask ranges are offsets into the whole content; splitting it would move them.
    assert "masks.ranges.length === 0 ? readMessagePrompt(message) : null" in messages, (
        "a masked message must not be split"
    )

    # Copy and export read the stored content, which is still the whole message. Leaving that
    # alone is what keeps the collapsed block a display choice rather than a data loss.
    text_module = _strip_comments(_read(MESSAGE_TEXT_TS))
    assert "prompt_selection" not in text_module, (
        "messageToPlainText must keep returning the full sent message"
    )

    print("  ok  the sent message shows the prompt apart from your words")
    return True


def test_the_fill_in_dialog_folded_into_the_card():
    """Two surfaces filling one prompt is how the safety badges end up on only one of them."""
    print("Testing dialog retirement...")

    assert not RETIRED_DIALOG.exists(), (
        "PromptVariablesDialog must not survive alongside the card that replaced it"
    )
    assert FIELD_TSX.exists(), "the shared variable field must exist"
    assert VARIABLE_VALUES_TS.exists(), "the shared values hook must exist"

    # The rules the dialog documented, now the hook's and the field's to keep.
    values = _strip_comments(_read(VARIABLE_VALUES_TS))
    assert "shared ? {} : recallPromptValues(promptId)" in values, (
        "nothing may be pre-filled in a shared conversation"
    )
    field = _strip_comments(_read(FIELD_TSX))
    assert "Reused" in field and "From this chat" in field, (
        "an auto-filled value must be visibly distinct from one the reader typed"
    )
    assert "isResolvedBuiltIn ?" in field, "a resolved built-in must be read-only"

    composer = _read(COMPOSER_TSX)
    assert "PromptVariablesDialog" not in composer, "the retired dialog must not be referenced"

    print("  ok  the dialog folded into the card without losing its rules")
    return True


def test_no_remote_asset_references():
    """Browser assets are local-only; a CDN reference must not creep in."""
    print("Testing for remote asset references...")

    offenders = []
    for path in [CARD_TSX, FIELD_TSX, PROMPT_REQUEST_TS, MESSAGE_PROMPT_TS, VARIABLE_VALUES_TS]:
        source = _strip_comments(_read(path))
        for match in re.finditer(r"https?://[^\s'\"`)]+", source):
            url = match.group(0)
            if "schemas" in url or "w3.org" in url:
                continue
            offenders.append(f"{path.name}: {url}")

    assert not offenders, f"Remote asset references are not allowed: {offenders}"
    print("  ok  no remote asset references")
    return True


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("Testing composer card logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node
    # can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-prompt-composer-card-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(LOGIC_CHECK_TS),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                "--define:import.meta.env={}",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    print(f"  ok  {passed} TypeScript logic checks passed")
    return True


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_the_prompt_is_attached_rather_than_pasted,
        test_an_edit_applies_to_this_turn_only,
        test_a_prompt_only_turn_can_be_sent,
        test_the_prompt_is_resolved_against_the_message_it_was_sent_with,
        test_both_send_paths_report_the_prompt,
        test_the_server_records_what_the_bubble_needs,
        test_a_sent_message_shows_the_prompt_apart_from_your_words,
        test_the_fill_in_dialog_folded_into_the_card,
        test_no_remote_asset_references,
        test_the_typescript_logic_checks_pass,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as error:  # noqa: BLE001
            print(f"  FAIL  {test.__name__}: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
