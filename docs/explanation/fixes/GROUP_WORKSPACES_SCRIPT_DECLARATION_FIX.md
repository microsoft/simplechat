# Group Workspaces Script Declaration Fix

Fixed in version: **0.241.113**

## Issue Description

Opening the Group Workspaces page could fail during browser parsing with `Uncaught SyntaxError: Identifier 'access' has already been declared`. When this happened, the group workspace script stopped before the page finished initializing.

## Root Cause

The group document row renderer declared `const access` twice in the same block. The same access-state change also left duplicate `canChat` and `canRemove` declarations and read `groupStatus` before it was declared. The folder document table had related shared-document access checks that used `access` and `canRemove` without declaring them in the per-document loop.

## Technical Details

Files modified:

- `application/single_app/templates/group_workspaces.html`
- `application/single_app/config.py`
- `functional_tests/test_group_workspace_script_declarations.py`
- `ui_tests/test_group_workspaces_page_script_errors.py`

Code changes summary:

- Consolidated group document row access flags so `access`, `groupStatus`, `canModify`, `canChat`, and `canRemove` are each declared once in the row setup block.
- Reused those access flags when building row chat, edit, approve, remove, share, and delete actions.
- Added per-document access flag declarations in the group folder documents table before approval and remove actions are rendered.
- Updated the application version from `0.241.112` to `0.241.113`.

Testing approach:

- Added a functional regression test that statically verifies the relevant group workspace declaration blocks do not redeclare block-scoped constants.
- Added a Playwright UI regression test that loads `/group_workspaces` and fails if the page script does not initialize the document rendering functions.

## Validation

Before:

- The browser rejected the Group Workspaces inline script with `Identifier 'access' has already been declared`.
- Document row rendering could not initialize, leaving the page unusable.

After:

- The inline script parses with a single access declaration per row setup block.
- Group workspace document renderers initialize again, including folder table rendering for shared-document access states.