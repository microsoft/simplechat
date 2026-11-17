#!/usr/bin/env python3
# test_v2_user_agreement_gate.py
"""
Functional test for the V2 user agreement gate.
Version: 0.261.445
Implemented in: 0.261.445

An administrator can require a user agreement before files are uploaded
(``enable_user_agreement``). Classic enforces it in the browser through
``static/js/user-agreement.js``; no upload route enforces it. V2 had only the administrator's
preview, so a V2 user could upload without ever seeing the agreement. V2 now asks before every
upload it makes.

These checks pin what the gate relies on:

- the client calls the same two routes with the parameters and workspace names the route reads, and
  names a workspace exactly as classic's call sites do, so an acceptance made in either interface counts
  for once-a-day acceptance in the other;
- every place V2 sends a user's file to the server is gated, and a new one cannot be added without a
  deliberate decision: the multipart senders are listed, each as gated or as exempt with its reason;
- the gate runs after the checks that refuse a file and before anything is sent;
- while a file waits on the agreement it has no chip, so the chat composer holds Enter and Send, and the
  elicitation card holds Next, Review answers, Use these answers and Enter, from the gate's `pending` flag, which
  the hook raises only for a gate that needs the check and lowers on every way it ends; the one other component
  that renders the shared editor cannot upload, so it can never reach the gate;
- a check or an acceptance that never answers fails after one named limit of twenty seconds, through the failure
  path every other failure takes;
- the dialog renders the agreement without raw HTML, with the shared modal's focus handling;
- the TypeScript logic (scope naming, when to ask, how an answer is read, what the routes are sent, the time
  limit, and the hook's `pending` semantics, run on a small hooks runtime) passes, executed with the esbuild
  Vite already brings in.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
ROUTE_FILE = APP_ROOT / "route_backend_user_agreement.py"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_user_agreement_gate_logic.ts"

CLIENT_TS = V2_SRC / "lib" / "userAgreement.ts"
HOOK_TS = V2_SRC / "lib" / "useUserAgreementGate.ts"
DIALOG_TSX = V2_SRC / "components" / "ui" / "UserAgreementDialog.tsx"
COMPOSER_TSX = V2_SRC / "components" / "chat" / "ComposerEditor.tsx"
CHAT_COMPOSER_TSX = V2_SRC / "components" / "chat" / "Composer.tsx"
ELICITATION_TSX = V2_SRC / "components" / "chat" / "ElicitationCard.tsx"
ASSIST_THREAD_TSX = V2_SRC / "components" / "chat" / "AssistThread.tsx"
EXPLORER_TSX = V2_SRC / "components" / "documents" / "DocumentExplorer.tsx"
FEATURE_DOC = REPO_ROOT / "docs" / "explanation" / "features" / "V2_USER_AGREEMENT_GATE.md"
MINI_REACT_HOOKS_TS = Path(__file__).resolve().parent / "test_support" / "miniReactHooks.ts"

# The components a person works in where a file is handed to the server. Each must use the gate. Keys are
# paths relative to application/v2_ui/src.
GATED_ENTRY_POINTS = {
    # The attach button, paste, drop and retry all reach POST /upload through here.
    "components/chat/ComposerEditor.tsx": "chat uploads (POST /upload)",
    # The Upload command, file input and drop region reach the workspace upload routes through here, for
    # personal, group and public scope.
    "components/documents/DocumentExplorer.tsx": "workspace documents (personal, group and public)",
}
# The modules that build the multipart body for those uploads. Reaching them is not itself an entry point.
UPLOAD_TRANSPORT = {
    "lib/endpoints.ts": "defines uploadDocument (chat) and uploadPersonalDocuments",
    "lib/documentOperations.ts": "the explorer's operation adapters (personal, group, public)",
    "lib/apiClient.ts": "defines uploadFile and uploadFileWithStatus",
}
# Multipart bodies that are not a user's document or chat upload. Classic does not gate any of these.
EXEMPT_MULTIPART_SENDERS = {
    "components/admin/BrandingImageField.tsx": "administrator branding image (logo, favicon)",
    "lib/workspaceActionConnectors.ts": "OpenAPI specification uploaded while configuring an action",
    "lib/groupSettings.ts": "group or public workspace logo in workspace settings",
    "lib/voice.ts": "recorded speech sent for transcription, not a stored file",
    "components/chat/CredentialRequestCard.tsx": "form fields read from a credential prompt, no file",
}
# What a module that builds a multipart body contains. A module that does and is in neither table above
# fails the test until someone decides which it is.
MULTIPART_MARKERS = ("FormData(", "uploadFile<", "uploadFileWithStatus<")
# The markup sinks the new files must not use. The names are the subject of the assertion, not a use of them.
RAW_HTML_SINKS = ("dangerouslySetInnerHTML", "innerHTML")  # xss-check: ignore - names the sinks the test forbids
# Callers of the functions that send a chat or workspace file; anything else that starts calling them is a
# new entry point. `uploadFilesToChat` is exported but nothing calls it, so it is not one yet.
GATE_DEFINITION_FILES = {
    "lib/userAgreement.ts", "lib/useUserAgreementGate.ts", "components/ui/UserAgreementDialog.tsx",
}
# Every component that renders the shared editor, and what holds its own Send, submit or Next control while a
# file waits on the agreement (it has no chip until the gate settles, so nothing else shows it is coming).
# A component that wires `onAgreementPendingChange` is held; one that cannot upload needs nothing.
COMPOSER_EDITOR_CONSUMERS = {
    "components/chat/Composer.tsx": "held: uploadsBlocked includes the flag, so Enter and both Send paths wait",
    "components/chat/ElicitationCard.tsx": "held: canAdvance and canFinish include the flag, so Next, Review answers, "
                                           "Use these answers and Enter wait",
    "components/chat/AssistThread.tsx": "restricted editor: uploads are off, so no file ever waits",
}
# The consumers that do not wire the flag, each justified above. Wiring one means deleting its entry here.
COMPOSER_EDITOR_UNHELD = {"components/chat/AssistThread.tsx"}


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def _v2_sources():
    for path in sorted(V2_SRC.rglob("*")):
        if path.suffix in (".ts", ".tsx") and path.is_file():
            yield path.relative_to(V2_SRC).as_posix(), path


def _segment(source, start, end):
    """The text from one marker up to the next, so an ordering check stays inside one function."""
    first = source.index(start)
    return source[first:source.index(end, first + len(start))]


def _positions(source, markers, where):
    """Where each marker sits, refusing a missing one with a sentence that says what went wrong."""
    positions = []
    for marker in markers:
        position = source.find(marker)
        assert position >= 0, (
            f"{where} no longer contains {marker!r}. The user agreement gate must stay in front of the upload, "
            "after the checks that refuse a file."
        )
        positions.append(position)
    assert positions == sorted(positions), f"{where} is out of order: {dict(zip(markers, positions))}"
    return positions


def test_version_is_at_least_the_implementing_release():
    """The application carries at least the version the V2 gate arrived in."""
    print("Testing the application version...")
    assert_app_version_at_least("0.261.445")


def test_the_client_calls_the_routes_with_the_names_the_route_reads():
    """Paths, methods, parameter and body names, workspace types and answer fields come from the route."""
    print("\nTesting the client against the route source...")
    route = _read(ROUTE_FILE)
    client = _read(CLIENT_TS)

    routes = dict(
        (path, method)
        for path, method in re.findall(r'@bp\.route\("([^"]+)", methods=\["([A-Z]+)"\]\)', route)
    )
    check_path = re.search(r"USER_AGREEMENT_CHECK_PATH = '([^']+)'", client).group(1)
    accept_path = re.search(r"USER_AGREEMENT_ACCEPT_PATH = '([^']+)'", client).group(1)
    assert routes.get(check_path) == "GET", routes
    assert routes.get(accept_path) == "POST", routes
    assert "method: 'GET'" in client and "method: 'POST'" in client

    read_arguments = set(re.findall(r'request\.args\.get\("([a-z_]+)"', route))
    sent_query = set(re.findall(r"^\s+(workspace_type|workspace_id|action_context):", _segment(
        client, "export function userAgreementCheckPath", "export function userAgreementAcceptBody",
    ), re.MULTILINE))
    assert read_arguments == sent_query == {"workspace_id", "workspace_type", "action_context"}, (
        read_arguments, sent_query,
    )
    read_body = set(re.findall(r'data\.get\("([a-z_]+)"', route))
    sent_body = set(re.findall(r"^\s+(workspace_type|workspace_id|action_context):", _segment(
        client, "export function userAgreementAcceptBody", "export function userAgreementSwitchedOn",
    ), re.MULTILINE))
    assert read_body == sent_body == {"workspace_id", "workspace_type", "action_context"}, (read_body, sent_body)

    route_types = set(re.findall(r'"([a-z]+)"', re.search(r"valid_types = \[([^\]]+)\]", route).group(1)))
    client_types = set(re.findall(r"'([a-z]+)'", re.search(
        r"export type UserAgreementWorkspaceType =([^;]+);", client,
    ).group(1)))
    assert route_types == client_types == {"personal", "group", "public", "chat"}, (route_types, client_types)

    # The answer fields the route sends are the ones the client reads, and its default action context is
    # the one the route defaults to.
    for field in ("needsAgreement", "agreementText", "enableDailyAcceptance"):
        assert f'"{field}"' in route and f"payload.{field}" in client, field
    assert '"success"' in route and "payload.success !== true" in client
    assert 'request.args.get("action_context", "file_upload")' in route
    assert "USER_AGREEMENT_ACTION_CONTEXT = 'file_upload'" in client

    print("  The client and the route agree.")


def test_v2_names_workspaces_exactly_as_classics_call_sites_do():
    """Once-a-day acceptance is keyed by type and workspace id, so both interfaces must send the same pair."""
    print("\nTesting workspace naming against classic's call sites...")
    static_js = APP_ROOT / "static" / "js"
    classic = {
        "chat": (_read(static_js / "chat" / "chat-input-actions.js"), r'"chat",\s*"default"'),
        "personal": (_read(static_js / "workspace" / "workspace-documents.js"), r"'personal',\s*'default'"),
        "group": (_read(APP_ROOT / "templates" / "group_workspaces.html"), r"'group',\s*activeGroupId"),
        "public": (_read(static_js / "public" / "public_workspace.js"), r"'public',\s*activePublicId"),
    }
    for scope, (source, pattern) in classic.items():
        assert re.search(pattern, source), f"classic no longer passes {pattern} for {scope} uploads"
    classic_manager = _read(static_js / "user-agreement.js")
    assert classic_manager.count("workspaceId || 'default'") == 2, "classic's fallback workspace id changed"
    assert classic_manager.count("action_context: 'file_upload'") == 2

    client = _read(CLIENT_TS)
    assert "USER_AGREEMENT_DEFAULT_WORKSPACE_ID = 'default'" in client
    assert "CHAT_AGREEMENT_SCOPE" in client and "{ type: 'chat' }" in client
    composer = _read(COMPOSER_TSX)
    assert composer.count("CHAT_AGREEMENT_SCOPE") >= 3, "Every chat gate must name the chat scope"
    explorer = _read(EXPLORER_TSX)
    assert "workspaceAgreementScope(captured.adapter.scope)" in explorer, (
        "The explorer must ask about the workspace its own adapter uploads to"
    )
    print("  Chat, personal, group and public scopes are named as classic names them.")


def test_every_multipart_sender_is_gated_transport_or_explained():
    """A module that builds a multipart body must be a known entry point, transport, or an exempt sender."""
    print("\nTesting the multipart senders...")
    builders = set()
    for relative, path in _v2_sources():
        if relative in GATE_DEFINITION_FILES:
            continue
        source = path.read_text(encoding="utf-8")
        if any(marker in source for marker in MULTIPART_MARKERS):
            builders.add(relative)
    known = set(UPLOAD_TRANSPORT) | set(EXEMPT_MULTIPART_SENDERS)
    unknown = sorted(builders - known)
    assert not unknown, (
        f"{unknown} build a multipart body and are not classified. If one uploads a user's file, gate its "
        "caller with useUserAgreementGate and list the module in UPLOAD_TRANSPORT; if it does not, justify it "
        "in EXEMPT_MULTIPART_SENDERS."
    )
    stale = sorted(known - builders)
    assert not stale, f"{stale} no longer build a multipart body; remove them from the tables"
    print("  Every multipart sender is classified.")


def test_only_the_gated_components_start_a_chat_or_workspace_upload():
    """Who calls the functions that send a user's file, and that each of those callers uses the gate."""
    print("\nTesting who starts an upload...")
    # `(?<!function )` leaves out the definitions; the rest are calls.
    senders = {
        "uploadDocument": r"(?<!function )(?<![\w.])uploadDocument\(",
        "uploadFilesToChat": r"(?<!function )(?<![\w.])uploadFilesToChat\(",
        "uploadPersonalDocuments": r"(?<!function )(?<![\w.])uploadPersonalDocuments\(",
        "adapter.upload": r"adapter\.upload\(",
    }
    callers = {name: {} for name in senders}
    for relative, path in _v2_sources():
        source = path.read_text(encoding="utf-8")
        for name, pattern in senders.items():
            count = len(re.findall(pattern, source))
            if count:
                callers[name][relative] = count

    # The composer reaches the chat route through its own queue; chatUploads.ts keeps a wrapper that
    # nothing calls. The explorer's adapters reach the personal route and the native routes.
    assert callers["uploadDocument"] == {"components/chat/ComposerEditor.tsx": 1, "lib/chatUploads.ts": 1}, callers
    assert callers["uploadFilesToChat"] == {}, (
        "uploadFilesToChat sends a file without asking about the agreement and now has a caller; gate that "
        f"caller with useUserAgreementGate first: {callers['uploadFilesToChat']}"
    )
    assert callers["uploadPersonalDocuments"] == {"lib/documentOperations.ts": 1}, callers
    assert callers["adapter.upload"] == {"components/documents/DocumentExplorer.tsx": 1}, callers

    for relative in GATED_ENTRY_POINTS:
        source = _read(V2_SRC / relative)
        assert "useUserAgreementGate()" in source, f"{relative} must use the gate"
        assert "<UserAgreementDialog gate={agreementGate} />" in source, f"{relative} must render the dialog"
    print("  Only the two gated components start an upload.")


