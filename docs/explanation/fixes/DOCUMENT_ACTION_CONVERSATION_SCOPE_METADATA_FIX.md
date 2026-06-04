# Document Action Conversation Scope Metadata Fix

Fixed in version: **0.241.124**

## Issue Description

Analyze and tabular document-action conversations could complete against group or public workspace documents while the conversation badge and metadata still appeared personal.

## Root Cause Analysis

Document-action execution passes selected or analyzed document summaries into conversation metadata, but the metadata collector only derived workspace context from hybrid search results. Analyze and tabular document actions often do not have hybrid search results, especially when the selected workbook is opened directly by the tabular processing path. When the request scope was `all`, the collector did not have enough evidence to assign group or public primary context.

Streaming document-action responses also normalized the final payload without `context`, `chat_type`, or scope-lock fields, which could leave the live UI stale until a reload.

## Technical Details

Files modified:

- `application/single_app/functions_conversation_metadata.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_document_action_conversation_scope_metadata.py`

Code changes summary:

- Added selected-document metadata fallback so conversation context can be inferred from document-action analysis summaries when `search_results` is empty.
- Preserved the assigned-knowledge personal-agent rule so assigned public knowledge remains secondary to a personal primary context.
- Included document-action `context`, `chat_type`, `scope_locked`, and `locked_contexts` in streaming normalized payloads.

Testing approach:

- Added functional coverage for group selected-document metadata assigning a group primary context.
- Added regression coverage for personal agents with assigned public knowledge keeping personal primary context.
- Added static coverage for document-action streaming metadata fields.

## Impact Analysis

Group and public Analyze or tabular document-action turns now update conversation badges and scope lock metadata from the actual analyzed documents. Personal agents with assigned public knowledge continue to show personal conversation context as intended.

## Validation

Run:

```bash
python functional_tests/test_document_action_conversation_scope_metadata.py
python -m py_compile application/single_app/functions_conversation_metadata.py application/single_app/route_backend_chats.py
```

Version updated in `application/single_app/config.py` from `0.241.123` to `0.241.124`.