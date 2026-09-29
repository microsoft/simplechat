#!/usr/bin/env python3
"""
Functional test for `#` document and tag references in the V2 plan editor's Ask AI.
Version: 0.261.201
Implemented in: 0.261.201

This test ensures the plan editor's Ask AI input offers `#` documents and tags, and only those,
sends them with the request in the same canonical form the server compares a replayed submission
against, and shows them back in the thread as plain text. The diagram, chart and image editors,
the main composer and the question card keep what they had.

The browser's behaviour is checked in test_v2_plan_references_logic.ts, which this test bundles
and runs when the front-end toolchain is installed. That file reads the same canonicalization
fixture as test_assist_reference_canonicalization.py, so the two sides cannot drift apart.
"""

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

IMPLEMENTED_IN = "0.261.201"

CHAT_COMPONENTS = V2_SRC / "components" / "chat"
PLAN_EDITOR_TSX = CHAT_COMPONENTS / "OrchestrationPlanEditor.tsx"
THREAD_TSX = CHAT_COMPONENTS / "AssistThread.tsx"
COMPOSER_TSX = CHAT_COMPONENTS / "ComposerEditor.tsx"
COMPOSER_PAGE_TSX = CHAT_COMPONENTS / "Composer.tsx"
ELICITATION_TSX = CHAT_COMPONENTS / "ElicitationCard.tsx"
CONTEXT_MENU_TSX = CHAT_COMPONENTS / "ContextMenu.tsx"
PICKER_TSX = CHAT_COMPONENTS / "DocumentPickerPopover.tsx"
PLAN_REFERENCES_TS = V2_SRC / "lib" / "planReferences.ts"
CONTEXT_MENTIONS_TS = V2_SRC / "lib" / "contextMentions.ts"
CONTROLLER_TS = V2_SRC / "lib" / "orchestrationController.ts"
ORCHESTRATION_TS = V2_SRC / "lib" / "orchestration.ts"
THREAD_TS = V2_SRC / "lib" / "assistThread.ts"
FIXTURE = REPO_ROOT / "functional_tests" / "fixtures" / "plan_reference_canonicalization.json"

OTHER_EDITORS = {
    "diagram": CHAT_COMPONENTS / "DiagramEditor.tsx",
    "chart": CHAT_COMPONENTS / "ChartEditor.tsx",
    "image": CHAT_COMPONENTS / "ImageEditor.tsx",
}


def _read(path):
    return path.read_text(encoding="utf-8")


def test_version_is_at_least_the_implementing_release():
    """The release that added plan editor references is in place."""
    assert_app_version_at_least(IMPLEMENTED_IN)
    print(f"  ok  version is at least {IMPLEMENTED_IN}")


def test_only_the_plan_editor_offers_references():
    """Decision 8: the plan editor opts in; the diagram, chart and image editors do not."""
    plan = _read(PLAN_EDITOR_TSX)
    assert re.search(r"<AssistThread[\s\S]*?\ballowContext\b[\s\S]*?/>", plan), (
        "the plan editor's Ask AI must offer # documents and tags"
    )
    for kind, path in OTHER_EDITORS.items():
        assert "allowContext" not in _read(path), f"the {kind} editor must not offer # references"

    thread = _read(THREAD_TSX)
    assert "allowContext = false" in thread, "an editor must opt in to # references"
    assert re.search(r"<ComposerEditor[\s\S]*?\brestricted\b[\s\S]*?/>", thread), (
        "the editors' input must stay the restricted composer, without uploads or / prompts"
    )

    # The main composer and the question card are not restricted, so they keep everything.
    for path in (COMPOSER_PAGE_TSX, ELICITATION_TSX):
        source = _read(path)
        assert "<ComposerEditor" in source, f"{path.name} no longer uses the shared composer"
        assert not re.search(r"\brestricted\b|\ballowContext\b", source), (
            f"{path.name} must keep its full composer"
        )

    print("  ok  only the plan editor offers # references")