def test_the_chat_composer_asks_before_it_attaches_or_sends_anything():
    """Attach, paste, drop and retry: the gate is in front of the queue, and after the checks that refuse a file."""
    print("\nTesting the chat composer's gate...")
    source = _read(COMPOSER_TSX)

    enqueue = _segment(source, "const enqueueSelectedFiles = async", "const onSelectFiles = async")
    _positions(enqueue, [
        "if (disabled || !uploadsEnabled)",
        "referenceUploadValidationError(file)",
        "agreementGate.confirm(CHAT_AGREEMENT_SCOPE, sendable)",
        "currentOwner.current !== gatedOwner",
        "files.current.set(upload.id, file)",
        "queueUpload(item.upload",
    ], "enqueueSelectedFiles")
    assert "retryFileId.current = null;\n            return;" in enqueue, "Cancelling must end a retry-by-picker"

    retry = _segment(source, "const retryUpload = (upload", "const removeUpload = (localId")
    _positions(retry, [
        "referenceUploadValidationError(file)",
        "agreementRetries.current.has(upload.id)",
        "agreementGate.withAgreement(CHAT_AGREEMENT_SCOPE, [file]",
        "currentOwner.current !== gatedOwner",
        "queueUpload(upload, file, controller)",
    ], "retryUpload")

    # Two places start an upload, and both are the gated ones above.
    enqueue_range = range(source.index("const enqueueSelectedFiles = async"), source.index("const onSelectFiles = async"))
    retry_range = range(source.index("const retryUpload = (upload"), source.index("const removeUpload = (localId"))
    starts = [m.start() for m in re.finditer(r"queueUpload\(", source)]
    assert len(starts) == 2 and any(s in enqueue_range for s in starts) and any(s in retry_range for s in starts), (
        "queueUpload has two call sites, both behind the gate; a third needs a gate of its own"
    )
    uploads = re.findall(r"(?<![\w.])uploadFile\(", source)
    assert len(uploads) == 1, "uploadFile must be reachable only through queueUpload"
    assert "const start = () => uploadFile(upload, file, controller);" in source

    paste_and_drop = _segment(source, "onPaste={(event) => {", "onDragOver={(event)")
    assert "enqueueSelectedFiles(pasted)" in paste_and_drop and "enqueueSelectedFiles(dropped)" in paste_and_drop
    assert "await enqueueSelectedFiles(chosen)" in source
    print("  Attach, paste, drop and retry reach the upload queue only through the gate.")


