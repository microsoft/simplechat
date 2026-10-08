#!/usr/bin/env python3
# test_v2_m365_pending_actions.py
"""
Functional test for Microsoft 365 pending-action cards in the V2 chat.

Version: 0.261.307
Implemented in: 0.261.307

A Microsoft 365 action the assistant saves for review (an email or a calendar change waiting
behind Send, Send now and Cancel) used to be drawn only by the classic chat page. V2 sent every
notice about one to `/chats`, which is a dead end once the administrator turns on New UI only:
a person who is not an administrator cannot open a classic page at all.

The cards are now drawn by the V2 chat itself:

  - one shared `PendingActionCard`, used by the Approvals page and by the chat, so the two can
    never disagree about what a saved action is allowed to do;
  - one `m365PendingActionsStore`, which owns every card's state (the saved action, the versions
    it has already moved past, what is being sent) and is the only thing that talks to the server;
  - placement that matches classic: under the reply that saved the action (live while the reply
    streams), and in a conversation section for actions no reply on screen accounts for;
  - a read of the conversation's list whenever a reply ends (finishes, fails, is stopped, or was
    picked up again), because a reply can save an action its own stream never described; and
  - notices that open the V2 chat with the card named, so the thread scrolls to it and
    highlights it once.

This test ensures those pieces stay wired together and runs the Node runtime tests that execute
the real modules: the pure rules, the store, and the live paths (the stream reader, a real send,
shared-conversation events and the notification hand-off). No backend change was needed, and
none is made.
"""

import importlib.util
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

IMPLEMENTED_IN = "0.261.307"

HELPERS_MODULE = V2_SRC / "lib" / "m365PendingActions.ts"
STORE_MODULE = V2_SRC / "stores" / "m365PendingActionsStore.ts"
CARD_COMPONENT = V2_SRC / "components" / "approvals" / "PendingActionCard.tsx"
PANEL_COMPONENT = V2_SRC / "components" / "approvals" / "PendingActionsPanel.tsx"
SLOTS_COMPONENT = V2_SRC / "components" / "chat" / "PendingActionSlots.tsx"
MESSAGE_LIST = V2_SRC / "components" / "chat" / "MessageList.tsx"
CHAT_STORE = V2_SRC / "stores" / "chatStore.ts"
CHAT_PAGE = V2_SRC / "pages" / "ChatPage.tsx"
SSE_MODULE = V2_SRC / "lib" / "sse.ts"
COLLABORATION_EVENTS = V2_SRC / "lib" / "collaborationEvents.ts"
CONVERSATION_URL = V2_SRC / "lib" / "conversationUrl.ts"
NOTIFICATION_LINKS = V2_SRC / "lib" / "notificationLinks.ts"
NOTIFICATION_NAVIGATION = V2_SRC / "lib" / "notificationNavigation.ts"
APPROVALS_API = V2_SRC / "lib" / "approvalsApi.ts"
M365_RUNTIME = APP_DIR / "functions_m365_runtime.py"
XSS_CHECKER_FILE = REPO_ROOT / "scripts" / "check_xss_sinks.py"

LOGIC_TEST = REPO_ROOT / "functional_tests" / "test_v2_m365_pending_actions_logic.mjs"
STORE_TEST = REPO_ROOT / "functional_tests" / "test_v2_m365_pending_actions_store.mjs"
STREAM_TEST = REPO_ROOT / "functional_tests" / "test_v2_m365_pending_actions_stream.mjs"
NODE_MODULES = REPO_ROOT / "application" / "v2_ui" / "node_modules"

NEW_FILES = (
    HELPERS_MODULE,
    STORE_MODULE,
    CARD_COMPONENT,
    SLOTS_COMPONENT,
    LOGIC_TEST,
    STORE_TEST,
    STREAM_TEST,
)

# What the Approvals page's tests and the browser tests look for. The card moved out of the
# panel, so these have to travel with it.
CARD_TEST_IDS = (
    "v2-pending-action-card",
    "v2-pending-action-status",
    "v2-pending-action-body",
    "v2-pending-action-countdown",
    "v2-pending-action-controls",
    "v2-pending-action-send",
    "v2-pending-action-cancel",
)

PENDING_ACTION_PARAM = "m365_pending_action"


def _read(path):
    if not path.exists():
        raise AssertionError(f"Expected file is missing: {path}")
    return path.read_text(encoding="utf-8", errors="ignore")


def _strip_comments(source):
    """Source without block and line comments, so a comment explaining a rule cannot satisfy it."""
    return re.sub(r"/\*[\s\S]*?\*/|(?<![:\"'`])//.*", "", source)


