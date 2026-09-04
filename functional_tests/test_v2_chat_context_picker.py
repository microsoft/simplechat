#!/usr/bin/env python3
# test_v2_chat_context_picker.py
"""
Functional test for the V2 chat context picker.
Version: 0.261.089
Implemented in: 0.261.089

The V2 composer shipped with a Documents button that was a plain on/off, and a
``selectedDocumentIds`` field that was declared, forwarded to both the chat
request and the orchestration seeds, and never populated by anything. Choosing
a document in the workspace and pressing Chat navigated to ``/chats``, which is
a full page load into the *classic* interface.

Three groups of checks arrive together here, because each covers a failure the
others cannot see:

* Structural, in Python. That the workspace hand-off stays inside V2, and that
  the composer no longer carries the write-only field.
* Metadata parity, in Python. The streaming path -- the one the V2 client uses
  -- did not record the tag filter it searched with, while the non-streaming
  path did. A retry or edit of a tag-filtered message therefore replayed a
  wider search than the one that produced the answer.
* Behavioural, in TypeScript. The chip-to-request mapping, bundled and executed
  by the companion ``test_v2_chat_context_request.ts``.
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"

CHATS_ROUTE_PY = APP_ROOT / "route_backend_chats.py"
CONVERSATIONS_ROUTE_PY = APP_ROOT / "route_backend_conversations.py"
COMPOSER_TSX = V2_DIR / "src" / "components" / "chat" / "Composer.tsx"
EXPLORER_TSX = V2_DIR / "src" / "components" / "documents" / "DocumentExplorer.tsx"
TAGS_TSX = V2_DIR / "src" / "pages" / "workspace" / "TagsSection.tsx"
RUN_VIEW_TSX = V2_DIR / "src" / "components" / "chat" / "OrchestrationRunView.tsx"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_chat_context_request.ts"


def test_the_version_carries_the_feature():
    """The picker is present from the version it was implemented in."""
    print("\nTesting version...")
    assert_app_version_at_least("0.261.089")
    print("  The application version covers the context picker.")
    return True


def test_the_workspace_hand_off_stays_in_v2():
    """Choosing Chat in the workspace must not drop the user into the classic UI."""
    print("\nTesting the workspace hand-off...")

    explorer = EXPLORER_TSX.read_text(encoding="utf-8")

    assert "window.location.href = `/chats" not in explorer, (
        "DocumentExplorer still hands off to the classic chat page. That is a full "
        "page load out of V2, triggered by the action most likely to follow "
        "choosing a document."
    )
    assert "navigate(`/chat?" in explorer, (
        "DocumentExplorer should navigate within the router so the selection "
        "arrives in the V2 composer."
    )
    assert "buildContextHandoffParams" in explorer, (
        "The hand-off should be built through the shared helper so the classic "
        "query vocabulary stays in one place."
    )

    tags = TAGS_TSX.read_text(encoding="utf-8")
    assert "navigate(`/chat?" in tags and "contextTags" in tags, (
        "The tags section should be able to hand a tag to the composer; chatting "
        "against a tag is the reason most tags exist."
    )

    print("  Documents and tags hand off into the V2 composer.")
    return True


def test_the_composer_no_longer_carries_a_write_only_selection():
    """`selectedDocumentIds` was never populated; the chip row replaces it."""
    print("\nTesting the composer's context state...")

    composer = COMPOSER_TSX.read_text(encoding="utf-8")

    assert "selectedDocumentIds" not in composer, (
        "The composer still references selectedDocumentIds, which nothing ever "
        "filled in."
    )
    assert "contextItems" in composer, (
        "The composer should hold its context references in contextItems."
    )
    assert "readContextQuery" in composer, (
        "The composer should offer the `#` menu."
    )
    assert "DocumentPickerPopover" in composer, (
        "The Documents button should open the picker rather than toggling."
    )

    print("  The composer drives the request from its chip row.")
    return True


def test_sending_clears_the_chips_with_the_text():
    """Chips and their `#[...]` text are two views of one thing and must clear together.

    Left behind on send, the chips would sit over an empty box holding tokens that
    are no longer in it -- and the next keystroke reconciles those away, so the
    references appear to survive the send and then vanish one character into the
    following message.
    """
    print("\nTesting draft clearing...")

    composer = COMPOSER_TSX.read_text(encoding="utf-8")

    assert "const clearDraft = () => {" in composer, (
        "The composer should clear its draft through one helper, so the plain and "
        "orchestrated send paths cannot drift apart."
    )

    # Both send paths, and no stragglers still clearing only the text: the draft is
    # emptied in exactly one place, which is what keeps them from drifting apart.
    assert composer.count("clearDraft();") >= 2, (
        "Both the plain and the orchestrated send should clear the draft."
    )
    assert composer.count("setText('')") == 1, (
        "The composer empties its text in more than one place, so a send path can "
        "clear the box while leaving the chip row behind."
    )
    assert "setContextQuery(null)" in composer, (
        "Clearing the draft should also close any open `#` query."
    )

    print("  Both send paths clear the chips with the text.")
    return True


def test_caches_are_not_poisoned_by_cancelled_requests():
    """An aborted fetch is not an answer, and must not be remembered as one.

    StrictMode aborts the first run of every effect on mount, and each debounced
    keystroke aborts the request before it. Caching those as "no result" would make
    the empty answer the common one: documents shown as bare uuids for the rest of
    the session, and `#` offering no tags for a minute at a time.
    """
    print("\nTesting cache behaviour on cancellation...")

    titles = (V2_DIR / "src" / "lib" / "documentTitles.ts").read_text(encoding="utf-8")
    assert titles.count("signal?.aborted") >= 2, (
        "documentTitles caches lookup results without checking whether the request "
        "was cancelled, so an aborted lookup is remembered as an unnameable "
        "document and never retried."
    )

    mentions = (V2_DIR / "src" / "lib" / "contextMentions.ts").read_text(encoding="utf-8")
    assert "options.signal?.aborted" in mentions, (
        "The tag vocabulary is cached without checking for cancellation, so a "
        "superseded keystroke caches an empty vocabulary for the whole TTL."
    )

    print("  Cancelled requests are not cached.")
    return True


def test_removing_a_chip_cannot_orphan_a_shared_reference():
    """Two documents can share a title, and so two chips can share one token.

    Stripping the text while a second chip still points at it leaves that chip
    with no token. Reconciliation drops it on the next keystroke, but a message
    sent before that keystroke still carries its document id -- grounding the
    answer in something the user had already removed.
    """
    print("\nTesting chip removal with shared tokens...")

    composer = COMPOSER_TSX.read_text(encoding="utf-8")

    assert "remaining.some((entry) => entry.token === item.token)" in composer, (
        "Removing a chip strips its token unconditionally, which orphans any other "
        "chip sharing that token."
    )
    assert "stillReferenced" in composer, (
        "Bulk removal should also keep tokens that remaining chips still use."
    )

    print("  A shared token survives until its last chip is removed.")
    return True


def test_the_plan_names_its_documents():
    """A plan that lists raw ids cannot be reviewed."""
    print("\nTesting orchestration plan legibility...")

    run_view = RUN_VIEW_TSX.read_text(encoding="utf-8")
    assert "useDocumentTitles" in run_view, (
        "The plan view should resolve document ids to titles. Deciding whether "
        "the planner picked the right contract is the entire purpose of showing "
        "the plan before it runs, and a bare uuid does not support that."
    )

    print("  Planned documents are shown by name.")
    return True


def _workspace_search_metadata_blocks(source: str):
    """The ``user_metadata['workspace_search'] = { ... }`` literals that record a search.

    Four of these exist. Two are the ``{'search_enabled': False}`` placeholder written
    when a turn used no document context at all, which has nothing to record and is
    deliberately excluded here; the other two are the streaming and non-streaming
    paths that actually searched.
    """
    blocks = []
    marker = "user_metadata['workspace_search'] = {"
    start = source.find(marker)
    while start != -1:
        end = source.find("}", start)
        block = source[start:end]
        if "'search_enabled': True" in block:
            blocks.append(block)
        start = source.find(marker, end)
    return blocks


def test_both_chat_paths_record_the_tag_filter():
    """The streaming path dropped tags, so V2 retries replayed a wider search."""
    print("\nTesting workspace_search metadata parity...")

    source = CHATS_ROUTE_PY.read_text(encoding="utf-8")
    blocks = _workspace_search_metadata_blocks(source)

    assert len(blocks) >= 2, (
        "Expected both the streaming and non-streaming chat paths to record "
        f"workspace_search metadata for a real search; found {len(blocks)}."
    )

    for index, block in enumerate(blocks):
        assert "'tags'" in block, (
            f"workspace_search block {index + 1} does not record the tag filter. "
            "Without it, _build_replayed_document_context has no tags to restore "
            "and a retry silently searches more widely than the original."
        )
        # The document ids were already recorded on both paths; asserted here so a
        # future edit cannot quietly drop one while adding the other.
        assert "'requested_document_ids'" in block, (
            f"workspace_search block {index + 1} stopped recording the requested "
            "document ids."
        )

    print(f"  All {len(blocks)} workspace_search blocks record tags and document ids.")
    return True


def test_replay_restores_the_tag_filter():
    """Recording tags is only useful if the replay reads them back."""
    print("\nTesting retry and edit replay...")

    source = CONVERSATIONS_ROUTE_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def _build_replayed_document_context\(.*?\n(?=\n\ndef )",
        source,
        re.DOTALL,
    )
    assert match, "_build_replayed_document_context could not be located"

    body = match.group(0)
    assert "'tags'" in body, (
        "The replayed document context does not restore the tag filter, so a "
        "retried or edited message answers a different question than the one it "
        "originally answered."
    )

    print("  Retry and edit restore the tag filter.")
    return True


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("\nTesting chip-to-request mapping (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where
    # node can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-chat-context-check.mjs"
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
                # chatContext reaches nothing Vite-specific, but the define keeps this
                # identical to the other logic-check runners.
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
        test_the_version_carries_the_feature,
        test_the_workspace_hand_off_stays_in_v2,
        test_the_composer_no_longer_carries_a_write_only_selection,
        test_sending_clears_the_chips_with_the_text,
        test_caches_are_not_poisoned_by_cancelled_requests,
        test_removing_a_chip_cannot_orphan_a_shared_reference,
        test_the_plan_names_its_documents,
        test_both_chat_paths_record_the_tag_filter,
        test_replay_restores_the_tag_filter,
        test_the_typescript_logic_checks_pass,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"  FAILED  {test.__name__}: {error}")
            results.append(False)

    print(f"\n{sum(1 for r in results if r)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