def test_the_restricted_picker_offers_documents_and_tags_only():
    """A plan request can use a document or a tag, so whole workspaces are not offered there."""
    composer = _read(COMPOSER_TSX)
    assert "workspacesEnabled: !restricted," in composer
    assert re.search(r"features\.enable_public_workspaces, restricted\]", composer), (
        "the search scope must be rebuilt when the composer's mode changes"
    )

    menu = _read(CONTEXT_MENU_TSX)
    assert "workspacesEnabled?: boolean;" in menu
    assert "includeWorkspaces: scopeRef.current.workspacesEnabled !== false," in menu
    assert "scope.workspacesEnabled]);" in menu, "the # menu must search again when the scope changes"

    picker = _read(PICKER_TSX)
    assert "const includeWorkspaces = scope.workspacesEnabled !== false;" in picker
    assert re.search(r"searchContextCandidates\(\{[\s\S]*?\bincludeWorkspaces,", picker)
    assert "'Search documents and tags…'" in picker

    mentions = _read(CONTEXT_MENTIONS_TS)
    assert "includeWorkspaces?: boolean;" in mentions
    guard = mentions.index("if (options.includeWorkspaces === false) {")
    assert guard < mentions.index("const allScopes: ContextScopeRef[] = ["), (
        "workspace rows must be left out before they are built"
    )

    print("  ok  the restricted picker offers documents and tags, not workspaces")


def test_the_request_carries_canonical_references():
    """The editor sends every chip, and the controller fingerprints the canonical form."""
    plan = _read(PLAN_EDITOR_TSX)
    assert "const references = planDraftReferences(draft);" in plan
    assert "{ action: 'ask', instruction: text, ...(references.length ? { references } : {}) }" in plan

    controller = _read(CONTROLLER_TS)
    canonical = controller.index("references = canonicalPlanReferences(action.references);")
    rebuilt = controller.index(
        "action = { action: 'ask', instruction, ...(references.length ? { references } : {}) };"
    )
    fingerprint = controller.index(
        "const fingerprint = JSON.stringify({ runId: requestPlan.run_id, version, edits, action });"
    )
    assert canonical < rebuilt < fingerprint, (
        "the fingerprint that decides id reuse must cover the canonical references"
    )
    assert "problem instanceof PlanReferenceError ? problem.message" in controller

    orchestration = _read(ORCHESTRATION_TS)
    assert re.search(
        r"action: 'ask';\s*instruction: string;[\s\S]{0,200}?references\?: readonly PlanReferenceInput\[\];",
        orchestration,
    ), "the Ask action must declare its references"

    print("  ok  Ask requests carry canonical references, covered by the id fingerprint")


def test_the_browser_mirrors_the_server_limits():
    """The canonical form's limits are the server's."""
    import functions_assist_references as server  # noqa: E402

    source = _read(PLAN_REFERENCES_TS)
    for name in (
        "REFERENCE_LABEL_LIMIT",
        "REFERENCE_IDENTIFIER_LIMIT",
        "REQUEST_REFERENCE_LIMIT",
        "REQUEST_REFERENCE_RAW_LIMIT",
    ):
        match = re.search(rf"export const {name} = (\d+);", source)
        assert match, f"planReferences.ts does not declare {name}"
        assert int(match.group(1)) == getattr(server, name), f"{name} differs from the server's"

    assert "plan_reference_canonicalization.json" in source, "the browser side must name its fixture"
    assert FIXTURE.exists(), "the shared canonicalization fixture is missing"

    print("  ok  the browser's reference limits are the server's")


