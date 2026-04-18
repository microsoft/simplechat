# Workflow Container Config Import Fix (v0.241.026)

Fixed/Implemented in version: **0.241.026**

## Issue Summary

SimpleChat could fail during startup when the workflow scheduler imported `functions_personal_workflows.py` because `config.py` exported `cosmos_personal_workflow_container` while the workflow module imported `cosmos_personal_workflows_container`.

## Root Cause

- The workflow definitions container in `config.py` used a singular export name that did not match the plural symbol imported by the workflow helpers.
- The manual container definitions also used partition keys that did not match the workflow storage code.
- `functions_personal_workflows.py` reads, queries, and deletes both workflow definitions and workflow runs with `partition_key=user_id`, so `/id` and `/workflow_id` partition keys would have broken workflow CRUD even after the import error was resolved.

## Files Modified

- `application/single_app/config.py`
- `functional_tests/test_personal_workflows_feature.py`
- `functional_tests/test_workflow_agent_selection_fix.py`
- `functional_tests/test_workflow_container_config_fix.py`

## Code Changes Summary

1. Renamed the exported workflow definitions container to `cosmos_personal_workflows_container` so it matches the runtime import contract.
2. Switched both workflow containers to `/user_id` partition keys so reads, writes, queries, and deletes line up with the workflow helper code.
3. Removed the singular workflow-container alias so the repo now follows the one-name-per-container rule consistently.
4. Added focused regression coverage for the config export and partition-key contract.

## Validation

- Targeted functional tests now verify the plural workflow export name and the `/user_id` partition keys.
- The workflow startup import path can now resolve `functions_personal_workflows.py` without the missing-config-symbol failure.

## Impact

- The app can start with workflow support enabled.
- Workflow definitions and workflow runs now use the same user-scoped partitioning assumed by the workflow storage helpers.
- The fix avoids a second runtime failure mode where CRUD would have broken even if the original import error had been patched locally.