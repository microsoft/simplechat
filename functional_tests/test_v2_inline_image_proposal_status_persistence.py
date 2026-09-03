#!/usr/bin/env python3
"""
Functional test for V2 inline image proposal approval state surviving a re-render.

Version: 0.261.045
Implemented in: 0.261.045

Approving several image proposals in one reply used to unravel the moment the first image came
back. The remaining cards lost their "Generating image..." status, their Approve buttons became
enabled again, and the "Approve all" control reappeared -- while those approvals were in fact
still draining through the serial queue and their images did arrive a moment later. The user
was told nothing was happening and invited to pay for the same image twice.

The cause was not in the proposal code at all. `AssistantMarkdown` built its react-markdown
`components` map inline in JSX, so every render handed react-markdown a fresh function identity
for each node type. react-markdown uses those functions as the *element type* for the nodes
they handle (`hast-util-to-jsx-runtime` resolves `state.components[name]` and passes it to
`jsx()`), and React unmounts and remounts a subtree whenever an element's type changes. So
every render of a message tore down and rebuilt every rich block inside it -- proposal cards,
Mermaid diagrams and charts alike -- and appending a generated image to the thread is precisely
such a render.

This test ensures both halves of the fix stay in place:

  - the component map is memoised, so the rich blocks in a message are no longer rebuilt every
    time anything about that message changes, and
  - a card's approval state is owned by the message's proposal scope rather than by the card,
    so an approval still in flight keeps reporting itself even if the card is rebuilt anyway --
    by a conversation reload, a mask, a collaborator's message, or anything else.

It also ensures the approved card no longer repeats the proposal's badges, which describe an
image that does not exist yet and say nothing once it does.
"""

import re
import subprocess
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.045"

MARKDOWN_COMPONENT = V2_SRC / "components" / "chat" / "AssistantMarkdown.tsx"
CARD_COMPONENT = V2_SRC / "components" / "chat" / "InlineImageProposal.tsx"
SCOPE_COMPONENT = V2_SRC / "components" / "chat" / "ImageProposalContext.tsx"
CARD_STATE_MODULE = V2_SRC / "lib" / "imageProposalCardState.ts"
SPEC_MODULE = V2_SRC / "lib" / "imageProposalSpec.ts"

LOGIC_TEST = REPO_ROOT / "functional_tests" / "test_v2_inline_image_proposal_logic.mjs"


def _read(path):
    if not path.exists():
        raise AssertionError(f"Expected file is missing: {path}")
    return path.read_text(encoding="utf-8", errors="ignore")


def test_markdown_components_are_memoised():
    """The renderer does not hand react-markdown a new component map on every render."""
    print("Testing that rich blocks are not rebuilt on every render...")
    source = _read(MARKDOWN_COMPONENT)

    # The map has to be passed by reference. An object literal in the JSX is the bug: it makes
    # every node type a new function on every render, and React remounts on a changed type.
    if not re.search(r"components=\{components\}", source):
        raise AssertionError(
            "AssistantMarkdown does not pass a stable component map to react-markdown. An "
            "inline object literal gives every rich block a new element type per render, so "
            "React rebuilds them all and a proposal card loses its approval state."
        )
    if re.search(r"components=\{\{", source):
        raise AssertionError(
            "AssistantMarkdown still builds its component map inline in the JSX."
        )
    print("  The component map is passed by reference, not built inline.")

    if not re.search(r"const components = useMemo<Components>\(", source):
        raise AssertionError("The component map is not memoised with useMemo.")
    print("  The map is memoised.")

    # `renderTokens` is closed over by most of the map's entries, so a fresh identity for it
    # would invalidate the memo on every render and put the remount straight back.
    if not re.search(r"const renderTokens = useCallback\(", source):
        raise AssertionError(
            "renderTokens is not memoised, so the component map it is captured by is rebuilt "
            "on every render regardless of the useMemo around it."
        )
    print("  renderTokens is memoised, so the map's dependencies are stable.")

    # The `?? []` defaults did the same thing more quietly: a new array per render for any
    # message without citations, masks or maths, which is most of them.
    for name in ("NO_CITATIONS", "NO_MASKS", "NO_MATH"):
        if name not in source:
            raise AssertionError(
                f"{name} is missing, so an inline `?? []` default is minting a new array on "
                "every render and invalidating the memo."
            )
    if re.search(r"=\s*(citations|masks|math)\s*\?\?\s*\[\]", source):
        raise AssertionError("An optional input still defaults to a fresh inline array.")
    print("  The optional inputs default to shared empties.")

    print("Component map test passed!")
    return True


