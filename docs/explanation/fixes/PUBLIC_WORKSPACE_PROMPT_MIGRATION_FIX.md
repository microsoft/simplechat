# Public Workspace Prompt Migration Fix (v0.250.072)

Fixed in version: **0.250.072**

Related issue: [#1033](https://github.com/microsoft/simplechat/issues/1033)

Related config.py version update: `VERSION = "0.250.072"`

## Issue Description

Selected public-workspace Data Management migrations omitted current public prompt records. Current prompts are stored in `public_prompts` with their workspace ownership in `public_id`, while selected-scope migration used only the legacy `public_workspace_id` ownership field.

## Root Cause Analysis

The selected-scope Cosmos iterator generated one equality filter from each container definition's `filter_field`. The `public_prompts` definition still named `public_workspace_id`, so current prompts with only `public_id` never reached the migration copy path. All-workspaces migration did not use that selected-scope filter and was unaffected.

## Technical Details

### Files Modified

- `application/single_app/functions_data_management.py`
- `application/single_app/config.py`
- `functional_tests/test_data_management_public_prompt_migration.py`
- Data Management and version-contract functional tests
- `docs/explanation/release_notes.md`

### Code Changes Summary

- Added a compatibility-aware `filter_fields` contract for selected-scope Cosmos migration definitions while preserving existing single `filter_field` definitions.
- Configured `public_prompts` to match current `public_id` ownership first and legacy `public_workspace_id` ownership second.
- Builds a parameterized OR predicate for selected public-workspace prompt reads and deduplicates transitional records that contain both ownership fields by Cosmos document identity.
- Applied the same selected-scope matching and deduplication to destination reconciliation scans.
- Left all-workspaces migration on its existing unfiltered container-read path.

## Impact Analysis

Selected migrations now copy current and legacy prompts owned by selected public workspaces, exclude prompts owned by unselected workspaces, and count each copied prompt once. Existing user, group, and all-workspace migration behavior remains unchanged.

## Validation

- Focused regression coverage verifies current, legacy, transitional, unselected, and all-workspace public-prompt cases.
- The focused test asserts source-read and copied artifact counts for selected and all-workspace migrations.
- Relevant Data Management Cosmos migration, reconciliation, orchestration, and security/version checks are run with this change.