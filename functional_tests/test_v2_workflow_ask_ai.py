#!/usr/bin/env python3
# test_v2_workflow_ask_ai.py
"""
Functional test for the Ask AI tab in the V2 workflow editor.
Version: 0.261.213
Implemented in: 0.261.213

This test ensures the Ask AI tab builds exactly the request POST /api/user/workflows/assist
accepts: limits counted in code points, base null and no id for a new or proposal draft, only
completed turns replayed, documents only as references, and the focus and time zone only when
they are valid. It also ensures nothing the server returns is trusted: an answer is checked
field by field, the change list shown is the editor's own diff of the draft it sent against the
candidate, every string stays plain text, and every status maps to a message and a next step.
The candidate is laid over the live draft before it is applied, so untouched values keep their
identity, and a turn's card reads its state from the authoring history. The shared assist
thread's new options default to today's behaviour, and a thread the workflow editor held never
sweeps the chat's idle threads.

The behaviour lives in TypeScript, so the checks are bundled with esbuild and run under node by
test_v2_workflow_ask_ai_logic.ts, following test_v2_workflow_change_tracking.py.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.213"

CODE_POINTS_TS = V2_SRC / "lib" / "codePoints.ts"
ASSIST_TS = V2_SRC / "lib" / "workflowAssist.ts"
STORE_TS = V2_SRC / "stores" / "workflowAssistStore.ts"
HOOK_TS = V2_SRC / "components" / "workflows" / "useWorkflowAssist.ts"
TAB_TSX = V2_SRC / "components" / "workflows" / "WorkflowAskAiTab.tsx"
DIALOG_TSX = V2_SRC / "components" / "workflows" / "WorkflowEditorDialog.tsx"
THREAD_TSX = V2_SRC / "components" / "chat" / "AssistThread.tsx"
THREAD_TS = V2_SRC / "lib" / "assistThread.ts"
COMPOSER_TSX = V2_SRC / "components" / "chat" / "ComposerEditor.tsx"
SERVER_ASSIST_PY = REPO_ROOT / "application" / "single_app" / "functions_workflow_assist.py"
LOGIC_CHECK = Path(__file__).with_name("test_v2_workflow_ask_ai_logic.ts")

# The four editors that used the shared thread before Ask AI. They must keep today's behaviour.
CHAT_EDITORS = tuple(
    V2_SRC / "components" / "chat" / name
    for name in ("DiagramEditor.tsx", "ChartEditor.tsx", "ImageEditor.tsx", "OrchestrationPlanEditor.tsx")
)
THREAD_OPTIONS = (
    "countCodePoints", "retain", "sendText", "cancelledMessage", "contextDocumentsOnly",
    "documentsOnly", "renderReply", "holdAssistThread",
)

NEW_FILES = (CODE_POINTS_TS, ASSIST_TS, STORE_TS, HOOK_TS, TAB_TSX)

IMPORT_RE = re.compile(r"^\s*import\s[^;]*?from\s+'([^']+)'", re.MULTILINE | re.DOTALL)

ALLOWED_PACKAGES = {"react", "clsx", "lucide-react", "zustand"}

# Ways model or server text could become markup. The reply, the error, the rate-limit message,
# change labels, warnings and document labels are all rendered as React text nodes.
HTML_SINKS = ("dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")
MARKDOWN_RENDERERS = ("AssistantMarkdown", "ReactMarkdown", "react-markdown", "marked", "markdown-it", "DOMPurify")


def test_version_is_at_least_the_implementing_release():
    """The release that introduced the Ask AI tab, or a later one, is configured."""
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  the configured version includes the Ask AI tab")


def test_ask_ai_imports_only_local_modules():
    """The tab is local code: no remote asset and no package the app does not already ship."""
    for path in NEW_FILES:
        source = path.read_text(encoding="utf-8")
        assert source.startswith(f"// {path.name}"), f"{path.name} must start with its filename comment"
        for module in IMPORT_RE.findall(source):
            assert module.startswith(".") or module in ALLOWED_PACKAGES, (
                f"{path.name} imports {module}; Ask AI may only use local modules and the packages "
                f"the app already ships ({', '.join(sorted(ALLOWED_PACKAGES))})"
            )
        assert "http://" not in source and "https://" not in source, f"{path.name} references a remote URL"
        assert "import(" not in source, f"{path.name} must not load code dynamically"
    print("  ok  Ask AI imports only local modules and packages the app already ships")


def test_model_and_server_text_render_as_plain_text():
    """Nothing in the Ask AI tab turns model or server text into HTML or rendered Markdown."""
    for path in NEW_FILES:
        source = path.read_text(encoding="utf-8")
        for sink in HTML_SINKS:
            assert sink not in source, f"{path.name} uses {sink}; model and server text must stay plain text"
        for renderer in MARKDOWN_RENDERERS:
            assert not re.search(rf"\b{re.escape(renderer)}\b", source), (
                f"{path.name} mentions {renderer}; the assistant's reply is plain text, not Markdown"
            )
    tab = TAB_TSX.read_text(encoding="utf-8")
    assert "renderReply" in tab, "the tab must render the reply itself, through the thread's plain-text hook"
    print("  ok  replies, errors and labels render as plain text")


def test_the_dialog_gates_ask_ai_on_the_bootstrap_flag():
    """The tab reads the per-user flag the bootstrap sends, and is only for writable personal workflows."""
    dialog = DIALOG_TSX.read_text(encoding="utf-8")
    assert re.search(r"features\??\.enable_workflow_ai_assistant === true", dialog), (
        "Ask AI must be gated on features.enable_workflow_ai_assistant alone"
    )
    gate = re.search(r"const askAiAvailable = ([^;]+);", dialog)
    assert gate, "the dialog must decide once whether Ask AI is available"
    condition = gate.group(1)
    for part in ("askAiEnabled", "personal", "!readOnly"):
        assert part in condition, f"Ask AI availability must include {part}"
    print("  ok  the dialog gates Ask AI on the bootstrap flag, a personal workflow and a writable editor")


def test_the_shared_thread_options_default_off():
    """Every option Ask AI added to the shared thread defaults to what the other editors do today."""
    thread = THREAD_TSX.read_text(encoding="utf-8")
    assert re.search(r"contextDocumentsOnly\s*=\s*false", thread), "contextDocumentsOnly must default to false"
    assert "cancelledMessage" in thread, "the thread must accept the editor's own cancel wording"
    composer = COMPOSER_TSX.read_text(encoding="utf-8")
    assert re.search(r"contextDocumentsOnly\s*=\s*false", composer), (
        "the composer must offer tags and documents unless an editor opts in to documents only"
    )
    logic = THREAD_TS.read_text(encoding="utf-8")
    for option in ("retain", "countCodePoints"):
        assert f"const {option} = options.{option} === true;" in logic, f"{option} must default to off"

    for editor in CHAT_EDITORS:
        source = editor.read_text(encoding="utf-8")
        used = [option for option in THREAD_OPTIONS if re.search(rf"\b{option}\b", source)]
        assert not used, f"{editor.name} must keep today's thread behaviour, but uses {used}"
    print("  ok  the shared thread's new options default to today's behaviour, and the chat editors pass none")


def test_the_instruction_limit_matches_the_server():
    """The tab refuses exactly what the route refuses: the same limit, counted in code points."""
    server = re.search(r"^ASSIST_INSTRUCTION_MAX_LENGTH = (\d+)$",
                       SERVER_ASSIST_PY.read_text(encoding="utf-8"), re.MULTILINE)
    client = re.search(r"^export const WORKFLOW_ASSIST_INSTRUCTION_LIMIT = (\d+);$",
                       ASSIST_TS.read_text(encoding="utf-8"), re.MULTILINE)
    assert server and client, "both instruction limits must stay plain constants"
    assert server.group(1) == client.group(1), (
        f"the tab allows {client.group(1)} code points but the server allows {server.group(1)}"
    )
    hook = HOOK_TS.read_text(encoding="utf-8")
    assert "maxLength: WORKFLOW_ASSIST_INSTRUCTION_LIMIT," in hook, "the thread must use the shared limit"
    assert "countCodePoints: true," in hook, "the thread must count code points, as the server does"
    print(f"  ok  the tab and the server both allow {server.group(1)} code points")


def test_the_typescript_logic_checks_pass():
    """Run the bundled behaviour checks, when the front-end toolchain is installed."""
    assert LOGIC_CHECK.exists(), "the logic check file is missing"

    if not (V2_DIR / "node_modules").exists():
        print("  --  skipped the TypeScript checks: run npm ci in application/v2_ui")
        return

    bundle = V2_DIR / "node_modules" / ".cache-workflow-ask-ai-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(LOGIC_CHECK),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
            timeout=300,
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=(sys.platform == "win32"),
            timeout=300,
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0 or "FAIL  " in result.stdout:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    assert passed >= 150, f"expected the full check suite, saw {passed} checks"
    print(f"  ok  {passed} TypeScript logic checks passed")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_ask_ai_imports_only_local_modules,
    test_model_and_server_text_render_as_plain_text,
    test_the_dialog_gates_ask_ai_on_the_bootstrap_flag,
    test_the_shared_thread_options_default_off,
    test_the_instruction_limit_matches_the_server,
    test_the_typescript_logic_checks_pass,
]


if __name__ == "__main__":
    passed = 0
    for test in TESTS:
        try:
            test()
            passed += 1
        except Exception as error:  # noqa: BLE001 - report and continue to the next check
            print(f"FAIL  {test.__name__}: {error}")

    print(f"\n{passed}/{len(TESTS)} checks passed")
    sys.exit(0 if passed == len(TESTS) else 1)