def test_the_composer_holds_send_while_a_file_waits_on_the_agreement():
    """The file has no chip until the gate settles, so the flag the gate raises must hold Send in the meantime."""
    print("\nTesting that Send is held while the agreement is being settled...")
    hook = _read(HOOK_TS)
    editor = _read(COMPOSER_TSX)
    composer = _read(CHAT_COMPOSER_TSX)
    explorer = _read(EXPLORER_TSX)

    # The hook: part of the gate's contract, raised only for a gate that needs the check, counted so that
    # overlapping gates keep it up, and lowered when the gate's promise settles, whichever way it settles.
    gate_interface = _segment(hook, "export interface UserAgreementGate {", "interface GateSession {")
    assert "pending: boolean;" in gate_interface
    confirm = _segment(hook, "const confirm = useCallback(", "const withAgreement = useCallback(")
    _positions(confirm, [
        "if (decision !== 'check') {",
        "return Promise.resolve(decision === 'proceed');",
        "holdGate();",
        "queue.current.then(run)",
        "void result.then(releaseGate, releaseGate);",
    ], "confirm")
    assert hook.count("holdGate()") == 1, "Only a gate that needs the check may raise the flag"
    hold = _segment(hook, "const holdGate = useCallback(", "const releaseGate = useCallback(")
    release = _segment(hook, "const releaseGate = useCallback(", "const finish = useCallback(")
    assert "waiting.current += 1;" in hold and "if (mounted.current)" in hold, "Updates after unmount are guarded"
    assert "waiting.current === 0 && mounted.current" in release, "The flag drops only when the last gate ends"
    assert "setPending(waiting.current > 0);" in hook, "An owner shown again must read the flag afresh"
    assert "{ confirm, withAgreement, prompt, pending, accept, cancel }" in hook
    assert hook.count("setPending(true)") == 1 and hook.count("setPending(false)") == 1

    # The editor tells its owner in the commit that raises the flag, and lowers it whenever it stops reporting.
    assert "onAgreementPendingChange?: (pending: boolean) => void;" in editor
    reporting = _segment(
        editor, "useLayoutEffect(() => {\n        onAgreementPendingChange?.(", "}, [agreementGate.pending, onAgreementPendingChange]);",
    )
    assert "onAgreementPendingChange?.(agreementGate.pending);" in reporting
    assert "return () => onAgreementPendingChange?.(false);" in reporting, "Going away must lower the flag"
    # Enter in the editor does nothing while a file is on its way, for an owner that does not wire the flag too.
    enter = _segment(editor, "if (event.key === 'Enter' && !event.shiftKey && onSubmit) {", "// Byte transfers belong")
    _positions(enter, ["event.preventDefault();", "if (!agreementGate.pending) {", "onSubmit();"], "the Enter handler")
    # Where the file's chip will appear, the wait is said in words, not by a disabled control alone.
    assert re.search(
        r"\{agreementGate\.pending && \(\s*<p role=\"status\" [^>]*>\{AGREEMENT_PENDING_MESSAGE\}</p>\s*\)\}", editor,
    ), "The editor must say, as status text, that the agreement is being checked"
    # A selection dropped because the person left the conversation is said, not lost in silence.
    enqueue = _segment(editor, "const enqueueSelectedFiles = async", "const onSelectFiles = async")
    owner_moved = _segment(enqueue, "currentOwner.current !== gatedOwner", "const replacing = retryFileId.current;")
    _positions(owner_moved, ["toast.error(", "return;"], "the owner-moved branch")

    # The composer includes the flag in the condition every send path already reads, so Enter, Send, the
    # large-run Continue and `submit()` itself all wait, and explains the held Send.
    assert "const [agreementPending, setAgreementPending] = useState(false);" in composer
    blocked = re.search(r"const uploadsBlocked = ([^;]+);", composer).group(1)
    assert "uploading" in blocked and "agreementPending" in blocked and "'failed'" in blocked, blocked
    editor_element = composer[composer.index("<ComposerEditor\n"):]
    assert "onAgreementPendingChange={setAgreementPending}" in editor_element.split("placeholder={", 1)[0]
    for reader in (
        "if (streaming || !canPost || uploadsBlocked || workflowResultOpening) {",
        "if (streaming || !canPost || uploadsBlocked) {",
        "submitDisabled={streaming || uploadsBlocked || workflowResultOpening",
        "|| !canPost || uploadsBlocked || workflowResultOpening || (orchestrating && orchestrationBlocked)}",
    ):
        assert reader in composer, f"{reader!r} no longer reads uploadsBlocked"
    assert "title={agreementPending ? AGREEMENT_PENDING_MESSAGE : undefined}" in composer
    assert "{uploading ? (" in composer, "The upload spinner still follows real uploads only"

    # The explorer does not use the flag: it holds its own controls while its upload is under way.
    assert "agreementGate.pending" not in explorer
    assert set(re.findall(r"agreementGate(\.\w+)?", explorer)) == {"", ".confirm"}, "The explorer's use of the gate changed"

    # Every consumer of the editor is either held or explained. A new one fails here until it is decided.
    consumers = {
        relative for relative, path in _v2_sources()
        if relative != "components/chat/ComposerEditor.tsx" and "<ComposerEditor" in path.read_text(encoding="utf-8")
    }
    assert consumers == set(COMPOSER_EDITOR_CONSUMERS), (
        "A component renders the shared editor and is not classified: hold its Send, submit or Next control "
        f"with onAgreementPendingChange, or explain why it needs none. {sorted(consumers ^ set(COMPOSER_EDITOR_CONSUMERS))}"
    )
    wired = {
        relative for relative in consumers
        if "onAgreementPendingChange=" in (V2_SRC / relative).read_text(encoding="utf-8")
    }
    assert consumers - wired == COMPOSER_EDITOR_UNHELD, (
        "The consumers that do not hold their controls changed; update COMPOSER_EDITOR_UNHELD and the feature "
        f"page's known limitations: {sorted((consumers - wired) ^ COMPOSER_EDITOR_UNHELD)}"
    )
    print("  Send is held while the agreement is being settled.")


