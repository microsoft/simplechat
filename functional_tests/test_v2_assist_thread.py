#!/usr/bin/env python3
"""
Functional test for the shared AI-assist thread in the V2 revision editors.
Version: 0.261.200
Implemented in: 0.261.200

This test ensures the diagram, chart, image and plan editors share one assist thread that
moves a sent message into the conversation at once, clears the input, and shows a pending
reply that can be cancelled, with Retry and Edit and resend when a request fails.

Three guarantees are load-bearing. Every request carries a client submission id, which is how
an optimistic turn is matched with the stored one, so nothing shows twice or goes missing,
including in a shared chat. An instruction over the limit is refused rather than cut short,
and the limit the counter enforces is never above the server's. And an editor stays open while
the reply it asked for re-renders the message, because a remount closed it and lost its thread.

The behaviour of the thread itself is checked in test_v2_assist_thread_logic.ts, which this
test bundles and runs when the front-end toolchain is installed.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
APP_DIR = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))
sys.path.insert(0, str(APP_DIR))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.200"

CHAT_COMPONENTS = V2_SRC / "components" / "chat"
THREAD_TSX = CHAT_COMPONENTS / "AssistThread.tsx"
COMPOSER_TSX = CHAT_COMPONENTS / "ComposerEditor.tsx"
MARKDOWN_TSX = CHAT_COMPONENTS / "AssistantMarkdown.tsx"
MERMAID_TSX = CHAT_COMPONENTS / "MermaidDiagram.tsx"
THREAD_TS = V2_SRC / "lib" / "assistThread.ts"
LIMITS_TS = V2_SRC / "lib" / "assistLimits.ts"
STORE_TS = V2_SRC / "stores" / "assistThreadStore.ts"
CHAT_STORE_TS = V2_SRC / "stores" / "chatStore.ts"
ENDPOINTS_TS = V2_SRC / "lib" / "endpoints.ts"
COLLABORATION_TS = V2_SRC / "lib" / "collaboration.ts"
ORCHESTRATION_TS = V2_SRC / "lib" / "orchestration.ts"
CONTROLLER_TS = V2_SRC / "lib" / "orchestrationController.ts"
PLAN_IDS_TS = V2_SRC / "lib" / "planSubmissionIds.ts"

EDITORS = {
    "diagram": CHAT_COMPONENTS / "DiagramEditor.tsx",
    "chart": CHAT_COMPONENTS / "ChartEditor.tsx",
    "image": CHAT_COMPONENTS / "ImageEditor.tsx",
    "plan": CHAT_COMPONENTS / "OrchestrationPlanEditor.tsx",
}

# Where each client limit comes from, and the server constant it must not exceed.
LIMIT_SOURCES = {
    "block": (
        V2_SRC / "lib" / "blockRevisions.ts",
        "MAX_INSTRUCTION_LENGTH",
        APP_DIR / "functions_block_revision_assist.py",
        "MAX_INSTRUCTION_LENGTH",
    ),
    "image": (
        V2_SRC / "lib" / "imageRevisions.ts",
        "MAX_IMAGE_INSTRUCTION_LENGTH",
        APP_DIR / "functions_message_image_revisions.py",
        "MAX_INSTRUCTION_LENGTH",
    ),
    "plan": (
        ORCHESTRATION_TS,
        "MAX_PLAN_INSTRUCTION_LENGTH",
        APP_DIR / "functions_orchestration_plan_revisions.py",
        "EDIT_INSTRUCTION_LIMIT",
    ),
}


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def _python_constant(path, name):
    """Read a module-level integer constant without importing the module."""
    tree = ast.parse(_read(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, int), f"{path.name}: {name} is not an integer"
            return value
    raise AssertionError(f"{path.name} no longer defines {name}")


def _component_body(path, name):
    """The source of one exported function component, from its signature to the next export."""
    source = _read(path)
    start = source.find(f"export function {name}(")
    assert start >= 0, f"{path.name} no longer exports {name}"
    end = source.find("\nexport ", start + 1)
    return source[start:] if end < 0 else source[start:end]


def test_version_is_at_least_the_implementing_release():
    """The feature must not appear in a build older than the one that introduced it."""
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  application version is at or beyond the implementing release")


def test_every_revision_editor_uses_the_shared_thread():
    """One thread, not four: each editor renders AssistThread and drives it through the hook."""
    for kind, path in EDITORS.items():
        source = _read(path)
        assert "from './AssistThread'" in source, f"the {kind} editor does not import AssistThread"
        assert "useAssistThread({" in source, f"the {kind} editor does not use useAssistThread"
        assert "<AssistThread" in source, f"the {kind} editor does not render AssistThread"
        # The input used to be local state that was only cleared once the server answered.
        assert "setInstruction(" not in source, f"the {kind} editor still keeps its own instruction"

    print("  ok  all four editors send through the shared assist thread")


def test_sending_does_not_wait_for_the_server():
    """The message joins the thread and the input clears before the request starts."""
    source = _read(THREAD_TS)
    submit = source[source.find("export function submitAssistDraft("):]
    submit = submit[: submit.find("\n}\n")]

    assert "status: 'pending'" in submit
    assert "draft: blankDraft()" in submit
    # The thread is updated first; the request only starts afterwards.
    assert submit.find("updateThread(") < submit.find("runExchange("), (
        "the input must clear before the request is sent"
    )
    assert "void runExchange(" in submit, "the request must not be awaited before the thread updates"

    print("  ok  a sent message joins the thread before the server answers")


def test_the_thread_is_announced_as_a_polite_log():
    """Screen readers hear new turns without the elapsed seconds being read out."""
    source = _read(THREAD_TSX)
    assert 'role="log"' in source
    assert 'aria-live="polite"' in source
    assert 'aria-hidden="true"' in source and "data-testid=\"assist-elapsed\"" in source, (
        "the running seconds must be hidden from assistive technology"
    )
    for label in ("Cancel", "Retry", "Edit and resend"):
        assert label in source, f"the thread no longer offers {label}"

    print("  ok  the thread is a polite log with Cancel, Retry and Edit and resend")


def test_the_editor_input_is_the_restricted_composer():
    """The editors reuse the main composer's editor, with uploads and / prompts switched off."""
    composer = _read(COMPOSER_TSX)
    assert "restricted?: boolean;" in composer
    assert "allowContext?: boolean;" in composer
    assert "const slashEnabled = !restricted;" in composer
    assert "&& !restricted;" in composer, "uploads must be off in a restricted composer"
    assert "const contextEnabled = !restricted || allowContext;" in composer

    thread = _read(THREAD_TSX)
    assert "<ComposerEditor" in thread
    assert re.search(r"<ComposerEditor[\s\S]*?\brestricted\b[\s\S]*?/>", thread), (
        "the thread must use the restricted composer"
    )
    assert "allowContext = false" in thread, "# references must stay off unless an editor opts in"

    # A2 (0.261.201) turns # references on in the plan editor only, which sends them with its
    # request for the server to authorise. The diagram, chart and image editors stay without them.
    for kind, path in EDITORS.items():
        source = _read(path)
        if kind == "plan":
            assert re.search(r"<AssistThread[\s\S]*?\ballowContext\b[\s\S]*?/>", source), (
                "the plan editor must offer # documents and tags"
            )
        else:
            assert "allowContext" not in source, f"the {kind} editor must not turn on # references"

    print("  ok  the editors use the restricted composer, with # references in the plan editor only")


