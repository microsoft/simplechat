# Web Research External Retrieval Priority Fix

Fixed/Implemented in version: **0.250.002**

## Issue Description

Explicit Web, URL Access, and Deep Research chat turns could be interrupted by the conversation citation experience. When workspace search was not selected, the chat backend could still inspect prior grounded conversation history and search previously cited workspace documents before honoring the external retrieval request.

## Root Cause Analysis

The standard and streaming chat routes used the history-grounded document fallback whenever workspace search was disabled. That fallback did not distinguish between a plain follow-up question and a turn where the user had explicitly selected Web, URL Access, or Deep Research.

Chat-upload workspace documents were also auto-merged into normal chat search context before external retrieval ran, which could make a Web or Research turn behave like a document-grounded turn.

## Technical Details

Files modified:

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_history_grounded_follow_up_fix.py`

Code changes:

- Added `explicit_external_retrieval_requested` handling for Web, URL Access, Source Review, and Deep Research requests.
- Added `_should_auto_merge_chat_upload_workspace_context` so uploaded workspace documents are not auto-linked into explicit external-retrieval-only turns.
- Updated history-grounded fallback guards in both standard and streaming chat paths so Web, URL Access, or Deep Research takes precedence over previously grounded document fallback.
- Updated `should_apply_history_grounding_message` so the final prompt does not add workspace-only grounding instructions during external retrieval turns.
- Updated conversation history preparation so prior assistant citation context is not injected into explicit Web, URL Access, or Deep Research turns.
- Updated `config.py` from `0.250.001` to `0.250.002`.

## Testing Approach

Updated `functional_tests/test_chat_history_grounded_follow_up_fix.py` to verify:

- Explicit external retrieval disables the history-grounding prompt.
- Web, URL Access, Source Review, and Deep Research all count as external retrieval.
- Chat-upload workspace context is not auto-merged for external-only turns.
- Prior assistant document citation context is omitted from external-retrieval history preparation.
- Both standard and streaming chat paths use the new history-grounded document fallback guard.

## Impact Analysis

When users explicitly select Web, URL Access, or Deep Research, those sources now take priority. Existing workspace search behavior is preserved when document search is explicitly active, and assigned knowledge workspace context can still participate when a selected agent requires it.

## Validation

Before the fix, a Web or Research request in a conversation with prior document citations could trigger history-grounded document assessment and workspace search first.

After the fix, explicit Web, URL Access, or Deep Research requests skip the history-grounded document fallback and proceed through external retrieval.