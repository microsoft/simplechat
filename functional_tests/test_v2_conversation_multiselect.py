#!/usr/bin/env python3
"""
Functional test for conversation multi-select in the V2 (React) interface.

Version: 0.261.053
Implemented in: 0.261.053

The V2 conversation rail could pick several conversations, but only in order to export them:
a permanent "Select" button swapped every row into a checkbox, the only bulk action was
Export, and there was no Shift-click range. Pin, hide and delete stayed single-row, even
though the backend has had bulk routes for all three since the classic interface shipped
them. This covers the feature that closed that gap:

  - Hover-revealed checkboxes in a reserved left gutter, with Ctrl/Cmd+click to toggle and
    Shift+click to extend a range, sharing one selection algebra with the documents explorer.
  - A bulk bar offering pin/unpin, hide, export and delete, drawn only while something is
    selected.
  - Confirmation in front of delete, which previously fired immediately with no undo.

No backend change was needed: the client drives ``POST /api/delete_multiple_conversations``,
``POST /api/conversations/bulk-pin`` and ``POST /api/conversations/bulk-hide``, which already
served the classic interface.

Much of what is asserted here is that the client keeps its half of that contract. In
particular, all three routes match on ``user_id`` against the personal conversations
container, so a shared conversation's id posted to them is silently reported in
``failed_ids`` and nothing happens to it — which is why the selection must be split by kind
before any request is sent.

The behavioural half of this lives in ``test_v2_conversation_multiselect_logic.ts``, run below.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.053"

RAIL_TSX = V2_SRC / "components" / "chat" / "ConversationRail.tsx"
STORE_TS = V2_SRC / "stores" / "chatStore.ts"
ENDPOINTS_TS = V2_SRC / "lib" / "endpoints.ts"
LIST_SELECTION_TS = V2_SRC / "lib" / "listSelection.ts"
CONVERSATION_SELECTION_TS = V2_SRC / "lib" / "conversationSelection.ts"
DOCUMENT_EXPLORER_TS = V2_SRC / "lib" / "documentExplorer.ts"
MODAL_TSX = V2_SRC / "components" / "ui" / "Modal.tsx"
CONFIRM_TSX = V2_SRC / "components" / "ui" / "ConfirmDialog.tsx"
CONVERSATION_ROUTE = APP_DIR / "route_backend_conversations.py"


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def test_version_is_at_least_the_implementing_release():
    """The feature must be present in the version the app reports."""
    print("Testing version...")
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  application version is at or beyond the implementing release")


def test_the_bulk_routes_the_client_calls_exist():
    """Every bulk path the client posts to must be a route the server registers."""
    print("Testing endpoint reuse...")

    endpoints = _read(ENDPOINTS_TS)
    route = _read(CONVERSATION_ROUTE)

    for path in (
        "/api/delete_multiple_conversations",
        "/api/conversations/bulk-pin",
        "/api/conversations/bulk-hide",
    ):
        assert path in endpoints, f"the client must call {path}"
        assert f"'{path}'" in route, f"{path} must be a registered route"

    # No new backend surface: the whole feature reuses what the classic interface drives.
    assert "bulkPinConversations" in endpoints and "bulkHideConversations" in endpoints, (
        "the bulk pin and hide wrappers must exist"
    )

    print("  ok  the client reuses the existing bulk routes")


def test_the_request_bodies_match_what_the_routes_read():
    """A misnamed field is a 400, or worse a silently ignored action."""
    print("Testing request shapes...")

    endpoints = _read(ENDPOINTS_TS)
    route = _read(CONVERSATION_ROUTE)

    assert "conversation_ids: conversationIds" in endpoints, (
        "all three routes read data.get('conversation_ids')"
    )
    assert "data.get('conversation_ids'" in route, "the route must read conversation_ids"

    # bulk-pin and bulk-hide set rather than toggle, and reject anything else.
    assert "action," in endpoints, "bulk pin and hide must send an explicit action"
    assert "'pin' | 'unpin'" in endpoints, "pin must be set, not toggled"
    assert "'hide' | 'unhide'" in endpoints, "hide must be set, not toggled"
    assert "pin_action not in ['pin', 'unpin']" in route
    assert "hide_action not in ['hide', 'unhide']" in route

    print("  ok  the request bodies match what the routes read")


def test_the_routes_are_still_personal_only():
    """
    The split exists because of what these routes do, so the reason is asserted here.

    All three read the personal conversations container and compare `user_id`. If that ever
    changes to accept shared conversations, the client-side split becomes dead weight and
    this test should be the thing that says so.
    """
    print("Testing the reason for the split...")

    route = _read(CONVERSATION_ROUTE)

    for marker in (
        "def bulk_pin_conversations",
        "def bulk_hide_conversations",
        "def delete_multiple_conversations",
    ):
        assert marker in route, f"{marker} must exist"

    # Both toggle routes reject a conversation owned by somebody else rather than acting.
    assert route.count("conversation_item.get('user_id') != user_id") >= 2, (
        "bulk pin and hide must still be scoped to the caller's own conversations"
    )
    assert "_authorize_personal_conversation_read" in route, (
        "bulk delete must still authorize each conversation as a personal one"
    )

    print("  ok  the bulk routes remain personal-only, so the client must split")


def test_a_shared_conversation_never_reaches_a_bulk_route():
    """A shared id posted to a bulk route is a silent no-op, so it must not be sent."""
    print("Testing the personal / shared split...")

    store = _read(STORE_TS)
    selection = _read(CONVERSATION_SELECTION_TS)

    assert "partitionBySpecies" in selection, "the split must be a named, testable rule"
    assert store.count("partitionBySpecies(targets)") == 3, (
        "delete, pin and hide must each split the selection before sending"
    )

    # Only the personal half is ever handed to a bulk route.
    for call in (
        "deleteConversationsApi(personalIds)",
        "bulkPinConversationsApi(\n                    personalIds",
        "bulkHideConversationsApi(\n                    personalIds",
    ):
        assert call in store, f"expected a bulk call taking only personal ids: {call}"

    # And the shared half goes one at a time through the collaboration routes.
    for call in (
        "collaborationDeleteAction(removal.id, removal.action)",
        "toggleCollaborationPinned(id)",
        "toggleCollaborationHidden(id)",
    ):
        assert call in store, f"shared conversations must be driven through {call}"

    print("  ok  shared conversations are routed away from the bulk endpoints")


def test_removing_a_shared_conversation_picks_delete_or_leave():
    """Posting the wrong one either destroys other people's thread or is refused."""
    print("Testing delete versus leave...")

    selection = _read(CONVERSATION_SELECTION_TS)

    assert "collaborativeRemovals" in selection
    assert "can_delete_conversation === true ? 'delete' : 'leave'" in selection, (
        "delete must require the permission the server reports; anything else is a leave"
    )

    print("  ok  removal chooses delete or leave per conversation")


