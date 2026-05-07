# TABULAR RELATED DOCUMENT SCOPE FIX

Fixed in version: **0.241.140**

## Issue Description

Tabular rows that referenced uploaded PDFs or DOCX files by filename could fail to resolve those attachments in group or public workspace chats. Users could see the filename in the CSV row, but the final tabular output and citations still behaved as if the attachment text was unavailable.

## Root Cause Analysis

- The related-document augmentation path in `route_backend_chats.py` depended on `group_id` or `public_workspace_id` being present in the logged tabular tool invocation parameters.
- In real group/public chat runs, tool invocations could log `source="group"` or `source="public"` without the concrete scope ID.
- When that happened, the related-document catalog query had no authorized scope ID to search against, so it built an empty catalog and never matched the referenced attachment filenames.

## Version Implemented

- **0.241.140**

## Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_related_document_evidence.py`

## Code Changes Summary

- Added a fallback that recovers the active authorized group/public scope from `g.authorized_chat_context` when the tabular invocation omits the concrete scope ID.
- Kept the fallback tied to the current authorized user and conversation before reusing that scope.
- Added a focused regression that verifies the related-document helper can recover group/public scope IDs from the authorized chat context.

## Testing Approach

- Ran `pytest functional_tests/test_tabular_related_document_evidence.py`
- Ran `python -m py_compile application/single_app/route_backend_chats.py`

## Impact Analysis

- Group/public tabular runs can now resolve row-level `File Name` references like `114100JosephJanuszewski.pdf` against uploaded workspace documents.
- Resolved attachment excerpts flow back into tabular exports, prompt handoff summaries, and tool citations instead of being silently dropped.
- The change is scoped to request-authorized chat contexts and does not widen document lookup beyond the active authorized scope.

## Validation

- Before: a row could reference an uploaded PDF or DOCX filename, but the related-document catalog stayed empty because the scope ID was missing from the tool invocation metadata.
- After: the helper reuses the authorized active group/public scope, finds the matching document catalog entry, and makes that attachment available to the tabular evidence pipeline.