def test_new_modules_and_tests_exist():
    """The feature is a handful of files; losing one of them loses a whole layer."""
    print("Testing that the new files exist...")
    for path in NEW_FILES:
        if not path.exists():
            raise AssertionError(f"Expected file is missing: {path.relative_to(REPO_ROOT)}")
    print(f"  All {len(NEW_FILES)} new files are present.")
    print("File presence test passed!")
    return True


def test_one_card_serves_the_approvals_page_and_the_chat():
    """Two copies of the card would drift apart on what a saved action may do."""
    print("Testing that the card is shared...")
    card_source = _read(CARD_COMPONENT)
    panel_source = _read(PANEL_COMPONENT)
    slots_source = _read(SLOTS_COMPONENT)

    if "export function PendingActionCard" not in card_source:
        raise AssertionError("The shared PendingActionCard is not exported.")
    if "PendingActionCard" not in panel_source:
        raise AssertionError("The Approvals panel does not use the shared card.")
    if "PendingActionCard" not in slots_source:
        raise AssertionError("The chat thread does not use the shared card.")
    print("  The panel and the thread both draw the shared card.")

    for test_id in CARD_TEST_IDS:
        if f'data-testid="{test_id}"' not in card_source:
            raise AssertionError(f"The shared card lost the {test_id} test id.")
    print("  The card keeps the test ids the Approvals page was tested with.")

    # The panel is a thin wrapper now: it must not grow its own send/cancel path back, or the
    # two surfaces stop agreeing about what happens after Send.
    for call in ("submitPendingAction(", "cancelPendingAction(", "sendPendingActionNow("):
        if call in _strip_comments(panel_source):
            raise AssertionError(
                f"The Approvals panel calls {call} itself instead of going through the store."
            )
    print("  The panel has no send or cancel path of its own.")

    print("Shared card test passed!")
    return True


def test_the_chat_thread_places_cards_like_classic():
    """Under the reply that saved the action, live while it streams, and a section for the rest."""
    print("Testing card placement in the thread...")
    list_source = _read(MESSAGE_LIST)
    slots_source = _read(SLOTS_COMPONENT)
    store_source = _read(STORE_MODULE)

    for name in (
        "PendingActionPlacementProvider",
        "InlinePendingActions",
        "StreamingPendingActions",
        "PendingActionsConversationSection",
    ):
        if f"{name}" not in list_source:
            raise AssertionError(f"MessageList.tsx does not render {name}.")
        if f"export function {name}" not in slots_source:
            raise AssertionError(f"PendingActionSlots.tsx does not export {name}.")
    print("  The thread renders the inline, streaming and conversation-level slots.")

    if "<InlinePendingActions anchor={message.id} />" not in list_source:
        raise AssertionError("A finished message does not offer its own cards a slot.")
    print("  Every message offers its own cards a slot.")

    # The module-level store is what the chat page uses; the Approvals page builds its own
    # through the factory so the two never share a conversation filter.
    if "export const chatPendingActionsStore" not in store_source:
        raise AssertionError("The chat's pending-action store is not exported.")
    if "export function createPendingActionsStore" not in store_source:
        raise AssertionError("The store factory the Approvals page uses is not exported.")
    print("  The chat and the Approvals page use separate stores.")

    print("Placement test passed!")
    return True


def test_a_failed_reply_still_shows_the_action_it_saved():
    """A run can fail after saving an action; hiding that card would leave it unsent and unseen."""
    print("Testing the stream ordering...")
    sse_source = _read(SSE_MODULE)
    chat_store_source = _read(CHAT_STORE)
    events_source = _read(COLLABORATION_EVENTS)

    handler = "if (carriesPendingActions(event)) handlers.onM365PendingActions?.(event);"
    error_check = "if (event.error || event.auth_required === true) {"
    if handler not in sse_source or error_check not in sse_source:
        raise AssertionError("sse.ts no longer has the pending-action report or the error check.")
    if sse_source.index(handler) > sse_source.index(error_check):
        raise AssertionError(
            "sse.ts reports saved actions after the error check, so a reply that fails after "
            "saving an action never shows it."
        )
    print("  Saved actions are reported before the error check.")

    # A refused request (HTTP 500) is read through a different path from a stream frame.
    refused = sse_source.index("if (carriesPendingActions(event)) handlers.onM365PendingActions?.(event);", sse_source.index(handler) + 1)
    if "captureError(" not in sse_source[refused : refused + 400]:
        raise AssertionError("A refused request no longer reports its actions before its error.")
    print("  A refused request reports its actions before its error too.")

    # Reported against the conversation on screen, not the frame's own id: a shared conversation's
    # frames can carry the id of the hidden source conversation.
    if chat_store_source.count("onM365PendingActions:") < 2:
        raise AssertionError(
            "chatStore.ts does not wire onM365PendingActions for both the reply stream and "
            "the shared-conversation events."
        )
    if "handleStreamPayload(event, {" not in chat_store_source:
        raise AssertionError("The reply stream does not hand saved actions to the store.")
    print("  The reply stream and the shared-conversation events both reach the store.")

    if "collaboration.m365.pending_action" not in events_source:
        raise AssertionError("The collaboration events no longer carry pending-action announcements.")
    print("  Shared conversations are told to read the list again.")

    print("Stream ordering test passed!")
    return True