def test_the_confirmation_and_the_request_cannot_disagree():
    """
    A dialog that promises a leave and performs a delete destroys other people's thread.

    Both the wording and the request must be decided by one rule reading one copy of the
    permissions. The store used to re-decide from the collaboration store's copy, which is
    refreshed by role-change events while the rail's row is not — so a promoted member could
    be shown "Leave" and have `delete` posted on their behalf.
    """
    print("Testing that the promise matches the action...")

    rail = _read(RAIL_TSX)
    store = _read(STORE_TS)
    selection = _read(CONVERSATION_SELECTION_TS)

    assert "export function removalActionFor" in selection, (
        "delete-vs-leave must be one named rule"
    )
    # The wording, the row menu label and the request all read it.
    assert "removalActionFor(conversation) === 'leave'" in selection, (
        "the summary must classify rows through the shared rule"
    )
    assert "removalActionFor(conversation) === 'leave' ?" in rail, (
        "the row menu label must come from the shared rule"
    )
    assert "removeConversation(targets[0].id, removalActionFor(targets[0]))" in rail, (
        "confirming must perform exactly the action the dialog described"
    )
    assert "decidedAction ??" in store, (
        "the store must honour a caller-decided action rather than re-deciding"
    )

    # And the two copies of the permissions are kept in step, so the fallback path agrees too.
    assert "function syncListedPermissions" in store, (
        "a refreshed membership must be written back to the rail row"
    )
    assert store.count("syncListedPermissions(conversationId)") >= 3, (
        "opening a conversation and every membership refresh must sync the row"
    )

    print("  ok  the confirmation, the row menu and the request share one decision")


