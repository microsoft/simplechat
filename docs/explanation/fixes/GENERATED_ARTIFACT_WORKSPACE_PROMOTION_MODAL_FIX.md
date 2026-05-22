# Generated Artifact Workspace Promotion Modal Fix

Version: 0.241.096

Fixed/Implemented in version: **0.241.096**

## Issue Description

Generated artifact cards showed a warning toast saying users had to select exactly one workspace scope before using **Add to Workspace**. In a personal conversation, that was confusing because the conversation already had a clear personal workspace destination. In ambiguous scope states, the toast did not help users choose the right destination.

## Root Cause Analysis

The client promotion flow reused the document search scope filter as a hard validation gate. The search scope often defaults to all available workspaces, so a personal conversation could still appear to have multiple possible save targets. When more than one target was present, the flow stopped with a toast instead of offering a guided target selection.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_generated_artifact_workspace_promotion_modal.py`
- `ui_tests/test_chat_generated_tabular_output_card.py`

### Code Changes Summary

- Added conversation-aware target inference so personal, group, and public conversations prefer their own workspace scope.
- Added a Bootstrap confirmation modal for single inferred targets.
- Added a Bootstrap chooser modal when multiple save targets are genuinely possible.
- Removed the dead-end one-scope warning toast from the generated artifact promotion flow.
- Extended UI coverage for personal confirmation and ambiguous target selection.

## Testing And Validation

- Functional regression: `functional_tests/test_generated_artifact_workspace_promotion_modal.py`
- UI regression: `ui_tests/test_chat_generated_tabular_output_card.py`
- JavaScript syntax validation for `application/single_app/static/js/chat/chat-messages.js`

## Impact Analysis

- Personal conversation artifacts now default to a personal workspace confirmation.
- Ambiguous scope states now let users choose the destination directly from the promotion flow.
- Group and public conversation artifacts continue to target their conversation workspace and preserve the existing approval behavior.