def _slice(source, start, end):
    """Comment-free source from one anchor to the next, failing loudly when either has moved."""
    begin = source.find(start)
    if begin < 0:
        raise AssertionError(f"chatStore.ts no longer contains {start!r}.")
    finish = source.find(end, begin + len(start))
    if finish < 0:
        raise AssertionError(f"chatStore.ts no longer has {end!r} after {start!r}.")
    return _strip_comments(source[begin:finish])


def test_a_reply_that_ends_reads_the_saved_actions_again():
    """A reply can save an action its own stream never described; only the list knows."""
    print("Testing the read after a reply...")
    source = _read(CHAT_STORE)

    helper = _slice(source, "function refreshPendingActionsAfterReply(", "\n}\n")
    if "pendingActions.conversationId !== conversationId" not in helper:
        raise AssertionError(
            "The read after a reply no longer checks the reader is still in that conversation, "
            "so it would read the list of whatever thread is on screen."
        )
    if "pendingActions.refreshList()" not in helper:
        raise AssertionError("The read after a reply no longer reads the conversation's list.")
    print("  The read is skipped when the reader has moved on.")

    # Each ending the classic client reads after: a reply that finishes or fails, one picked up
    # again after the reader was away, and one the reader stops.
    sent = _slice(source, "async function runChatStream(", "async function resumeChatStream(")
    if "if (ownsController()) {" not in sent or "refreshPendingActionsAfterReply(conversationId)" not in sent:
        raise AssertionError("A reply that ends does not read the saved actions again.")
    if sent.index("if (ownsController()) {") > sent.index("refreshPendingActionsAfterReply("):
        raise AssertionError("The read after a reply runs even when a newer send owns the screen.")
    print("  A reply that finishes or fails reads the list again.")

    resumed = _slice(source, "async function resumeChatStream(", "\n/**")
    if "if (isCurrent()) {" not in resumed or "refreshPendingActionsAfterReply(conversationId)" not in resumed:
        raise AssertionError("A reply picked up again does not read the saved actions when it ends.")
    if resumed.index("if (isCurrent()) {") > resumed.index("refreshPendingActionsAfterReply("):
        raise AssertionError("The read after a picked-up reply runs after the reader left it.")
    print("  A reply picked up again reads the list when it ends.")

    stopped = _slice(source, "stopStreaming: () => {", "setDrawerMode:")
    if "const stoppedConversationId = streamingConversationId" not in stopped:
        raise AssertionError("Stop no longer remembers which conversation it stopped.")
    if stopped.index("stoppedConversationId = streamingConversationId") > stopped.index("detachActiveStream()"):
        raise AssertionError(
            "Stop reads the conversation after detaching, when detaching has already forgotten it."
        )
    if ".then(() => refreshPendingActionsAfterReply(stoppedConversationId))" not in stopped:
        raise AssertionError("A reply the reader stops does not read the saved actions afterwards.")
    print("  A stopped reply reads the list once the server has the stop request.")

    print("Read after a reply test passed!")
    return True


def test_a_detached_reply_is_no_longer_a_live_turn():
    """Left registered, the next send would take the stopped reply's turn for a renamed one."""
    print("Testing that detaching clears the live turn...")
    source = _read(CHAT_STORE)

    detach = _slice(source, "function detachActiveStream(): void {", "\n}\n")
    if "chatPendingActionsStore.getState().setLiveStream(null)" not in detach:
        raise AssertionError(
            "detachActiveStream no longer clears the pending-action store's live stream, so a "
            "message sent after Stop pulls the stopped reply's saved actions onto the new turn."
        )
    print("  Stopping or leaving a reply clears the turn its saved actions were drawn under.")

    print("Detached reply test passed!")
    return True