def test_the_elicitation_card_holds_its_controls_while_a_file_waits_on_the_agreement():
    """Next, Review answers, Use these answers and Enter read one condition, and the hold is part of it."""
    print("\nTesting that the elicitation card holds its controls...")
    card = _read(ELICITATION_TSX)
    form = _segment(card, "export function ElicitationForm({", "function QuestionField({")
    field = card[card.index("function QuestionField({"):]

    # The state is declared with the other hooks, ahead of the return the form makes when it has no question,
    # and lowered by a question or a revision that replaces this one.
    _positions(form, [
        "const [agreementHolds, setAgreementHolds] = useState<ReadonlySet<string>>(() => new Set());",
        "const holdAgreement = useCallback((name: string, held: boolean) => setAgreementHolds((current) => {",
        "setAgreementHolds((current) => current.size === 0 ? current : new Set());",
        "if (!elicitation || !draft || !answer) {",
        "const agreementHeld = agreementHolds.size > 0;",
    ], "ElicitationForm")
    assert "}, [elicitation?.elicitation_id, elicitation?.revision]);" in form

    # The conditions every forward path reads: the Next, Review answers and Use these answers button, `send('accept')`,
    # `advance()` and the Enter that reaches it through the editor.
    assert "const canFinish = Object.keys(answer.errors).length === 0 && !answer.pendingUploads && !agreementHeld;" in form
    assert "const canAdvance = isReview ? canFinish : currentErrors.length === 0 && !agreementHeld;" in form
    assert "(action === 'accept' && !canFinish)" in form
    advance = _segment(form, "const advance = () => {", "return (\n        <section")
    assert "if (!canAdvance) {" in advance and "send('accept')" in advance and "changePage(pageIndex + 1)" in advance
    assert "disabled={draft.submitting || !canAdvance}" in form
    assert "onSubmit={advance}" in form
    # It says why, in the hint under the buttons, with the sentence the composer uses.
    assert re.search(r"<p>\{agreementHeld\s+\? AGREEMENT_PENDING_MESSAGE\s+: answer\.pendingUploads", form)
    assert "{(isReview ? !canFinish : !canAdvance) ? (" in form
    # Cancel, Continue without answers and Back are not held.
    for control in ("onClick={() => send('cancel')}", "onClick={() => send('decline')}",
                    "onClick={() => changePage(pageIndex - 1)}"):
        button = _segment(form, control, "</GlassButton>")
        assert "agreementHeld" not in button and "canAdvance" not in button and "canFinish" not in button, control
    # Each field reports through one function that stays the same while the field is mounted: the editor reports
    # again whenever its callback changes, so a new function on every render would raise and lower the hold forever.
    assert "onAgreementHold={holdAgreement}" in form
    assert re.search(
        r"const reportAgreementHold = useCallback\(\s+\(held: boolean\) => onAgreementHold\(name, held\),"
        r"\s+\[onAgreementHold, name\],\s+\);", field,
    )
    assert "onAgreementPendingChange={reportAgreementHold}" in field
    print("  The card's controls wait for a file that is waiting on the agreement.")