def test_a_batch_does_not_abandon_itself_on_one_failure():
    """One conversation refusing must not leave the rest of a bulk action half-done."""
    print("Testing batch resilience...")

    store = _read(STORE_TS)

    assert store.count("Promise.allSettled(") >= 3, (
        "each per-item batch must settle rather than reject on the first failure"
    )
    assert "failed_ids ?? []" in store, (
        "the bulk routes succeed partially, so failed_ids must be read rather than the 200 trusted"
    )
    assert "partialFailureMessage" in store, "a partial failure must be reported"

    print("  ok  a partial failure is survived and reported")


def test_the_selection_cannot_outlive_the_rows_it_names():
    """A bulk action on invisible rows is the surprise a delete button must never produce."""
    print("Testing selection pruning...")

    store = _read(STORE_TS)

    assert "pruneSelection(" in store, "reloading the feed must prune the selection"
    # Removing or hiding a single conversation must also drop it, along with a stale anchor.
    assert store.count("selectedConversationIds.filter(") >= 2, (
        "removing and hiding a conversation must both prune the selection"
    )
    assert store.count("selectionAnchorId === conversationId ? null") >= 2, (
        "a range must not be able to extend from a row that has gone"
    )
    # Including the server-driven removal: a shared conversation deleted by its owner takes
    # its row away without any click, and a selection that kept the id would leave the bulk
    # bar counting a conversation that is gone.
    assert "store.selectedConversationIds.filter(" in store, (
        "removeConversationLocally must prune the selection too"
    )
    # And the resolver drops ids with no row even if pruning has not run yet.
    assert "selectedConversations(previous" in store, (
        "bulk actions must resolve ids against the loaded list"
    )

    print("  ok  the selection is pruned wherever rows can disappear")


def test_the_rail_reveals_selection_on_hover_without_a_mode():
    """The point of the redesign: no permanent chrome, no mode swap, no layout shift."""
    print("Testing the rail's selection affordance...")

    rail = _read(RAIL_TSX)

    assert 'type="checkbox"' in rail, "rows need checkboxes"
    assert "group-hover/row:opacity-100" in rail, "the checkbox must be revealed on hover"
    # A hover-only affordance is invisible to a keyboard, and absent entirely on touch.
    assert "focus-visible:opacity-100" in rail, "the checkbox must be reachable by keyboard"
    assert "pointer-coarse:opacity-100" in rail, (
        "a device with no hover must show the checkbox permanently"
    )

    # The old mode is gone: no separate selection rendering, and no Select button.
    assert "selectionMode" not in rail, "selection is no longer a mode"
    assert ">Select<" not in rail, "the permanent Select button must be gone"

    # The gutter is reserved rather than inserted, so revealing the box moves nothing.
    assert "h-4 w-4 shrink-0" in rail, "the gutter must have a fixed width"

    print("  ok  selection is hover-revealed and costs no permanent chrome")


