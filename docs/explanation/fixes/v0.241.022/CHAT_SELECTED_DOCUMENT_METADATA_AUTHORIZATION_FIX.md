# Chat Selected Document Metadata Authorization Fix

Fixed/Implemented in version: **0.241.017**

## Overview

This fix closes finding **f046** for chat-selected document metadata resolution.

Version implemented:
`config.py` now reports `VERSION = "0.241.017"` for this fix.

## Issue Description

- `/api/chat` accepted a caller-selected document id and looked up document metadata by raw id in the requested container.
- `/api/chat/stream` repeated the same raw lookup path.
- The selected tabular document helper in `route_backend_chats.py` also resolved explicit document selections by raw id across all-scope containers.
- That allowed document name and filename metadata from unauthorized personal, group, or public documents to enter chat metadata and tabular analysis context when the caller knew the document id.

## Root Cause Analysis

Authentication existed at route entry, but selected-document metadata resolution was not itself an authorization boundary.

- Personal selected documents were not constrained to the caller's owner or shared-user access.
- Group selected documents were not constrained to the caller's active authorized groups.
- Public selected documents were not constrained to the caller's visible public workspaces.
- Three separate selected-document lookup sites could drift because they did not share one scope-aware resolver.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_all_scope_group_source_context.py`
- `functional_tests/test_chat_selected_document_metadata_authorization.py`

### Code Changes Summary

- Added `_resolve_chat_selected_document_metadata(...)` in `route_backend_chats.py`.
- Personal document resolution now allows only:
  - owner access via `c.user_id = @user_id`
  - direct shared-user access via `ARRAY_CONTAINS(c.shared_user_ids, @user_id)`
  - prefixed shared-user access via `STARTSWITH(s, @user_id_prefix)`
- Group document resolution now allows only:
  - direct group ownership via `c.group_id = @group_id`
  - raw shared-group entries via `ARRAY_CONTAINS(c.shared_group_ids, @group_id)`
  - approved shared-group entries via `ARRAY_CONTAINS(c.shared_group_ids, @group_id_approved)`
- Public document resolution now allows only documents in authorized visible public workspace ids.
- Rewired `/api/chat`, `/api/chat/stream`, and `get_selected_workspace_tabular_file_contexts(...)` to use the shared resolver instead of raw id-only Cosmos lookups.
- Updated the existing tabular all-scope regression to pass authorized group and public workspace ids into the selected-document helper path.

## Validation

### Testing Approach

- Extended the existing all-scope tabular regression so it exercises the new authorization-aware selected-document path.
- Added a focused functional regression for personal foreign denial, personal shared allow, group raw shared allow, group approved shared allow, public visible allow, and public hidden deny.
- Validated the touched chat route module with targeted compile checks.

### Validation Results

- `python -m pytest functional_tests/test_tabular_all_scope_group_source_context.py -q`
- `python -m pytest functional_tests/test_chat_selected_document_metadata_authorization.py -q`
- `python -m py_compile application/single_app/route_backend_chats.py`
- `python -m py_compile functional_tests/test_tabular_all_scope_group_source_context.py`
- `python -m py_compile functional_tests/test_chat_selected_document_metadata_authorization.py`

## Before And After

Before:

- Selected document metadata lookups trusted caller-supplied document ids after authentication.
- Unauthorized document titles and filenames could be resolved into chat metadata or selected tabular context if the caller knew the document id.

After:

- Selected document metadata resolution is scoped to the caller's authorized personal, group, or public access.
- Chat and streaming metadata enrichment plus the selected tabular helper now share the same authorization-aware resolver.

## User Experience Impact

Authorized selected documents continue to work as before. The visible behavior change is the intended secure outcome: unauthorized selected document ids no longer resolve metadata into chat state or tabular analysis context.