def test_notices_open_the_v2_chat_with_the_card_named():
    """Notices that opened classic /chats are dead ends under New UI only."""
    print("Testing notification routing...")
    links_source = _read(NOTIFICATION_LINKS)
    navigation_source = _read(NOTIFICATION_NAVIGATION)
    url_source = _read(CONVERSATION_URL)
    page_source = _read(CHAT_PAGE)

    code = _strip_comments(links_source)
    if f"searchParams.has('{PENDING_ACTION_PARAM}')" in code:
        raise AssertionError(
            "notificationLinks.ts still branches on the pending-action parameter, which is how "
            "notices were sent to the classic chat page."
        )
    if re.search(r"classic\(\s*`/chats", code):
        raise AssertionError("notificationLinks.ts still opens a classic /chats page.")
    print("  No notice about a saved action is sent to the classic chat page.")

    if "readPendingActionFocus(url.searchParams)" not in links_source:
        raise AssertionError("The notice resolver does not read the saved action's id.")
    if "pendingActionId" not in navigation_source:
        raise AssertionError("The navigation does not carry the saved action to the chat.")
    if "requestFocus(pendingActionId, conversationId)" not in navigation_source:
        raise AssertionError("Following a notice on the chat page does not ask for the card.")
    if "chatHrefForPendingAction(conversationId, pendingActionId)" not in navigation_source:
        raise AssertionError("Following a notice from another page does not name the card.")
    print("  The chat is opened with the card named, from the chat page or from any other.")

    if f"M365_PENDING_ACTION_PARAM = '{PENDING_ACTION_PARAM}'" not in url_source:
        raise AssertionError("The V2 address parameter is not named like the one the server writes.")
    if "readPendingActionFocus" not in page_source:
        raise AssertionError("The chat page does not read the card named in its address.")
    print("  The chat page reads the card out of its address and the address is then cleaned up.")

    print("Notification routing test passed!")
    return True


def test_the_server_writes_the_link_parameter_the_client_reads():
    """The notice's link comes from the backend; the two ends have to agree on its name."""
    print("Testing the link parameter...")
    runtime_source = _read(M365_RUNTIME)
    if f"'{PENDING_ACTION_PARAM}': action['id']" not in runtime_source:
        raise AssertionError(
            f"functions_m365_runtime.py no longer writes the {PENDING_ACTION_PARAM} link "
            "parameter the V2 client reads."
        )
    if "/chats?" not in runtime_source:
        raise AssertionError("The notice link no longer points at /chats, which V2 maps to its chat.")
    print(f"  The server writes {PENDING_ACTION_PARAM} and the V2 client reads the same name.")
    print("Link parameter test passed!")
    return True


def test_the_conversation_can_be_listed_without_a_backend_change():
    """The list the chat reads already existed; asking it about one conversation is a query."""
    print("Testing the conversation list request...")
    api_source = _read(APPROVALS_API)
    if "export async function fetchConversationPendingActions" not in api_source:
        raise AssertionError("There is no request for one conversation's saved actions.")
    if "conversation_id=" not in api_source and "conversation_id" not in api_source:
        raise AssertionError("The request does not scope the list to a conversation.")
    if "Outgoing actions could not be verified." not in api_source:
        raise AssertionError(
            "A list the server could not verify is not reported, so an unverifiable list would "
            "read as an empty one."
        )
    print("  The list is scoped to the conversation and an unverifiable list is an error.")
    print("Conversation list test passed!")
    return True