def test_the_thread_shows_chips_as_text():
    """Chips come from untrusted labels, so they are rendered as text and never as HTML."""
    thread = _read(THREAD_TSX)
    assert "function ReferenceChips(" in thread
    assert 'data-testid="assist-reference-chip"' in thread
    assert 'data-testid="assist-scope-notice"' in thread
    assert '<span className="truncate">{chip.label}</span>' in thread
    assert "exchange.draft.contextItems.length ? (" in thread, "a sent message must show its chips"

    for path in (THREAD_TSX, PLAN_REFERENCES_TS, PLAN_EDITOR_TSX):
        source = _read(path)
        assert "dangerouslySetInnerHTML" not in source, f"{path.name} writes HTML"
        assert "innerHTML" not in source, f"{path.name} writes HTML"

    plan = _read(PLAN_EDITOR_TSX)
    assert "references: entry.role === 'user' ? storedTurnReferences(entry.references) : undefined," in plan
    assert "scopeNoticeText(entry.scope_notice)" in plan

    print("  ok  the thread shows chips and notices as text")


def test_chips_are_never_lost():
    """Edit and resend restores chips, and so does a reply that did not use them."""
    thread = _read(THREAD_TS)
    assert "export function restoreAssistContext(" in thread
    assert re.search(
        r"function restoreDraft\([\s\S]*?addContextItem\(items, item\)[\s\S]*?reconcileContextItems\(text, merged\)",
        thread,
    ), "edit and resend must merge the exchange's chips into the input"

    plan = _read(PLAN_EDITOR_TSX)
    assert re.search(
        r"if \(references\.length && after && !after\.pending && after\.plan\.run_id === runBefore\) \{\s*"
        r"restoreAssistContext\(",
        plan,
    ), "a reply that neither revised the plan nor asked a question must hand the chips back"

    print("  ok  chips come back after Edit and resend and after a plain reply")


def test_escape_closes_the_picker_before_the_editor():
    """An open picker in the plan editor closes on Escape; the editor stays open."""
    picker = _read(PICKER_TSX)
    assert 'data-context-picker=""' in picker

    plan = _read(PLAN_EDITOR_TSX)
    escape = plan.index("if (event.key === 'Escape') {")
    guard = plan.index("dialogRef.current?.querySelector('[data-context-picker]')")
    close = plan.index("useOrchestrationStore.getState().setEditorTarget(null);", escape)
    assert escape < guard < close, "the editor must let an open picker take Escape first"

    print("  ok  Escape closes the picker before the editor")


def test_the_new_files_load_nothing_remote():
    """Browser code stays local: no remote URL and no dynamic import."""
    for path in (PLAN_REFERENCES_TS,):
        source = _read(path)
        assert not re.search(r"https?://", source), f"{path.name} references a remote URL"
        assert not re.search(r"\bimport\(", source), f"{path.name} uses a dynamic import"

    print("  ok  the new browser code loads nothing remote")


def test_the_typescript_logic_checks_pass():
    """Run the bundled behaviour checks, when the front-end toolchain is installed."""
    ui_dir = REPO_ROOT / "application" / "v2_ui"
    check = Path(__file__).with_name("test_v2_plan_references_logic.ts")

    assert check.exists(), "the logic check file is missing"

    if not (ui_dir / "node_modules").exists():
        print("  --  skipped the TypeScript checks: run npm install in application/v2_ui")
        return

    bundle = ui_dir / "node_modules" / ".cache-plan-references-check.mjs"
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
            encoding="utf-8",
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
    assert passed > 100, f"expected the full check suite, saw {passed} checks"
    print(f"  ok  {passed} TypeScript logic checks passed")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_only_the_plan_editor_offers_references,
    test_the_restricted_picker_offers_documents_and_tags_only,
    test_the_request_carries_canonical_references,
    test_the_browser_mirrors_the_server_limits,
    test_the_thread_shows_chips_as_text,
    test_chips_are_never_lost,
    test_escape_closes_the_picker_before_the_editor,
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
    print(f"\n{len(TESTS) - failures}/{len(TESTS)} tests passed")
    sys.exit(1 if failures else 0)
