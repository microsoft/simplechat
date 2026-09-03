#!/usr/bin/env python3
"""
Functional test for V2 inline image approvals surviving the view that started them.

Version: 0.261.050
Implemented in: 0.261.050

Approving an inline image proposal used to be tied to the conversation being on screen. The
approval itself was not -- it is a blocking request, and the serial queue behind it is
module-level -- but everything the user could see about it was. `selectConversation` empties
the message list, so leaving the conversation unmounted every `ImageProposalScope` in it and
took the approval state with it. Coming back rebuilt those scopes empty, so cards that were
mid-generation read as untouched: no status, Approve enabled again, "Approve all" back, and an
invitation to pay a second time for images that were already on their way. They did arrive,
because the requests never stopped, but nothing said so.

Reloading the page was worse still. The request died with the page while the server carried on
and stored the image regardless, so the only thing actually lost was the knowledge that it was
coming.

This test ensures the three pieces of the fix stay in place:

  - approval state is owned by `imageProposalStore`, keyed by conversation and message, so it
    outlives the card, the message bubble and the conversation view alike;
  - approvals in flight are persisted and picked back up after a reload, polled through the
    status route until their image lands, and written off on a deadline rather than spinning
    forever; and
  - an approval running out of sight is reported where the user actually is -- on the
    conversation row in the rail, and in a single notice.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
APP_DIR = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.050"

TRACKING_MODULE = V2_SRC / "lib" / "imageProposalTracking.ts"
RESUME_MODULE = V2_SRC / "lib" / "imageProposalResume.ts"
STORE_MODULE = V2_SRC / "stores" / "imageProposalStore.ts"
CARD_COMPONENT = V2_SRC / "components" / "chat" / "InlineImageProposal.tsx"
SCOPE_COMPONENT = V2_SRC / "components" / "chat" / "ImageProposalContext.tsx"
RAIL_COMPONENT = V2_SRC / "components" / "chat" / "ConversationRail.tsx"
TOAST_STORE = V2_SRC / "stores" / "toastStore.ts"
ENDPOINTS_MODULE = V2_SRC / "lib" / "endpoints.ts"
APP_COMPONENT = V2_SRC / "App.tsx"
CHAT_PAGE = V2_SRC / "pages" / "ChatPage.tsx"
CHAT_ROUTES = APP_DIR / "route_backend_chats.py"

LOGIC_TEST = REPO_ROOT / "functional_tests" / "test_v2_inline_image_proposal_resume_logic.mjs"
STORE_TEST = REPO_ROOT / "functional_tests" / "test_v2_inline_image_proposal_store.mjs"
NODE_MODULES = REPO_ROOT / "application" / "v2_ui" / "node_modules"

STATUS_ROUTE = "/api/chat/image-proposals/status"


def _read(path):
    if not path.exists():
        raise AssertionError(f"Expected file is missing: {path}")
    return path.read_text(encoding="utf-8", errors="ignore")


def test_approval_state_outlives_the_conversation_view():
    """State that dies with the message list cannot report an approval that does not."""
    print("Testing that approval state outlives the conversation view...")
    store_source = _read(STORE_MODULE)
    scope_source = _read(SCOPE_COMPONENT)

    if "useState<ProposalCardStates>" in scope_source:
        raise AssertionError(
            "The proposal scope holds the card state map in React state. selectConversation "
            "clears the message list, so that map is destroyed by opening another conversation "
            "-- exactly when an approval most needs to keep reporting itself."
        )
    print("  The scope holds no card state map of its own.")

    # Keyed by conversation as well as message: two conversations can both be mid-approval,
    # and a key that only named the message would let one overwrite the other's cards.
    if "function scopeKey(conversationId: string, assistantMessageId: string)" not in store_source:
        raise AssertionError(
            "Card states are not keyed by conversation and message, so approvals in different "
            "conversations can collide."
        )
    if "selectCardStates(state, conversationId, assistantMessageId)" not in scope_source:
        raise AssertionError("The scope does not read its card states from the store.")
    if "storeUpdateCardState(conversationId, assistantMessageId, cardKey, patch)" not in scope_source:
        raise AssertionError("The scope does not write card state back to the store.")
    print("  The store owns them, addressed by conversation and message.")

    print("Approval state ownership test passed!")
    return True


def test_an_approval_is_tracked_from_before_it_is_sent():
    """A record that starts after the request would miss the window it exists to cover."""
    print("Testing that approvals are tracked...")
    card_source = _read(CARD_COMPONENT)

    if "beginApproval({" not in card_source:
        raise AssertionError("The card does not record the approval it is starting.")

    # Ordering matters: the record has to exist before the request, because the case being
    # recovered is the page disappearing while the request is in flight.
    begin_at = card_source.index("beginApproval({")
    enqueue_at = card_source.index("enqueueImageApproval(")
    if begin_at > enqueue_at:
        raise AssertionError(
            "The approval is recorded after it is enqueued, so a reload in between leaves a "
            "request running that nothing knows about."
        )
    print("  The record is written before the request is sent.")

    # A card with an approval already running must not start a second one. That is real money.
    if "if (!tracked) {" not in card_source:
        raise AssertionError(
            "The card ignores a refused begin, so a duplicate approval can be sent for an "
            "image that is already being generated and paid for."
        )
    if "if (get().inFlight[id]) {" not in _read(STORE_MODULE):
        raise AssertionError("The store does not refuse a duplicate approval record.")
    print("  A duplicate approval for the same card is refused.")

    for outcome in ("'generated'", "'failed'"):
        if f"endApproval(activeRecordId, {outcome})" not in card_source:
            raise AssertionError(f"The card never ends its record with the {outcome} outcome.")
    print("  Both outcomes end the record.")

    # The image arriving is the one signal common to every route it can arrive by: this
    # approval's own response, a poll after a reload, or a conversation that already had it.
    if not re.search(r"if \(!result\) \{\s*\n\s*return;\s*\n\s*\}\s*\n\s*endApproval\(recordId", card_source):
        raise AssertionError(
            "The card does not clear its record when the image appears, so an approval settled "
            "by any route other than its own response is resumed forever."
        )
    print("  The image appearing clears the record however it arrived.")

    print("Approval tracking test passed!")
    return True


def test_a_reload_picks_the_approval_back_up():
    """The request dies with the page; the work does not, so the record must survive."""
    print("Testing reload recovery...")
    tracking_source = _read(TRACKING_MODULE)
    resume_source = _read(RESUME_MODULE)
    store_source = _read(STORE_MODULE)
    app_source = _read(APP_COMPONENT)

    # sessionStorage, not localStorage: it survives the reload being recovered from and does
    # not reach a second tab, which could not settle a record it never started. Checked against
    # the code rather than the file, so the comment explaining the choice does not trip it.
    tracking_code = re.sub(r"/\*[\s\S]*?\*/|//.*", "", tracking_source)
    if "window.sessionStorage" not in tracking_code:
        raise AssertionError("In-flight approvals are not persisted to sessionStorage.")
    if "localStorage" in tracking_code:
        raise AssertionError(
            "In-flight approvals are persisted to localStorage, which reaches other tabs and "
            "would show them progress for an approval they cannot settle."
        )
    print("  Records are persisted per tab.")

    if "saveApprovals(Object.values(inFlight))" not in store_source:
        raise AssertionError("The store does not persist its in-flight records.")
    if "restorePersistedApprovals()" not in resume_source:
        raise AssertionError("Nothing restores the persisted records after a reload.")
    print("  They are written on every change and read back on load.")

    # Started from the shell, because a reload can land on any route and the approval still
    # has to be recovered and reported.
    if "startImageApprovalTracking()" not in app_source:
        raise AssertionError(
            "Approval tracking is not started by the app shell, so a reload that does not land "
            "on the chat page recovers nothing."
        )
    print("  Recovery starts with the app, not with the chat page.")

    # A restored card must not offer Approve while its image is still coming.
    if "status: 'generating'" not in store_source or "resumed: true" not in store_source:
        raise AssertionError(
            "A restored record does not put its card back into the generating state, so the "
            "card offers Approve again for an image that is already on its way."
        )
    print("  A restored card reports the approval instead of offering it again.")

    print("Reload recovery test passed!")
    return True


def test_polling_is_bounded_and_gives_up():
    """A poll with no ceiling and no deadline is a spinner that never resolves."""
    print("Testing the poll...")
    resume_source = _read(RESUME_MODULE)
    tracking_source = _read(TRACKING_MODULE)

    if "fetchImageProposalStatus(" not in resume_source:
        raise AssertionError("The resume watcher does not ask the status route anything.")
    if "earliestStart(" not in resume_source:
        raise AssertionError(
            "The poll does not narrow its window, so it reads every proposal image the "
            "conversation has ever contained on every request."
        )
    print("  It polls the status route, windowed to what it is waiting for.")

    if "MAX_POLL_MS" not in resume_source or "POLL_BACKOFF" not in resume_source:
        raise AssertionError("The poll has no backoff, so a long generation hammers the server.")
    if "document.hidden" not in resume_source:
        raise AssertionError(
            "The poll runs while the tab is hidden, where nothing it learns can be shown."
        )
    print("  It backs off, and stops while the tab is hidden.")

    for bound in ("GIVE_UP_AFTER_MS", "STALE_RECORD_MS"):
        if f"export const {bound}" not in tracking_source:
            raise AssertionError(f"{bound} is not defined, so a lost approval is never resolved.")
    if "settleLost(" not in resume_source:
        raise AssertionError(
            "An approval that never arrives is not written off, so its card spins forever."
        )
    print("  A lost approval is written off rather than left spinning.")

    # One re-read per poll, and only for the conversation being looked at: opening any other
    # conversation reads it anyway.
    if "reloadMessages()" not in resume_source:
        raise AssertionError("An arrived image is never fetched into the thread.")
    if "activeConversationId === conversationId" not in resume_source:
        raise AssertionError(
            "The thread is re-read without checking which conversation is open, so a poll for "
            "one conversation reloads another."
        )
    print("  An arrival re-reads the open conversation once.")

    print("Poll test passed!")
    return True


def test_the_client_polls_a_route_that_exists():
    """The poll is only a recovery if the route it asks is really there."""
    print("Testing the poll's route...")
    routes_source = _read(CHAT_ROUTES)
    client_source = _read(ENDPOINTS_MODULE)

    if f"@bp.route('{STATUS_ROUTE}/<conversation_id>', methods=['GET'])" not in routes_source:
        raise AssertionError("The image proposal status route is not registered.")
    print("  The route is registered.")

    if f"{STATUS_ROUTE}/${{encodeURIComponent(conversationId)}}" not in client_source:
        raise AssertionError("The client does not call the status route.")
    print("  The client calls it.")

    # What the route may and may not return, and how it authorizes, is the subject of
    # test_image_proposal_status_endpoint.py.
    print("Poll route test passed!")
    return True


def test_an_approval_out_of_sight_is_reported_where_the_user_is():
    """A spinner nobody can see is the complaint, not the fix."""
    print("Testing the away reporting...")
    rail_source = _read(RAIL_COMPONENT)
    resume_source = _read(RESUME_MODULE)
    toast_source = _read(TOAST_STORE)

    if "selectInFlightCount(state, conversation.id)" not in rail_source:
        raise AssertionError(
            "The conversation row does not show that images are being generated in it."
        )
    if "aria-label={label}" not in rail_source:
        raise AssertionError("The rail indicator is not labelled for assistive technology.")
    print("  The rail row reports its conversation's approvals.")

    if "toast.pending(" not in resume_source or "toast.settle(" not in resume_source:
        raise AssertionError("No notice is raised while approvals run out of sight.")
    if "record.conversationId !== visibleConversationId" not in resume_source:
        raise AssertionError(
            "The notice counts approvals in the conversation on screen too, where it merely "
            "repeats what every card is already showing."
        )
    # Which conversation is open is not the same as which conversation's cards are visible:
    # the chat store keeps a conversation open while the reader is in My Workspace.
    if "setVisibleConversation(activeConversationId)" not in _read(CHAT_PAGE):
        raise AssertionError(
            "The chat page does not report which conversation's cards are on screen, so "
            "leaving the chat page entirely would still count as watching them."
        )
    print("  A single notice covers only what the user cannot already see.")

    if "update: (id, message)" not in toast_source:
        raise AssertionError(
            "The toast store cannot rewrite a pending notice, so a changing count would have "
            "to be dismissed and re-pushed, moving and flickering it."
        )
    print("  It counts down in place rather than stacking.")

    print("Away reporting test passed!")
    return True


def test_no_html_sink_or_remote_asset_was_introduced():
    """The V2 UI loads nothing from a CDN, and none of this renders model output as HTML."""
    print("Testing rendering safety...")
    remote_pattern = re.compile(r"https?://(?!localhost)[^\s'\"`)]+", re.I)

    for path in (TRACKING_MODULE, RESUME_MODULE, STORE_MODULE, CARD_COMPONENT, SCOPE_COMPONENT):
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


def test_resume_logic_behaves():
    """Run the runtime checks for matching, windowing and persistence.

    The assertions above prove the pieces are wired together. They cannot prove that a restored
    record recognises its own image and refuses somebody else's, which is where a mistake would
    cost a user their picture, so the companion Node test executes the real modules.
    """
    print("Testing resume logic behaviour...")
    return _run_node_test(LOGIC_TEST)


def test_store_behaves():
    """Run the runtime checks for the store itself.

    Two of its rules cost real money when they are wrong: a duplicate approval sends a second
    request for an image already being generated, and a record that is not persisted cannot be
    resumed, so the card offers to generate the image again. Neither is visible from the source.

    Needs `npm install` in `application/v2_ui`, because the store depends on zustand. Skipped
    rather than failed when that has not been done, since the absence of a package directory is
    a fact about the machine and not about the code.
    """
    print("Testing store behaviour...")
    if not (NODE_MODULES / "zustand").exists():
        print("  application/v2_ui/node_modules is not installed; skipping the store test.")
        print("  Install it with: npm install --prefix application/v2_ui")
        return True
    return _run_node_test(STORE_TEST)


def _run_node_test(path):
    """Execute one of the Node runtime tests, reporting its result."""
    if not path.exists():
        raise AssertionError(f"The runtime test is missing: {path}")

    node = shutil.which("node")
    if not node:
        print("  Node is not installed; skipping the runtime test.")
        print(f"  Run it with: node {path.relative_to(REPO_ROOT)}")
        return True

    completed = subprocess.run(
        [node, str(path)],
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
        if line.startswith("FAIL") or "runtime checks" in line:
            print(f"  {line}")

    if completed.returncode != 0:
        print(output)
        raise AssertionError(f"{path.name} failed; see the output above.")

    print(f"  {path.name} passed.")
    return True


def test_version_was_incremented():
    """The application version records when this shipped."""
    print("Testing version...")
    version = assert_app_version_at_least(
        IMPLEMENTED_IN,
        reason="V2 inline image approvals surviving the view that started them.",
    )
    print(f"  config.py VERSION is {version}.")
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_approval_state_outlives_the_conversation_view,
        test_an_approval_is_tracked_from_before_it_is_sent,
        test_a_reload_picks_the_approval_back_up,
        test_polling_is_bounded_and_gives_up,
        test_the_client_polls_a_route_that_exists,
        test_an_approval_out_of_sight_is_reported_where_the_user_is,
        test_no_html_sink_or_remote_asset_was_introduced,
        test_resume_logic_behaves,
        test_store_behaves,
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