def _load_xss_checker():
    spec = importlib.util.spec_from_file_location("check_xss_sinks_for_m365_cards", XSS_CHECKER_FILE)
    if spec is None or spec.loader is None:
        raise AssertionError("Expected a module spec for check_xss_sinks.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_no_html_sink_or_remote_asset_was_introduced():
    """Saved actions carry model-written text; none of it may be rendered as HTML."""
    print("Testing rendering safety...")
    remote_pattern = re.compile(r"https?://(?!localhost)[^\s'\"`)]+", re.I)

    for path in (HELPERS_MODULE, STORE_MODULE, CARD_COMPONENT, SLOTS_COMPONENT, PANEL_COMPONENT):
        source = _read(path)
        for sink in ("dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML"):
            if sink in source:
                raise AssertionError(f"{path.relative_to(REPO_ROOT)} uses {sink}.")
        for match in remote_pattern.finditer(source):
            raise AssertionError(f"{path.relative_to(REPO_ROOT)} references a remote URL: {match.group(0)}")
    print("  No HTML sink and no remote URL in the new modules.")

    checker = _load_xss_checker()
    if "chatHrefForPendingAction" not in checker.TS_SAME_ORIGIN_URL_BUILDERS:
        raise AssertionError(
            "chatHrefForPendingAction is not an approved same-origin URL builder, so the card's "
            "Open conversation link fails the XSS sink check."
        )
    for path in (
        HELPERS_MODULE,
        STORE_MODULE,
        CARD_COMPONENT,
        PANEL_COMPONENT,
        SLOTS_COMPONENT,
        CONVERSATION_URL,
        NOTIFICATION_LINKS,
        NOTIFICATION_NAVIGATION,
        SSE_MODULE,
        COLLABORATION_EVENTS,
        APPROVALS_API,
    ):
        issues = checker.inspect_file(path)
        if issues:
            raise AssertionError(
                f"{path.relative_to(REPO_ROOT)} fails the XSS sink check: "
                + "; ".join(checker.format_error_annotation(issue) for issue in issues)
            )
    print("  Every touched file passes the XSS sink checker in full.")
    print("Rendering safety test passed!")
    return True


def _run_node_test(path):
    """Execute one of the Node runtime tests, reporting its result."""
    if not path.exists():
        raise AssertionError(f"The runtime test is missing: {path}")

    if not (NODE_MODULES / "zustand").exists():
        print("  application/v2_ui/node_modules is not installed; skipping the runtime test.")
        print("  Install it with: npm ci --prefix application/v2_ui")
        return True

    node = shutil.which("node")
    if not node:
        print("  Node is not installed; skipping the runtime test.")
        print(f"  Run it with: node {path.relative_to(REPO_ROOT)}")
        return True

    completed = subprocess.run(
        [node, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )
    output = (completed.stdout or "") + (completed.stderr or "")

    # Node below 22.6 cannot import TypeScript directly. That is a limitation of the
    # environment, not a defect in the code under test.
    if completed.returncode != 0 and "Unknown file extension" in output:
        print("  This Node cannot import TypeScript directly (needs 22.6 or newer); skipping.")
        return True

    if completed.returncode != 0:
        print(output)
        raise AssertionError(f"{path.name} failed; see the output above.")

    # A file that registered no tests exits cleanly too, so the count has to be positive.
    passed = re.search(r"(?m)^.{0,3}pass (\d+)\s*$", output)
    failed = re.search(r"(?m)^.{0,3}fail (\d+)\s*$", output)
    if passed is None or failed is None:
        raise AssertionError(f"{path.name} printed no test summary:\n{output}")
    if int(passed.group(1)) < 1 or int(failed.group(1)) != 0:
        print(output)
        raise AssertionError(
            f"{path.name} reported {passed.group(1)} passing and {failed.group(1)} failing tests."
        )

    print(f"  {path.name}: {passed.group(1)} tests passed.")
    return True


def test_pure_rules_behave():
    """Run the runtime checks for placement, staleness, countdowns, links and notices.

    The assertions above prove the pieces are wired together. They cannot prove that an older
    snapshot is ignored or that an unsafe link is refused, so the companion Node test executes
    the real modules.
    """
    print("Testing the pure rules...")
    return _run_node_test(LOGIC_TEST)


def test_store_behaves():
    """Run the runtime checks for the store: what Send, Send now and Cancel do to a card.

    Sending the wrong version of an action, or sending twice, cannot be undone: the email is
    delivered. Neither is visible from the source.
    """
    print("Testing the store...")
    return _run_node_test(STORE_TEST)


def test_the_live_paths_behave():
    """Run the runtime checks for the stream, a real send, shared events and notice hand-off."""
    print("Testing the live paths...")
    return _run_node_test(STREAM_TEST)


def test_version_was_incremented():
    """The application version records when this shipped."""
    print("Testing version...")
    version = assert_app_version_at_least(
        IMPLEMENTED_IN,
        reason="V2 chat renders Microsoft 365 pending-action cards.",
    )
    print(f"  config.py VERSION is {version}.")
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_new_modules_and_tests_exist,
        test_one_card_serves_the_approvals_page_and_the_chat,
        test_the_chat_thread_places_cards_like_classic,
        test_a_failed_reply_still_shows_the_action_it_saved,
        test_a_reply_that_ends_reads_the_saved_actions_again,
        test_a_detached_reply_is_no_longer_a_live_turn,
        test_notices_open_the_v2_chat_with_the_card_named,
        test_the_server_writes_the_link_parameter_the_client_reads,
        test_the_conversation_can_be_listed_without_a_backend_change,
        test_no_html_sink_or_remote_asset_was_introduced,
        test_pure_rules_behave,
        test_store_behaves,
        test_the_live_paths_behave,
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
