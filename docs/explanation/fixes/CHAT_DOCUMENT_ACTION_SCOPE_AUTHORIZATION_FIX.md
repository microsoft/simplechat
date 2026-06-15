# Chat Document Action Scope Authorization Fix

Fixed in version: **0.241.209**

## Issue Description

Chat document actions could carry caller-provided group or public workspace scope ids into document analysis and comparison flows after basic action normalization. Normal chat Search already filtered these ids through the authorized chat scope context, but the document-action path had a separate execution route and did not apply the same boundary before invoking the workflow runner.

## Root Cause Analysis

The document-action route trusted normalized `active_group_ids` and `active_public_workspace_id` values as execution inputs. The workflow search/document context helpers also accepted explicit group and public workspace ids without intersecting them with the current user's access. A related tabular evidence helper could build a related-document catalog from invocation-supplied group or public workspace ids before evidence lookup.

## Technical Details

Files modified:

- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_search_service.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_upload_personal_workspace_handoff.py`

Code changes:

- Document actions now revalidate requested group and public workspace ids with `_get_authorized_chat_scope_context()` before analysis or comparison execution.
- Unauthorized document-action scopes return a 403 response instead of being passed to the workflow runner.
- Document-action selected document metadata now resolves through `_resolve_chat_selected_document_metadata()` so display names use the same scoped lookup model as normal chat search metadata.
- Shared search-service helpers now intersect explicit group ids with the user's current group memberships and public workspace ids with the user's visible public workspace ids.
- Tabular related-document evidence augmentation now refuses group/public ids that are not present in the request's authorized chat context before building related-document catalogs.

## Testing Approach

Functional test coverage was extended in `functional_tests/test_chat_upload_personal_workspace_handoff.py` with source-contract assertions for:

- Document-action scope revalidation.
- 403 rejection of unauthorized group/public workspace ids.
- Safe selected-document metadata resolution.
- Shared search-service group/public scope filtering.
- Authorized tabular related-document scope handling.

## Impact Analysis

This closes a route-level access-control gap for Analyze and Compare without changing the intended behavior for authorized personal, group, public, assigned-knowledge, or uploaded task document flows. Users can still analyze documents they are allowed to access, but cannot cause the chat backend to search or analyze another group's or hidden public workspace's documents by supplying ids directly.

## Validation

Before this fix, document-action scope ids were trusted after normalization. After this fix, document-action and shared search-service paths revalidate group/public ids at the server boundary and at the shared document context layer.

Related version update: `application/single_app/config.py` was updated to **0.241.209**.