def test_card_state_is_owned_by_the_message_not_the_card():
    """An approval in flight keeps reporting itself even if its card is rebuilt."""
    print("Testing that approval state outlives the card...")
    card_source = _read(CARD_COMPONENT)
    scope_source = _read(SCOPE_COMPONENT)

    # The heart of the fix. State the card holds itself is state the card loses.
    for field in ("status", "queuePosition", "failure", "prompt", "editing"):
        setter = f"set{field[0].upper()}{field[1:]}"
        if re.search(rf"const \[[^\]]*\b{setter}\b[^\]]*\]\s*=\s*useState", card_source):
            raise AssertionError(
                f"The card still holds `{field}` in local state, so it is discarded whenever "
                "the card is rebuilt."
            )
    print("  The card holds no approval state of its own.")

    if "cardStates[cardKey]" not in card_source:
        raise AssertionError("The card does not read its state from the proposal scope.")
    if "updateCardState(cardKey" not in card_source:
        raise AssertionError("The card does not write its state back to the proposal scope.")
    print("  It reads and writes that state through the scope.")

    # The scope is rendered by the message bubble, which is keyed on the message id, so it
    # survives the markdown subtree being rebuilt underneath it.
    if "applyCardStatePatch" not in scope_source or "useState<ProposalCardStates>" not in scope_source:
        raise AssertionError("The proposal scope does not own the card state map.")
    print("  The scope owns the map.")

    # Every status the card can be in has to be reachable from a rebuilt card, so all of them
    # must go through the scope rather than a local setter.
    for status in ("'queued'", "'generating'", "'generated'", "'error'", "'cancelled'"):
        if f"status: {status}" not in card_source:
            raise AssertionError(f"The card never records the {status} status in the scope.")
    print("  Every status is recorded in the scope.")

    # A card that was queued or generating is not pending, so a rebuilt card is excluded from
    # the pending count and the "Approve all" control does not come back mid-generation.
    if "status === 'idle'" not in card_source:
        raise AssertionError(
            "Pending is not gated on the idle status, so a card mid-generation can be counted "
            "as awaiting a decision again."
        )
    print("  A card mid-generation is not counted as pending.")

    print("Card state ownership test passed!")
    return True


def test_cards_are_keyed_by_their_position_in_the_message():
    """Two cards in one message cannot share one entry of the state map."""
    print("Testing card identity...")
    spec_source = _read(SPEC_MODULE)
    card_source = _read(CARD_COMPONENT)
    markdown_source = _read(MARKDOWN_COMPONENT)

    if "export function proposalCardKey(" not in spec_source:
        raise AssertionError("proposalCardKey is not exported.")
    if "proposalCardKey(spec, blockIndex)" not in card_source:
        raise AssertionError("The card does not derive its key from its block index.")
    print("  The card key comes from the fence's position in the message.")

    # The index is stamped by rehypeRichBlockIndex and has to reach the card, which means it
    # must be read before the image-proposal branch returns rather than after it.
    if not re.search(
        r"const index = readRichBlockIndex\(code\);[\s\S]*?<InlineImageProposal",
        markdown_source,
    ):
        raise AssertionError(
            "The block index is read after the image proposal branch returns, so the card "
            "never receives one and every card in a message shares a fallback key."
        )
    if "blockIndex={index ?? undefined}" not in markdown_source:
        raise AssertionError("The block index is not passed to the card.")
    print("  The renderer passes it to the card.")

    # A DOM id has to be unique across the document, and every message's first proposal has
    # block index 0, so the prompt field's id must not be derived from the card key.
    if not re.search(r"const promptFieldId = `\$\{cardId\}-prompt`", card_source):
        raise AssertionError(
            "The prompt field id is not derived from useId, so two messages' first proposals "
            "would render duplicate DOM ids and their labels would address the wrong field."
        )
    print("  The prompt field keeps a document-unique id.")

    print("Card identity test passed!")
    return True