def test_a_plain_click_still_opens_a_conversation():
    """
    The rail's primary action must not change depending on invisible state.

    Modifiers select; an unmodified click opens and drops the selection. A rail where a
    plain click sometimes opens and sometimes ticks a box is worse than one that
    occasionally loses a selection the user can see.
    """
    print("Testing click semantics...")

    rail = _read(RAIL_TSX)

    assert "selectionIntentFromEvent(event)" in rail, "clicks must read their modifiers"
    assert "intent !== 'replace'" in rail, "only modified clicks select"
    assert "clearConversationSelection();" in rail and "void selectConversation(" in rail, (
        "a plain click must clear the selection and open the conversation"
    )
    assert "event.shiftKey ? 'range' : 'toggle'" in rail, (
        "Shift held while ticking a box must still extend a range"
    )

    print("  ok  a plain click opens; modifiers select")


def test_the_bulk_bar_offers_every_action_that_makes_sense_in_bulk():
    """Pin, hide, export and delete — but not rename or share, which are single-target."""
    print("Testing the bulk bar...")

    rail = _read(RAIL_TSX)

    for action in (
        "bulkSetConversationsPinned",
        "bulkHideSelectedConversations",
        "ConversationExportDialog",
        "setPendingRemoval({ conversations: selection, bulk: true })",
    ):
        assert action in rail, f"the bulk bar must offer {action}"

    # Pin is adaptive, because a toggle over a mixed selection is ambiguous and the route
    # wants an explicit action.
    assert "pinActionFor(selection)" in rail, "the pin button must adapt to the selection"
    assert "pinAction === 'unpin' ? 'Unpin' : 'Pin'" in rail, (
        "the pin button must say which of the two it will do"
    )

    # The bar exists only while it has something to act on.
    assert "{anySelected && (" in rail, "the bulk bar must not be permanent chrome"

    # Select-all needs a real indeterminate state or a partial selection reads as none.
    assert "indeterminate = someSelected" in rail, "select-all must show a partial selection"

    print("  ok  the bulk bar offers pin, hide, export and delete only when useful")


def test_delete_is_confirmed_and_described_honestly():
    """Deleting a conversation cannot be undone, and 'delete' is sometimes a lie."""
    print("Testing delete confirmation...")

    rail = _read(RAIL_TSX)
    selection = _read(CONVERSATION_SELECTION_TS)

    assert "ConfirmDialog" in rail, "delete must be confirmed"
    # Both entry points go through the same gate, including the single-row menu that used
    # to delete immediately.
    assert "setPendingRemoval({ conversations: [target], bulk: false })" in rail, (
        "the single-row delete must be confirmed too"
    )
    assert "onRequestDelete(conversation)" in rail, (
        "the row menu must request confirmation rather than delete"
    )
    assert "removeConversation(" in rail, "confirming a single removal must still remove it"

    # The wording has to follow what will actually happen per row.
    for helper in ("summarizeRemoval", "removalTitle", "removalDescription", "removalConfirmLabel"):
        assert helper in rail and helper in selection, f"{helper} must describe the removal"
    assert "'Leave conversation'" in selection, (
        "a conversation the user can only leave must not be described as deleted"
    )

    print("  ok  both single and bulk delete confirm, and say what will really happen")


def test_the_selection_algebra_is_shared_with_the_documents_explorer():
    """Two lists with the same modifier grammar must not have two implementations of it."""
    print("Testing shared selection algebra...")

    assert LIST_SELECTION_TS.exists(), "the shared selection module must exist"
    explorer = _read(DOCUMENT_EXPLORER_TS)
    rail = _read(RAIL_TSX)
    store = _read(STORE_TS)

    assert "from './listSelection'" in explorer, (
        "the explorer must re-export the shared algebra rather than keep its own"
    )
    # Nothing may redefine it: a second copy is how the two lists drift apart.
    assert "export function applySelection" not in explorer, (
        "applySelection must have exactly one definition"
    )
    for consumer, name in ((rail, "the rail"), (store, "the store")):
        assert "lib/listSelection" in consumer or "../lib/listSelection" in consumer, (
            f"{name} must use the shared algebra"
        )

    print("  ok  one selection algebra serves both lists")


