# V2 Workflows Workbench and Editor

## Overview

The V2 Workflows section now uses the design language of V2 Admin Settings. Before this change,
each workflow was a card in a long list that carried every action -- Run, Cancel, Edit, Delete,
View Flow and Show run history -- and run history expanded inline under the card, so a workspace
with a few workflows became a long scroll of buttons. The editor was a modal dialog with one long
column of controls, where a label sat above its control and a setting that only mattered when
another was on looked the same as everything else.

Workflows now reads the way Admin Settings does:

- **A workbench for the list**, drawn like Admin's Model Catalog. Each workflow is one line --
  its name, how it stands in words (such as **Running**, **Awaiting approval** or **Failed**) with
  a matching icon, and its trigger in a word or two -- beside a detail pane for the selected
  workflow. The detail holds the workflow's actions and
  three tabs: **Overview**, **Runs** and, for structured workflows, **Flow**.
- **A page for the editor**, as Agents and Actions already have. It opens at its own address in
  both personal and group workspaces, uses Admin's wide frame, and lays the workflow out in
  distinct section cards with Admin's status chips, label-beside-control fields, paired switches,
  nested dependent settings, and an **On this page** index.

Nothing about what a workflow can do changed. The same fields are saved in the same shape, run
inspection is unchanged inside the Runs tab, and the chat **Proposed workflow** card still opens
the same editor in a dialog.

## Implemented in version: **0.261.266**

The application version is maintained in `application/single_app/config.py`.

**Dependencies:** the React/TypeScript V2 UI, React Router (`useBlocker` for the leave prompt),
local `lucide-react` icons, and the Admin Settings primitives (`SettingsIndex`, the section status
vocabulary in `adminSections.ts` and `sectionStatusPresentation.ts`, and the `.admin-field` rules
in `theme.css`). No new packages, settings, API routes, or browser asset sources are required.

## Technical specifications

### Architecture

| File | Responsibility |
| --- | --- |
| `application/v2_ui/src/pages/workspace/WorkflowsSection.tsx` | The workbench: intro, search, Status and Trigger filters, the one-line list, selection, run links, and the Run, Cancel and Delete requests. |
| `application/v2_ui/src/components/workflows/WorkflowWorkbenchDetail.tsx` | The selected workflow: header, actions, and the Overview, Runs and Flow tabs. |
| `application/v2_ui/src/components/workflows/WorkflowStatusChip.tsx` | The status chip in Admin's chip style, with a compact icon-only form for list rows. |
| `application/v2_ui/src/lib/workflowWorkbench.ts` | Status words and tones, attention, filters, row and detail lines, and the Overview facts. |
| `application/v2_ui/src/pages/workspace/WorkflowEditorPage.tsx` | The routed editor page: loads the workflow and editor options, gates editing, and returns to the list after a save or close. |
| `application/v2_ui/src/components/workflows/WorkflowEditorDialog.tsx` | The editor itself, drawn as a page (`presentation="page"`) or, for the chat proposal card, a dialog. |
| `application/v2_ui/src/lib/workflowEditorSections.ts` | Which cards a draft shows, each card's status and line of facts, and the task checks they share. |
| `application/v2_ui/src/components/ui/SectionCard.tsx` | Admin's section card for surfaces outside Admin: header band, icon, title, facts, status chip. |
| `application/v2_ui/src/components/workflows/WorkflowField.tsx` | Field rows, read-only values, paired switches, and the primary and dependent emphasis, built on `.admin-field`. |
| `application/v2_ui/src/lib/workflowRunLink.ts` | `workflowListHref`, `workflowEditorHref` and the existing run links. |

`WorkflowFlowDialog.tsx` is removed: the Flow tab shows the saved definition with the same
read-only `WorkflowFlowView`.

### Addresses

| Address | Shows |
| --- | --- |
| `/v2/workspace/workflows` | The workbench, with the first workflow selected. |
| `/v2/workspace/workflows?workflow_id=<id>` | The workbench with that workflow selected on Overview. |
| `/v2/workspace/workflows?workflow_id=<id>&run_id=<run>` | That workflow's Runs tab with the run expanded. Chat run cards, notices, alerts and document provenance links use this form, unchanged. |
| `/v2/workspace/workflows/<id>` | The editor page for that workflow. |
| `/v2/workspace/workflows/new` | The editor page for a new workflow. |

A group workspace uses the same forms under `/v2/groups/<group id>/workflows`. Until this
version, `?workflow_id=<id>` opened the editor dialog, and a group workflow resource segment was
rewritten to that query; the segment is now the editor page itself. Every address is built by
the reviewed same-origin builders in `workflowRunLink.ts`, which `scripts/check_xss_sinks.py`
lists.

### Card status

Each editor card carries Admin's status vocabulary, decided in `workflowEditorSections.ts`:

