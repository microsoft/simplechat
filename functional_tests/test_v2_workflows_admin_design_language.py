#!/usr/bin/env python3
# test_v2_workflows_admin_design_language.py
"""
Functional test for the V2 Workflows workbench and editor in the Admin Settings design language.
Version: 0.261.266
Implemented in: 0.261.266

This test ensures that the V2 Workflows section keeps the shape it was redesigned into:

* The list is a workbench, as Admin's Model Catalog is: one-line rows beside the selected
  workflow's detail, with Overview, Runs and Flow tabs, rather than rows carrying every action.
* The editor is a page of its own in both personal and group workspaces, as Agents and Actions
  are, built from Admin's distinct section cards and its "On this page" index. The chat proposal
  card keeps the same editor in a dialog.
* The separate Flow dialog is gone; the Flow tab shows the saved definition.
* The editor and list addresses are built by the reviewed same-origin URL builders.

The behavioural half -- each card's status and facts, and the workbench's labels and filters --
lives in ``test_v2_workflows_workbench_logic.ts``, which this file bundles with esbuild and runs
under node, skipping when the front-end toolchain is absent.
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = REPO_ROOT / "application" / "v2_ui"
SRC = V2_DIR / "src"
WORKFLOWS_SECTION = SRC / "pages" / "workspace" / "WorkflowsSection.tsx"
EDITOR_PAGE = SRC / "pages" / "workspace" / "WorkflowEditorPage.tsx"
WORKSPACE_SECTIONS = SRC / "pages" / "workspace" / "sections.tsx"
WORKSPACE_PAGE = SRC / "pages" / "workspace" / "WorkspacePage.tsx"
GROUP_PAGE = SRC / "pages" / "GroupWorkspacePage.tsx"
EDITOR = SRC / "components" / "workflows" / "WorkflowEditorDialog.tsx"
DETAIL = SRC / "components" / "workflows" / "WorkflowWorkbenchDetail.tsx"
FIELD = SRC / "components" / "workflows" / "WorkflowField.tsx"
SECTION_CARD = SRC / "components" / "ui" / "SectionCard.tsx"
FLOW_DIALOG = SRC / "components" / "workflows" / "WorkflowFlowDialog.tsx"
RUN_LINK = SRC / "lib" / "workflowRunLink.ts"
THEME = SRC / "styles" / "theme.css"
XSS_GUARDRAIL = REPO_ROOT / "scripts" / "check_xss_sinks.py"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_workflows_workbench_logic.ts"

CHANGED_COMPONENTS = (
    WORKFLOWS_SECTION,
    EDITOR_PAGE,
    EDITOR,
    DETAIL,
    FIELD,
    SECTION_CARD,
    SRC / "components" / "workflows" / "WorkflowStatusChip.tsx",
    SRC / "components" / "workflows" / "WorkflowTaskFields.tsx",
    SRC / "components" / "workflows" / "WorkflowScheduleFields.tsx",
    SRC / "components" / "workflows" / "WorkflowFileSyncFields.tsx",
    SRC / "components" / "workflows" / "WorkflowAlertEditor.tsx",
    SRC / "components" / "workflows" / "WorkflowAlertSummary.tsx",
)


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def test_version_includes_the_redesign():
    """The workbench and the routed editor arrived in 0.261.266."""
    print("\nTesting the application version...")
    assert_app_version_at_least("0.261.266")
    print("  ok  version is at least 0.261.266")
    return True


def test_the_workflows_section_is_a_workbench():
    """Rows select a workflow; its actions and its runs belong to the detail beside the list."""
    print("\nTesting the Workflows workbench...")
    section = _read(WORKFLOWS_SECTION)
    detail = _read(DETAIL)

    assert '<ul aria-label="Workflows"' in section, "The workflow list must stay a named list"
    assert "aria-pressed={isSelected}" in section, "A row must say whether it is the selected workflow"
    assert "<WorkflowWorkbenchDetail" in section, "The selected workflow must be drawn by the detail pane"
    assert "WorkflowEditorDialog" not in section, "The list must not open the editor itself; the editor is a page"
    assert "navigate(workflowEditorHref(" in section, "Create and Edit must navigate to the editor page"
    assert "readWorkflowRunLink(location.search)" in section, "Run links must still select a workflow and its run"

    assert 'role="tablist" aria-label="Workflow details"' in detail
    for tab in ("overview: 'Overview'", "runs: 'Runs'", "flow: 'Flow'"):
        assert tab in detail, f"The detail is missing the tab {tab}"
    assert "<WorkflowRunHistory" in detail, "Runs must show the workflow's run history"
    assert "target={{ kind: 'saved', workflowId }}" in detail, "Flow must show the saved definition read-only"
    assert "definition_version === 3 ? ['overview', 'runs', 'flow']" in detail, (
        "Only structured workflows offer the Flow tab"
    )
    print("  ok  list rows select; the detail carries actions, Runs and Flow")
    return True


def test_the_editor_is_a_page_in_both_workspaces():
    """Personal and group workspaces route /workflows/<id|new> to the editor page."""
    print("\nTesting the routed editor...")
    sections = _read(WORKSPACE_SECTIONS)
    workspace = _read(WORKSPACE_PAGE)
    group = _read(GROUP_PAGE)
    page = _read(EDITOR_PAGE)

    workflows_entry = sections[sections.index("id: 'workflows'"):]
    workflows_entry = workflows_entry[:workflows_entry.index("id: 'identities'")]
    assert "layout: 'full'" in workflows_entry, "Workflows must use the full-width frame Agents and Actions use"
    assert "context.resourceId" in workflows_entry and "<WorkflowEditorPage" in workflows_entry
    assert re.search(r"\[\s*'agents',\s*'actions',\s*'workflows'\s*\]", workspace), (
        "The personal workspace must accept a workflow resource segment"
    )
    assert "section === 'workflows' && resourceId ? <WorkflowEditorPage" in group, (
        "The group workspace must route a workflow resource segment to the editor page"
    )
    assert "nativeWorkflows" in group, "The group Workflows section must be full-bleed like the other native sections"

    assert 'presentation="page"' in page, "The routed page must draw the editor as a page, not a dialog"
    assert "useBlocker(" in page, "Leaving the personal editor with unsaved changes must ask first"
    assert "workspaceEditorSaved: true" in page, "A save must return to the list without asking to discard"
    assert "workflowListHref(scope, saved.id ?? backTo)" in page, "A save must return with the saved workflow selected"
    print("  ok  /workflows/<id|new> is the editor page in personal and group workspaces")
    return True


def test_the_editor_uses_admin_cards_and_index():
    """The editor draws Admin's section card, field rows and On this page index."""
    print("\nTesting the editor's Admin design language...")
    editor = _read(EDITOR)
    card = _read(SECTION_CARD)
    field = _read(FIELD)
    theme = _read(THEME)

    assert "import { SectionCard }" in editor, "Editor cards must be the shared SectionCard"
    assert "SettingsIndex" in editor, "The editor page must offer Admin's On this page index"
    assert "workflowEditorSections(" in editor, "Card statuses must come from the tested section logic"
    assert "presentation === 'page'" in editor or "presentation = 'dialog'" in editor, (
        "The editor must still support the dialog presentation the chat proposal card uses"
    )

    assert "presentSectionStatus(" in card, "Cards must use Admin's status chip vocabulary"
    assert "admin-section-body" in card, "Cards must use Admin's section body so field rows lay out the same"
    assert "rounded-t-2xl border-b border-edge-strong bg-surface-2" in card, "Cards must keep Admin's header band"

    assert "admin-field" in field and "admin-field-heading" in field and "admin-field-control" in field, (
        "Workflow fields must use Admin's label-beside-control rows"
    )
    assert "admin-switch-row" in field, "Workflow switches must pair with their label as Admin's do"
    assert re.search(r"@container \(min-width: 50rem\) \{\s*\.admin-field,", theme), (
        "Admin's field layout must stay one shared rule in theme.css"
    )
    assert ".workflow-disclosure" in theme, "Task disclosures need their shared style"
    print("  ok  SectionCard, Admin field rows, switches and the index are shared")
    return True