def test_the_assist_thread_can_never_reach_the_gate():
    """It renders the editor restricted, which switches uploads off, so no file can wait there or start a gate."""
    print("\nTesting that the assist thread cannot reach the gate...")
    assist = _read(ASSIST_THREAD_TSX)
    editor = _read(COMPOSER_TSX)
    assert re.search(r"\n\s+restricted\n", _segment(assist, "<ComposerEditor", "/>")), "AssistThread must stay restricted"
    assert (
        "const uploadsEnabled = features.enable_chat_file_uploads === true && !uploadsDisabled && !restricted;"
    ) in editor
    # Every way a file reaches the gate is behind that switch: the shared queue returns before it, and paste, drop,
    # the file input, the Attach buttons and the Retry button are off or not rendered without uploads.
    enqueue = _segment(editor, "const enqueueSelectedFiles = async", "const onSelectFiles = async")
    _positions(enqueue, ["if (disabled || !uploadsEnabled) {", "return;", "agreementGate.confirm("], "enqueueSelectedFiles")
    assert "if (!uploadsEnabled) {" in _segment(editor, "onPaste={(event) => {", "onDrop={(event) => {")
    assert "if (disabled || !uploadsEnabled) {" in _segment(editor, "onDrop={(event) => {", "onDragOver={(event)")
    assert re.search(r"\{!restricted && \(\s+<input ref=\{fileInputRef\} type=\"file\"", editor)
    assert re.search(r"disabled=\{disabled \|\| !uploadsEnabled[^}]*\}\s+onClick=\{\(\) => retryUpload\(upload\)\}", editor)
    print("  A restricted editor cannot upload, so its gate is never asked.")


