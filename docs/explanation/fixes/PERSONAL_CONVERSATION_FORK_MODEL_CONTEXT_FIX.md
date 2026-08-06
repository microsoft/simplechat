# Personal Conversation Fork Model Context Fix

Fixed/Implemented in version: **0.250.107**

## Issue Description

Personal conversations that only had the built-in "Model's knowledge" context could be rejected during fork creation with an unsupported workspace context conflict, even though they were not group or public workspace conversations.

## Root Cause Analysis

The fork authorization helper revalidated every stored context as either personal, group, or public. Conversation metadata stores model knowledge as a secondary context with scope `Model` and id `N/A`, so the fork helper interpreted it as an unsupported workspace context instead of treating it as model-only personal context.

## Technical Details

Files modified:
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/config.py`
- `functional_tests/test_conversation_fork.py`

Code changes summary:
- Added model and model-knowledge scopes to the personal fork context allow-list.
- Preserved group and public workspace revalidation behavior for real workspace contexts.
- Updated `config.py` from version `0.250.106` to `0.250.107` for traceability.

Testing approach:
- Added a regression test covering personal forks whose only stored context is model knowledge.
- Covered both the stored `Model` scope with `N/A` id and the normalized `model_knowledge` form.

## Validation

Expected behavior after the fix:
- Personal model-only conversations can be forked successfully.
- The fork preserves the source model-knowledge context.
- Group and public workspace conversations still require the existing workspace availability and access checks.