def test_the_approved_card_drops_the_proposal_badges():
    """Once the image is here, the proposal's descriptions describe nothing."""
    print("Testing the approved card...")
    card_source = _read(CARD_COMPONENT)

    approved = re.search(
        r"if \(result\) \{(.*?)\n    \}\n", card_source, re.S
    )
    if not approved:
        raise AssertionError("The approved-result branch could not be read from the card.")
    branch = approved.group(1)

    if "ProposalBadges" in branch:
        raise AssertionError(
            "The approved card still shows the proposal's badges -- the visual type, slide "
            "reference and context -- which describe an image that does not exist yet."
        )
    if "activeSpec.description" in branch:
        raise AssertionError("The approved card still shows the proposal's description.")
    print("  No badges and no description once the image has been generated.")

    # The title is what identifies the image in the reply, and the model name is a fact about
    # the image rather than about the proposal, so both stay.
    if "{displayTitle}" not in branch:
        raise AssertionError("The approved card no longer shows the proposal's title.")
    if "model_deployment_name" not in branch:
        raise AssertionError("The approved card no longer shows which model generated it.")
    if "<ApprovedImage" not in branch:
        raise AssertionError("The approved card no longer shows the image.")
    print("  The title, the image and the model name stay.")

    # The badges are still what a card awaiting a decision shows, which is the point of them.
    if "<ProposalBadges badges={badges} />" not in card_source:
        raise AssertionError("A pending proposal no longer shows its badges.")
    print("  A pending proposal still shows them.")

    print("Approved card test passed!")
    return True


def test_no_html_sink_or_remote_asset_was_introduced():
    """A proposal is model output, and the V2 UI loads nothing from a CDN."""
    print("Testing rendering safety...")
    remote_pattern = re.compile(r"https?://(?!localhost)[^\s'\"`)]+", re.I)

    for path in (MARKDOWN_COMPONENT, CARD_COMPONENT, SCOPE_COMPONENT, CARD_STATE_MODULE):
        source = _read(path)
        for sink in ("dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML"):
            if sink in source:
                raise AssertionError(f"{path.relative_to(REPO_ROOT)} uses {sink}.")
        for match in remote_pattern.finditer(source):
            raise AssertionError(
                f"{path.relative_to(REPO_ROOT)} references a remote URL: {match.group(0)}"
            )

    print("  No HTML sink and no remote URL in any of the touched files.")
    print("Rendering safety test passed!")
    return True


def test_card_state_behaves():
    """Run the runtime checks for card identity and the card state patcher.

    The assertions above prove the pieces are wired together. They cannot prove that one
    card's progress leaves another's alone, which is the entire bug, so the companion Node
    test executes the real modules and this runs it.
    """
    print("Testing card state behaviour...")
    if not LOGIC_TEST.exists():
        raise AssertionError(f"The runtime logic test is missing: {LOGIC_TEST}")

    node = shutil.which("node")
    if not node:
        print("  Node is not installed; skipping the runtime logic test.")
        print(f"  Run it with: node {LOGIC_TEST.relative_to(REPO_ROOT)}")
        return True

    completed = subprocess.run(
        [node, str(LOGIC_TEST)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    output = (completed.stdout or "") + (completed.stderr or "")

    # Node below 22.6 cannot import TypeScript directly. That is a limitation of the
    # environment, not a defect in the code under test.
    if completed.returncode != 0 and "Unknown file extension" in output:
        print("  This Node cannot import TypeScript directly (needs 22.6 or newer); skipping.")
        return True

    for line in output.splitlines():
        if "card" in line.lower() or "patch" in line.lower() or "runtime checks" in line:
            print(f"  {line}")

    if completed.returncode != 0:
        print(output)
        raise AssertionError("The runtime logic test failed; see the output above.")

    print("Card state behaviour test passed!")
    return True


def test_version_was_incremented():
    """The application version records when this shipped."""
    print("Testing version...")
    version = assert_app_version_at_least(
        IMPLEMENTED_IN,
        reason="V2 inline image proposal approval state surviving a re-render.",
    )
    print(f"  config.py VERSION is {version}.")
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_markdown_components_are_memoised,
        test_card_state_is_owned_by_the_message_not_the_card,
        test_cards_are_keyed_by_their_position_in_the_message,
        test_the_approved_card_drops_the_proposal_badges,
        test_no_html_sink_or_remote_asset_was_introduced,
        test_card_state_behaves,
        test_version_was_incremented,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as error:  # noqa: BLE001
            print(f"FAILED: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(1 for r in results if r)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