def test_a_check_or_an_acceptance_that_never_answers_runs_out_of_time():
    """request() has no time limit, so the client puts one on both; the failure path is the one every failure takes."""
    print("\nTesting the time limit on the check and the acceptance...")
    client = _read(CLIENT_TS)
    hook = _read(HOOK_TS)
    assert len(re.findall(r"export const USER_AGREEMENT_REQUEST_TIMEOUT_MS = 20_000;", client)) == 1
    assert client.count("USER_AGREEMENT_REQUEST_TIMEOUT_MS =") == 1, "The limit must be one named constant"

    helper = _segment(client, "async function withTimeLimit<T>(", "export async function checkUserAgreement")
    _positions(helper, [
        "const controller = new AbortController();",
        "callerSignal?.addEventListener('abort', followCaller, { once: true });",
        "const timer = setTimeout(() => {",
        "timedOut = true;\n        controller.abort();\n    }, USER_AGREEMENT_REQUEST_TIMEOUT_MS);",
        "return await send(controller.signal);",
        "throw timedOut && !callerSignal?.aborted ? new UserAgreementTimeoutError() : error;",
        "clearTimeout(timer);",
        "callerSignal?.removeEventListener('abort', followCaller);",
    ], "withTimeLimit")
    # Both requests go out only through the limit, with the limit's own signal, and nowhere else.
    assert len(re.findall(r"request<unknown>\(", client)) == 2
    check = _segment(client, "export async function checkUserAgreement", "/** Record the acceptance.")
    accept = _segment(client, "export async function acceptUserAgreement", "export const CHECK_FAILED_MESSAGE")
    for name, source in (("check", check), ("accept", accept)):
        assert "withTimeLimit(signal, (limited) => request<unknown>(" in source and "signal: limited" in source, name
    # No browser API the supported browsers lack, and nothing that ignores a faked clock.
    assert "AbortSignal.timeout" not in client and "AbortSignal.any" not in client
    # A timeout is a failure of the ordinary kind: the same two failure sentences, and the hook's one catch for each
    # phase turns it into the dialog that offers Try again and Cancel.
    message = _segment(client, "export function agreementFailureMessage", "\n}\n")
    assert "error instanceof UserAgreementTimeoutError" in message and "no answer within" in message
    assert hook.count("agreementFailureMessage('check', error)") == 1
    assert hook.count("agreementFailureMessage('accept', error)") == 1
    # No new dependency: the client still imports only the API client and the shared types.
    assert re.findall(r"^import .* from '([^']+)';$", client, re.MULTILINE) == ['./apiClient', './types']
    print("  Both requests are bounded by one twenty second limit that fails them like any other failure.")