def test_over_limit_input_is_refused_not_cut_short():
    """A counter shows the limit, and nothing trims what the reader wrote."""
    for kind, path in EDITORS.items():
        source = _read(path)
        for constant in ("MAX_INSTRUCTION_LENGTH", "MAX_IMAGE_INSTRUCTION_LENGTH", "MAX_PLAN_INSTRUCTION_LENGTH"):
            assert f"maxLength={{{constant}}}" not in source, (
                f"the {kind} editor still truncates its instruction with maxLength"
            )

    for path in (THREAD_TSX, THREAD_TS, COMPOSER_TSX):
        source = _read(path)
        assert not re.search(r"\.(slice|substring)\(0,\s*(max|MAX_|limit)", source), (
            f"{path.name} cuts the instruction short"
        )

    thread = _read(THREAD_TS)
    assert "draft.text.length > maxLength ? 'too_long'" in thread
    assert "overLimit: draft.text.length > maxLength" in thread

    component = _read(THREAD_TSX)
    assert "!thread.overLimit" in component, "Send must be refused while the input is over the limit"
    assert "counterId" in component, "the input must show a character counter"

    print("  ok  over-limit input is refused with a counter, never truncated")


def test_the_limits_match_the_server():
    """The counter's limit is the server's, so nothing the reader sends is cut short there."""
    limits_source = _read(LIMITS_TS)
    for kind, (client_path, client_name, server_path, server_name) in LIMIT_SOURCES.items():
        match = re.search(rf"\b{kind}:\s*(\d+)", limits_source)
        assert match, f"assistLimits.ts has no {kind} limit"
        client_limit = int(match.group(1))
        server_limit = _python_constant(server_path, server_name)

        assert client_limit <= server_limit, (
            f"the {kind} counter allows {client_limit} characters but the server keeps {server_limit}"
        )
        assert client_limit == server_limit, (
            f"the {kind} limits drifted: client {client_limit}, server {server_limit}"
        )
        assert f"{client_name} = ASSIST_INSTRUCTION_LIMITS.{kind};" in _read(client_path), (
            f"{client_path.name} must take {client_name} from assistLimits.ts"
        )

    print("  ok  every editor's limit matches its server's")


