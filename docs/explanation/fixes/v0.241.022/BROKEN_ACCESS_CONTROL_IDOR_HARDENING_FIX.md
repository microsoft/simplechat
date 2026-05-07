# Broken Access Control IDOR Hardening Fix

Fixed/Implemented in version: **0.241.010**

## Overview

This fix closes three authenticated broken-access-control paths that remained open after the earlier authorization hardening pass:

Version implemented:
`config.py` now reports `VERSION = "0.241.010"` for this fix.

## Issue Description

The application authenticated users at route entry, but later code paths still trusted identifiers supplied by the client request or by the LLM tool call. That created three horizontal authorization gaps:

- `/api/chat` and `/api/chat/stream` could read and continue another user's conversation when the caller knew its id.
- Tabular blob resolution could be steered toward another scope by forged tool-call parameters.
- Fact-memory reads and writes could be redirected to another user's or group's partition by forged tool-call parameters.

## Root Cause

- Route entry authentication was present.
- Sensitive later-stage operations reused caller-controlled identifiers.
- Server-side code treated prompt or tool-call arguments as if they were authorization decisions.
- Plugin execution relied on prompt guidance rather than a canonical request-scoped authorization context.

## Technical Changes

### Personal Conversation Ownership Enforcement

Changes implemented:

- Added `_authorize_personal_conversation_access(...)` to load a personal conversation and fail closed when the current user does not own it.
- Added `_create_personal_conversation(...)` and `_resolve_or_create_authorized_personal_conversation(...)` so new conversations are created server-side only when the request did not supply an id.
- Updated `/api/chat` to return `404` for unknown caller-supplied conversation ids and `403` for foreign conversations instead of creating a replacement conversation under the attacker-controlled id.
- Updated `/api/chat/stream` to authorize a caller-supplied conversation id before `CHAT_STREAM_REGISTRY.start_session(...)` is created.
- Updated the streaming generator to reuse the same ownership check before loading an existing conversation.

Files involved:

- `application/single_app/route_backend_chats.py`

Security outcome:

Personal chat requests can no longer read from or write into another user's conversation by supplying a foreign `conversation_id`.

### Canonical Chat Scope Filtering

Changes implemented:

- Added `_normalize_requested_scope_ids(...)` and `_get_authorized_chat_scope_context(...)`.
- Filtered `active_group_id`, `active_group_ids`, `active_public_workspace_id`, and `active_public_workspace_ids` to the current user's real access at request entry.
- Removed the prior fallback that restored the raw request `active_group_id` when the validated list was empty.
- Reused the same scope-filtering helper inside `revalidate_prior_grounded_document_search_parameters(...)` so request-entry scope filtering and fallback-history scope filtering now follow the same authorization boundary.
- Added `_set_authorized_chat_request_context(...)` to persist the canonical user, conversation, group, public workspace, and fact-memory scope context for downstream plugin authorization.

Files involved:

- `application/single_app/route_backend_chats.py`

Security outcome:

Caller-controlled scope ids no longer survive request normalization when the caller lacks access to those scopes.

### Tabular Processing Plugin Scope Binding

Changes implemented:

- Added `_get_authorized_chat_context(...)` and `_resolve_authorized_scope_arguments(...)` to `TabularProcessingPlugin`.
- Bound tabular tool execution to the authenticated request user and authorized conversation context.
- Rejected forged `group_id` and `public_workspace_id` values that are not currently authorized for the user.
- Stopped trusting remembered blob-path overrides unless the remembered blob location still resolves inside the current request's authorized scope.
- Updated `list_tabular_files(...)` to fail closed when the request tries to enumerate an unauthorized group or public workspace.
- Updated `_resolve_blob_location_with_fallback(...)` so all blob reads now pass through the request-scoped authorization boundary before blob existence checks or downloads begin.

Files involved:

- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`

Security outcome:

Tabular tool calls can no longer pivot into another user's workspace, another conversation's chat upload path, another group's blob prefix, or another public workspace's blob prefix by forging tool-call scope parameters.

### Fact Memory Plugin Scope Binding

Changes implemented:

- Added `_get_authorized_fact_memory_scope(...)` and `_resolve_authorized_fact_memory_call(...)` to `FactMemoryPlugin`.
- Derived the fact-memory scope from the canonical request authorization context instead of the LLM tool call.
- Updated `set_fact(...)`, `update_fact(...)`, `delete_fact(...)`, and `get_facts(...)` to use only the authorized request scope when calling `FactMemoryStore`.
- Overrode forged `scope_id`, `scope_type`, and `conversation_id` values with the request-authorized values and logged the mismatch for diagnostics.

Files involved:

- `application/single_app/semantic_kernel_plugins/fact_memory_plugin.py`

Security outcome:

Fact memory can no longer be read, written, updated, or deleted across users or groups by forging tool-call scope ids.

## Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/semantic_kernel_plugins/fact_memory_plugin.py`
- `application/single_app/config.py`
- `functional_tests/test_security_authorization_hardening.py`

## Validation

Testing approach:

- Extended the existing security authorization regression test to cover personal conversation ownership enforcement, request-entry scope canonicalization, tabular plugin request-scope binding, fact-memory request-scope binding, and the new fix document/version target.
- Validated the touched Python files with targeted `py_compile` runs during implementation.

Validation performed for this implementation:

- `python -m py_compile application/single_app/route_backend_chats.py`
- `python -m py_compile application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `python -m py_compile application/single_app/semantic_kernel_plugins/fact_memory_plugin.py`
- `python functional_tests/test_security_authorization_hardening.py`

## Before And After

Before:

- `/api/chat` and `/api/chat/stream` trusted caller-supplied personal conversation ids.
- Request scope normalization could still preserve raw single-value group or public workspace ids.
- Tabular tool calls trusted prompt-controlled scope ids for blob resolution.
- Fact-memory tool calls trusted prompt-controlled scope ids for Cosmos partition access.

After:

- Personal conversation access is bound to the authenticated owner.
- Request scope ids are canonicalized against current group membership and visible public workspace access before downstream processing.
- Tabular blob access is bound to the canonical request user and currently authorized group/public scopes.
- Fact-memory access is bound to the canonical request scope.

## User Experience Impact

Normal authorized chat, tabular analysis, and fact-memory behavior stays the same. The visible changes are the expected security-correct outcomes:

- Unauthorized personal conversation ids now fail with `403` or `404`.
- Unauthorized group and public workspace scope ids are dropped from chat request context.
- Unauthorized tabular tool calls return a scoped authorization error instead of silently reading another scope.
- Fact-memory tool calls now operate only on the caller's authorized scope.