def test_the_documents_explorer_asks_after_validation_and_before_it_sends():
    """Permission, then the type and size checks, then the agreement, then the upload."""
    print("\nTesting the documents explorer's gate...")
    source = _read(EXPLORER_TSX)
    upload = _segment(source, "const onUploadFiles = useCallback(", "const onDownload = useCallback(")
    _positions(upload, [
        "operationTargets('upload')",
        "Unsupported workspace file type",
        "exceeds the ${maxSizeMb} MB limit",
        "if (!accepted.length) return;",
        "agreementGate.confirm(workspaceAgreementScope(captured.adapter.scope), accepted)",
        "|| !operationTargets('upload')) return;",
        "beginMutation('Uploading files'",
        "captured.adapter.upload(accepted)",
    ], "onUploadFiles")
    # The memoized callback must list the gate among its dependencies, wherever else it grows.
    assert re.search(r"\[[^\[\]]*agreementGate\.confirm[^\[\]]*\],\s*\)", upload), (
        "onUploadFiles must list agreementGate.confirm in its dependencies"
    )

    # The file input and the drop region call it, and so does nothing else: both go through the gate.
    callers = re.findall(r"onUploadFiles\(", source)
    assert len(callers) == 2, "A new caller of onUploadFiles still reaches the gate, but check it is intended"
    assert "onUpload={() => fileInputRef.current?.click()}" in source
    print("  The explorer asks only about files it will send, for the workspace it sends them to.")


def test_the_dialog_and_hook_follow_the_house_rules():
    """Safe rendering, the shared modal, no hidden-by-style, and a gate that ends when its owner goes."""
    print("\nTesting the dialog and the hook...")
    dialog = _read(DIALOG_TSX)
    hook = _read(HOOK_TS)
    client = _read(CLIENT_TS)

    for path, source in ((DIALOG_TSX, dialog), (HOOK_TS, hook), (CLIENT_TS, client)):
        assert source.startswith(f"// {path.name}\n"), f"{path.name} must start with its filename comment"
        assert not any(sink in source for sink in RAW_HTML_SINKS), f"{path.name} must not write raw HTML"
        assert "display:none" not in source.replace(" ", "") and "alert(" not in source.replace("window.alert", "")
        assert "http://" not in source and "https://" not in source, f"{path.name} must not reference a remote URL"

    # The agreement renders through the renderer the administrator's preview uses, in the shared modal
    # (Escape, backdrop, focus trap and focus return), never as raw HTML.
    assert "from './PlainMarkdown'" in dialog and "<PlainMarkdown" in dialog
    assert "from './Modal'" in dialog and "<Modal" in dialog
    assert "rehype-raw" not in dialog
    assert "role=\"alert\"" in dialog and "role=\"status\"" in dialog
    assert "onClose={prompt.busy ? IGNORE_CLOSE : onCancel}" in dialog, "A request in flight must not be dismissable"
    assert "'noopener,noreferrer'" in dialog, "Agreement links must open in a new tab without an opener"

    # A gate that is still waiting when its owner unmounts ends with "do not upload".
    assert "mounted.current = false" in hook and "finish(session, false)" in hook
    assert "controller.abort()" in hook
    # A failed check holds the upload: it shows the failure, never proceeds.
    assert "kind: 'unavailable'" in hook
    assert re.search(r"catch \(error\) \{\s+if \(session\.ended\) \{\s+return;\s+\}\s+show\(\{\s+kind: 'unavailable'", hook)
    print("  The dialog renders safely and the gate fails closed.")