def test_every_request_carries_a_submission_id():
    """The id is how the optimistic turn and the stored turn are recognised as one."""
    chat_store = _read(CHAT_STORE_TS)
    assert "...(submissionId ? { submission_id: submissionId } : {})" in chat_store

    # The shared chat route takes the same optional field as the personal one.
    assert "submission_id?: string;" in _read(ENDPOINTS_TS)
    collaboration = _read(COLLABORATION_TS)
    assist = collaboration[collaboration.find("export const assistCollaborationBlockRevision"):]
    assert "submission_id?: string;" in assist[: assist.find("=>")], (
        "a shared chat's assist request must accept a submission id"
    )

    controller = _read(CONTROLLER_TS)
    assert "submission_id: sentId" in controller
    # The server holds an id to the request it first came with and refuses it with any other, so
    # a retry that is no longer the same request must go out under a fresh id.
    assert (
        "choosePlanSubmissionId(fingerprint, session.submission, options.submissionId, makeTurnId)"
        in controller
    )
    assert "rememberPlanSubmission(sentId, fingerprint);" in controller
    plan_ids = _read(PLAN_IDS_TS)
    assert "previous === undefined || previous === fingerprint" in plan_ids
    assert "MAX_SENT_PLAN_SUBMISSIONS" in plan_ids

    # Each editor hands the thread's whole request to the hook that sends it, so the id, the
    # abort signal and the cancelled ids all travel together.
    for hook in (V2_SRC / "lib" / "blockRevisions.ts", V2_SRC / "lib" / "imageRevisions.ts"):
        source = _read(hook)
        for forwarded in (
            "submissionId: request.submissionId",
            "signal: request.signal",
            "earlierSubmissionIds: request.earlierSubmissionIds",
        ):
            assert forwarded in source, f"{hook.name} does not forward {forwarded.split(':')[0]}"
    for kind in ("diagram", "chart"):
        source = _read(EDITORS[kind])
        assert "onAsk: AssistSend;" in source and "send: onAsk," in source, (
            f"the {kind} editor must send through its block's revision hook"
        )
    assert "revisions.ask(request," in _read(EDITORS["image"])
    assert "{ submissionId, inlineError: true }" in _read(EDITORS["plan"])

    print("  ok  every assist request carries the thread's submission id")


def test_stored_turns_reconcile_by_submission_id():
    """A stored turn replaces its optimistic twin, and a cancelled change that landed is recognised."""
    thread = _read(THREAD_TS)
    assert "export function reconcileStoredExchanges(" in thread
    # A shared chat can deliver the stored turns before this page's own reply arrives.
    assert "pending: allExchanges.find((exchange) => exchange.status === 'pending')" in thread

    chat_store = _read(CHAT_STORE_TS)
    assert "chatHoldsSubmission(storedChat, earlierSubmissionIds)" in chat_store
    assert "earlierApplied: true" in chat_store

    for kind in ("diagram", "chart", "plan"):
        assert "storedTurns:" in _read(EDITORS[kind]), f"the {kind} editor does not reconcile its stored chat"

    print("  ok  stored turns reconcile with the thread by submission id")