def test_the_flow_dialog_is_retired():
    """The Flow tab replaced the separate Flow dialog; nothing may still import it."""
    print("\nTesting the retired Flow dialog...")
    assert not FLOW_DIALOG.exists(), "WorkflowFlowDialog.tsx should be removed"
    for path in SRC.rglob("*.ts*"):
        assert "WorkflowFlowDialog" not in path.read_text(encoding="utf-8"), f"{path} still references WorkflowFlowDialog"
    print("  ok  no source references the Flow dialog")
    return True


def test_editor_addresses_use_reviewed_url_builders():
    """The editor and list addresses are built in one place and reviewed as same-origin."""
    print("\nTesting the workflow address builders...")
    link = _read(RUN_LINK)
    guardrail = _read(XSS_GUARDRAIL)
    assert "export function workflowEditorHref(" in link
    assert "export function workflowListHref(" in link
    assert "encodeURIComponent(workflowId ?? NEW_WORKFLOW_RESOURCE)" in link, (
        "A workflow id must be encoded into its editor path"
    )
    builders = guardrail[guardrail.index("TS_SAME_ORIGIN_URL_BUILDERS"):]
    builders = builders[:builders.index("}")]
    for name in ("workflowEditorHref", "workflowListHref", "workflowRunHref"):
        assert re.search(rf"['\"]{name}['\"]", builders), f"{name} must be listed as a reviewed same-origin URL builder"
    print("  ok  workflowEditorHref and workflowListHref are reviewed builders")
    return True


def test_changed_components_follow_the_frontend_rules():
    """No inline display:none (Bootstrap d-none or conditional rendering instead) and no remote assets."""
    print("\nTesting the frontend rules on the changed components...")
    for path in CHANGED_COMPONENTS:
        content = _read(path)
        assert not re.search(r"display\s*:\s*['\"]?none", content), f"{path.name} sets display:none inline"
        assert "https://" not in content or "cdn" not in content.lower(), f"{path.name} references a remote asset"
        first_line = content.splitlines()[0]
        assert first_line == f"// {path.name}", f"{path.name} must start with its filename comment"
    print(f"  ok  {len(CHANGED_COMPONENTS)} components checked")
    return True


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("\nTesting workflow workbench and card logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where
    # node can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-workflows-workbench-check.mjs"
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
                # workflowEditor reaches the API client, which reads import.meta.env.
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
        test_version_includes_the_redesign,
        test_the_workflows_section_is_a_workbench,
        test_the_editor_is_a_page_in_both_workspaces,
        test_the_editor_uses_admin_cards_and_index,
        test_the_flow_dialog_is_retired,
        test_editor_addresses_use_reviewed_url_builders,
        test_changed_components_follow_the_frontend_rules,
        test_the_typescript_logic_checks_pass,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