def test_the_bootstrap_carries_the_switch_the_gate_reads():
    """V2 reads the administrator's switch from the bootstrap payload's sanitized settings, as classic's templates do."""
    print("\nTesting that the bootstrap carries the switch...")
    settings_source = _read(APP_ROOT / "functions_settings.py")
    terms = re.search(r"sensitive_terms = \(([^)]*)\)", settings_source.split("def sanitize_settings_for_user", 1)[1])
    assert terms, "sanitize_settings_for_user no longer declares its sensitive terms"
    redacted = [term for term in re.findall(r'"([^"]+)"', terms.group(1)) if term in "enable_user_agreement"]
    assert not redacted, f"sanitize_settings_for_user would strip enable_user_agreement via {redacted}"
    route = _read(APP_ROOT / "route_backend_v2.py")
    assert "public_settings = sanitize_settings_for_user(settings)" in route
    assert '"settings": public_settings,' in route, "The bootstrap payload must carry the sanitized settings"
    client = _read(CLIENT_TS)
    assert "settings?.enable_user_agreement" in client
    hook = _read(HOOK_TS)
    assert "useBootstrapStore.getState().data?.settings" in hook
    print("  The switch reaches V2 as classic's templates see it.")


def test_the_feature_documentation_is_present_and_names_every_gated_entry_point():
    """The feature page exists, carries the version, and lists the entry points the test above enumerates."""
    print("\nTesting the feature documentation...")
    text = _read(FEATURE_DOC)
    assert "0.261.445" in text
    for relative in GATED_ENTRY_POINTS:
        assert Path(relative).name in text, f"{relative} is not described in {FEATURE_DOC.name}"
    for needle in ("/api/user_agreement/check", "/api/user_agreement/accept", "fails closed", "once per day"):
        assert needle in text, f"{FEATURE_DOC.name} must describe {needle!r}"
    # The Send hold: the flag, who reads it, what the person is told, and the consumers that wire it.
    flat = " ".join(text.split())
    for needle in (
        "`pending`", "onAgreementPendingChange", "Checking the user agreement before attaching your file",
        "uploadsBlocked", "ElicitationCard", "Your file was not attached because you left the conversation",
        "canAdvance", "canFinish", "AssistThread",
    ):
        assert needle in flat, f"{FEATURE_DOC.name} must describe {needle!r}"
    # The time limit, and that the two gaps this page used to list are closed.
    for needle in ("USER_AGREEMENT_REQUEST_TIMEOUT_MS", "20 seconds", "no answer within 20 seconds", "Try again"):
        assert needle in flat, f"{FEATURE_DOC.name} must describe {needle!r}"
    for stale in ("The elicitation card does not hold its own controls", "A check that never answers holds Send"):
        assert stale not in flat, f"{FEATURE_DOC.name} still lists a limitation that is fixed: {stale!r}"
    guide = " ".join(_read(REPO_ROOT / "docs" / "guides" / "upload-documents-in-chat.md").split())
    assert "Checking the user agreement before attaching your file" in guide, "The chat guide must say why Send is held"
    assert "20 seconds" in guide, "The chat guide must say that a check that does not answer fails"
    print("  The feature page covers the entry points and the failure policy.")


def test_user_agreement_logic_checks_pass():
    """Execute the TypeScript checks, skipping when the front-end toolchain is absent."""
    print("\nTesting the user agreement logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return

    assert LOGIC_CHECK_TS.exists(), "The TypeScript user agreement checks are missing"
    assert MINI_REACT_HOOKS_TS.exists(), "The hooks runtime the gate hook's checks run on is missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node can resolve
    # bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-user-agreement-check.mjs"
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
                # The gate hook runs on a small hooks runtime, since there is no DOM to render it in. The
                # alias applies to the bundled sources only, so the stores still use the real packages.
                f"--alias:react={MINI_REACT_HOOKS_TS}",
                # apiClient reads import.meta.env, which only Vite provides.
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
            env={**os.environ},
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript user agreement checks failed")

    passed = result.stdout.count("  ok  ")
    assert passed >= 40, f"Only {passed} user agreement checks ran; the runner likely broke."
    print(f"  ok  {passed} TypeScript user agreement checks passed")


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_the_client_calls_the_routes_with_the_names_the_route_reads,
        test_v2_names_workspaces_exactly_as_classics_call_sites_do,
        test_every_multipart_sender_is_gated_transport_or_explained,
        test_only_the_gated_components_start_a_chat_or_workspace_upload,
        test_the_chat_composer_asks_before_it_attaches_or_sends_anything,
        test_the_composer_holds_send_while_a_file_waits_on_the_agreement,
        test_the_elicitation_card_holds_its_controls_while_a_file_waits_on_the_agreement,
        test_the_assist_thread_can_never_reach_the_gate,
        test_a_check_or_an_acceptance_that_never_answers_runs_out_of_time,
        test_the_documents_explorer_asks_after_validation_and_before_it_sends,
        test_the_dialog_and_hook_follow_the_house_rules,
        test_the_bootstrap_carries_the_switch_the_gate_reads,
        test_the_feature_documentation_is_present_and_names_every_gated_entry_point,
        test_user_agreement_logic_checks_pass,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