def test_the_image_transcript_stays_on_the_page():
    """The image editor keeps its own transcript in memory, not in the conversation."""
    image = _read(EDITORS["image"])
    assert "mode: 'local'" in image
    for kind in ("diagram", "chart", "plan"):
        assert "mode: 'stored'" in _read(EDITORS[kind]), f"the {kind} editor must show the stored chat"

    store = _read(STORE_TS)
    for storage in ("localStorage", "sessionStorage", "indexedDB", "persist("):
        assert storage not in store, f"the assist threads must not be persisted ({storage})"

    print("  ok  the image transcript is local and nothing is persisted")


def test_the_editors_stay_open_while_the_message_changes():
    """A reply re-renders its message. Neither the diagram nor the chart editor may unmount."""
    markdown = _read(MARKDOWN_TSX)
    # A new message object carries a new, equal masks array. Keying the parse on its value keeps
    # the rendered blocks, and the editors they own, mounted.
    assert "const maskKey = JSON.stringify(masks ?? NO_MASKS);" in markdown
    assert "[content, maskKey, streaming]" in markdown

    diagram = _component_body(MERMAID_TSX, "MermaidDiagram")
    assert "let body: ReactNode;" in diagram
    assert "return <DiagramSource" not in diagram, "an early return would unmount the editor"
    body_at = diagram.find("{body}")
    editor_at = diagram.find("{editing && (")
    assert 0 <= body_at < editor_at, "the editor must render beside the body in every state"

    print("  ok  the editors stay mounted while their message re-renders")


def test_the_thread_renders_text_only():
    """Turns hold what a model or another participant wrote, so none of it reaches an HTML sink."""
    for path in (THREAD_TSX, THREAD_TS, STORE_TS):
        source = _read(path)
        assert "dangerouslySetInnerHTML" not in source, f"{path.name} writes HTML"
        assert "innerHTML" not in source, f"{path.name} writes HTML"

    print("  ok  the thread renders text only")


def test_the_new_files_load_nothing_remote():
    """Browser code stays local: no remote URL and no dynamic import."""
    for path in (THREAD_TSX, THREAD_TS, STORE_TS, LIMITS_TS, PLAN_IDS_TS):
        source = _read(path)
        assert not re.search(r"https?://", source), f"{path.name} references a remote URL"
        assert not re.search(r"\bimport\(", source), f"{path.name} uses a dynamic import"

    print("  ok  the assist thread loads nothing remote")


def test_the_typescript_logic_checks_pass():
    """Run the bundled behaviour checks, when the front-end toolchain is installed."""
    ui_dir = REPO_ROOT / "application" / "v2_ui"
    check = Path(__file__).with_name("test_v2_assist_thread_logic.ts")

    assert check.exists(), "the logic check file is missing"

    if not (ui_dir / "node_modules").exists():
        print("  --  skipped the TypeScript checks: run npm install in application/v2_ui")
        return

    bundle = ui_dir / "node_modules" / ".cache-assist-thread-check.mjs"
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
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(ui_dir),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(ui_dir),
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
    assert passed > 50, f"expected the full check suite, saw {passed} checks"
    print(f"  ok  {passed} TypeScript logic checks passed")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_every_revision_editor_uses_the_shared_thread,
    test_sending_does_not_wait_for_the_server,
    test_the_thread_is_announced_as_a_polite_log,
    test_the_editor_input_is_the_restricted_composer,
    test_over_limit_input_is_refused_not_cut_short,
    test_the_limits_match_the_server,
    test_every_request_carries_a_submission_id,
    test_stored_turns_reconcile_by_submission_id,
    test_the_image_transcript_stays_on_the_page,
    test_the_editors_stay_open_while_the_message_changes,
    test_the_thread_renders_text_only,
    test_the_new_files_load_nothing_remote,
    test_the_typescript_logic_checks_pass,
]


if __name__ == "__main__":
    failures = 0
    for test in TESTS:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()

    total = len(TESTS)
    print(f"\n{total - failures}/{total} checks passed")
    sys.exit(0 if failures == 0 else 1)
