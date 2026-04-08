# Personal Prompt Helper User Id Fix

Fixed/Implemented in version: **0.239.206**

## Issue Description

Personal prompt retrieval, update, and delete operations started failing after the shared prompt helper was refactored to support more workspace scopes. The create and list flows still worked, which made the regression easy to miss until users tried to reopen or edit an existing personal prompt.

## Root Cause Analysis

The shared helper in `functions_prompts.py` deleted the `user_id` argument at the top of `_get_prompt_doc_with_container()`. The public and group branches did not need that variable, but the personal-scope fallback still used `user_id` to constrain the lookup. Once execution reached that branch, Python raised an `UnboundLocalError` instead of resolving the user-scoped prompt.

## Technical Details

Files modified:

- `application/single_app/functions_prompts.py`
- `application/single_app/config.py`
- `functional_tests/test_personal_prompt_helper_user_id_fix.py`

Code changes summary:

- Removed the local deletion of `user_id` from `_get_prompt_doc_with_container()`.
- Added a regression test that executes personal prompt create, get, update, and delete behavior against stub Cosmos containers.
- Bumped `config.py` to version `0.239.206`.

## Testing Approach

Functional validation was added in `functional_tests/test_personal_prompt_helper_user_id_fix.py`.

The test verifies:

- personal prompt create, get, update, and delete flows work through the shared helper without raising runtime errors
- prompt ownership remains scoped to the caller user ID
- non-owner update and delete attempts continue to fail safely
- the application version is updated to `0.239.206`

## Impact Analysis

Before:

- personal prompt GET, PATCH, and DELETE flows could return 500 errors
- prompt ownership checks in the shared helper never reached their intended personal-scope branch

After:

- personal prompt CRUD lookups resolve correctly through the shared helper
- owner-only behavior is preserved for personal prompts
- the regression is covered by a focused helper-level functional test

## Validation

Test results:

- `functional_tests/test_personal_prompt_helper_user_id_fix.py`

User experience improvements:

- users can reopen, edit, and delete their saved personal prompts again without server errors