| Card | Status |
| --- | --- |
| Basics | **Needs configuration** without a name, with an agent runner and no agent, or with no explicit model when the app default model is not valid here; otherwise **Configured**. |
| Trigger and schedule | **Off** when **Workflow enabled** is off; otherwise **Configured**. |
| File Sync | **Off** when the workflow does not sync; **Prerequisite missing** when the group has File Sync turned off; **Needs configuration** with no sources; otherwise **Configured**. |
| Execution, Shared references, Limits | Facts only, no chip. Limits appears for structured workflows only. |
| Tasks | **Needs configuration** with no tasks or when any task shows its own problem. |
| Alerts | **Off**, **Needs configuration** for conditional alerts with no rules or with a rule the alert checks refuse, otherwise **Configured**. |

A status is guidance only. It never blocks a save: the editor's validation still decides that,
and its messages are listed above the cards.

### Workflow status

The workbench reads a workflow's status the way the server records it. While a run is in
progress, the workflow's `status` says so (`running`, `queued`, or a waiting state such as
`awaiting_approval`). When the run ends, the server sets `status` back to `idle` and records the
outcome in `last_run_status`, so a finished workflow shows how its last run ended, such as
**Completed**, **Completed with task errors**, **Failed** or **Cancelled**. An older record that
kept the outcome in `status` reads the same way.

**Needs attention** lists workflows that wait on a person (an approval or a sign-in), and those
whose last run failed, was cancelled or completed with task errors and that are not running
again. The Overview's **Last run** names the outcome and when the run ended, in the reader's
locale, or says **Not run yet**.

### Leaving the editor

Saving returns to the list with the saved workflow selected and a short **Workflow saved.** status,
as Agents does. Closing a pristine editor returns
at once. Leaving with unsaved changes -- **Cancel**, **Back**, another link, or the browser's back
button -- asks the workspace leave prompt (**Keep editing** or **Discard changes**). In a group
workspace, the group page owns that prompt, as it does for the group's other editors. Returning
moves focus to the edited workflow's heading in the workbench.

### Accessibility

- List rows are toggle buttons (`aria-pressed`) in a list named **Workflows**, with arrow-key,
  Home and End movement and one tab stop. A row's status and trigger are its description. On a
  narrow screen, where the detail sits under the list, choosing a row scrolls the detail into
  view and leaves focus on the row.
- The Status and Trigger filters are labelled by reference, so each is named by its label alone.
- The detail is an `article` named by the workflow; its tabs follow the ARIA tabs pattern with
  arrow keys, Home and End.
- The editor page is a region named **Edit workflow** or **Create workflow**. Its title takes
  focus on arrival. **On this page** moves focus to the chosen card's title, without smooth
  scrolling when reduced motion is requested. Converting to structured control flow moves focus to
  the converted tasks card, since the button that asked is gone with the ordered tasks.
- A failed editor load is announced as an alert, with **Retry**.
- Each card is a region named by its title, so the existing names **Workflow basics**,
  **Workflow shared references**, **Workflow tasks** and **Alerts** still identify them.

## Usage

Open **My workspace > Workflows** in V2, or a group's **Workflows**. Search, or filter by status
(**Running**, **Needs attention**, **Completed**, **Disabled**) or trigger, then select a
workflow. **Overview** summarises its settings, **Runs** lists its recent runs and their results,
and **Flow** shows a structured workflow's saved definition. **Edit** opens the editor page;
**Create workflow** opens it for a new workflow. See
[Create a workflow](../../guides/create-a-workflow.md#create-or-edit-in-v2) and
[Trigger a workflow](../../guides/trigger-a-workflow.md).

## Testing and validation

- `functional_tests/test_v2_workflows_workbench_logic.ts`, run by
  `functional_tests/test_v2_workflows_admin_design_language.py`, executes every card status and
  line of facts, the status words, the filters, and the Overview facts against the real modules.
- `functional_tests/test_v2_workflows_admin_design_language.py` also pins the workbench, the
  routed editor in both workspaces, the shared Admin primitives, the retired Flow dialog, and the
  reviewed address builders.
- `ui_tests/test_v2_workflows_workbench_and_editor_layout.py` drives the built SPA: one-line
  rows, keyboard list and tabs, run links, card statuses and the index, label-beside-control and
  stacked fields, the leave prompt, the return after a save, and no overflow at 390px and at
  1920px with 200% text, in light and dark themes.
- The existing workflow UI suites (`ui_tests/test_v2_workflow_*.py`,
  `ui_tests/test_v2_group_workflow_file_sync.py`, `ui_tests/test_v2_group_workspace_shell.py`
  and others) now reach workflows through the shared helpers in
  `ui_tests/fixtures/workflow_workbench.py`.

### Known limitations

- The editor page loads the workflow from the scope's workflow list; there is no single-workflow
  read, so a very large list is read in full to open one workflow.
- The workbench keeps its selection in the page, not the address; reload returns to the first
  workflow unless the address names one.

Related: [V2 Admin Settings Layout and Hierarchy](V2_ADMIN_SETTINGS_LAYOUT_AND_HIERARCHY.md),
[V2 Model Catalog Workbench](V2_MODEL_CATALOG_WORKBENCH.md),
[V2 Group Workflows](V2_GROUP_WORKFLOWS.md).