def test_a_dialog_opened_from_the_rail_escapes_its_containing_block():
    """
    A `backdrop-filter` ancestor traps `position: fixed`.

    The glass sidebar has one, so a confirmation rendered in place would be laid out against
    the 280px rail instead of the viewport. The export wizard already portals for this
    reason; the shared modal has to as well.
    """
    print("Testing dialog placement...")

    modal = _read(MODAL_TSX)
    confirm = _read(CONFIRM_TSX)

    assert "createPortal" in modal, "the shared modal must render through a portal"
    assert "document.body" in modal, "the portal must escape to the document body"
    assert "from './Modal'" in confirm, "the confirmation must use the shared shell"

    print("  ok  dialogs opened from the rail escape the rail")


def test_no_new_browser_dependency_was_introduced():
    """Browser JavaScript must stay local; nothing here may add a CDN or a package."""
    print("Testing browser assets...")

    package_json = _read(V2_DIR / "package.json")
    for forbidden in ("http://", "https://cdn", "unpkg", "jsdelivr"):
        for source in (RAIL_TSX, MODAL_TSX, CONFIRM_TSX, LIST_SELECTION_TS, CONVERSATION_SELECTION_TS):
            assert forbidden not in _read(source), f"{source.name} must not reference {forbidden}"

    # Everything used here is already a dependency: react, react-dom, clsx, lucide-react.
    for existing in ("react-dom", "lucide-react", "clsx"):
        assert f'"{existing}"' in package_json, f"{existing} should already be a dependency"

    print("  ok  no new browser dependency and no remote asset")


def test_the_typescript_logic_checks_pass():
    """Run the bundled behaviour checks, when the front-end toolchain is installed."""
    print("Testing TypeScript logic...")

    check = Path(__file__).with_name("test_v2_conversation_multiselect_logic.ts")
    assert check.exists(), "the logic check file is missing"

    if not (V2_DIR / "node_modules").exists():
        print("  --  skipped the TypeScript checks: run npm install in application/v2_ui")
        return

    # The check file lives in functional_tests/, which has no node_modules of its own, so bare
    # imports are left for node to resolve at run time from where the bundle is written.
    bundle = V2_DIR / "node_modules" / ".cache-conversation-multiselect-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(check),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                # types.ts is reached through conversationSelection.ts; anything on that path
                # that reads Vite's `import.meta.env` at module scope has no such object under
                # node, so it is defined away. Nothing under test consults it.
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


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_the_bulk_routes_the_client_calls_exist,
    test_the_request_bodies_match_what_the_routes_read,
    test_the_routes_are_still_personal_only,
    test_a_shared_conversation_never_reaches_a_bulk_route,
    test_removing_a_shared_conversation_picks_delete_or_leave,
    test_the_confirmation_and_the_request_cannot_disagree,
    test_a_batch_does_not_abandon_itself_on_one_failure,
    test_the_selection_cannot_outlive_the_rows_it_names,
    test_the_rail_reveals_selection_on_hover_without_a_mode,
    test_a_plain_click_still_opens_a_conversation,
    test_the_bulk_bar_offers_every_action_that_makes_sense_in_bulk,
    test_delete_is_confirmed_and_described_honestly,
    test_the_selection_algebra_is_shared_with_the_documents_explorer,
    test_a_dialog_opened_from_the_rail_escapes_its_containing_block,
    test_no_new_browser_dependency_was_introduced,
    test_the_typescript_logic_checks_pass,
]


def main():
    print("Testing V2 conversation multi-select...\n")
    failed = []

    for test in TESTS:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"  FAIL  {test.__name__}: {exc}")
        print()

    passed = len(TESTS) - len(failed)
    print(f"{passed}/{len(TESTS)} tests passed")
    for name in failed:
        print(f"Failed: {name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
