# Conversation Cache Invalidation Authorization Fix

Fixed/Implemented in version: **0.250.046**

## Issue Description

PR readiness validation flagged a direct personal conversation read in the message-mutation cache invalidation path. The read used a request-derived `conversation_id` before proving that the current caller owned the exact personal conversation.

## Root Cause Analysis

`_invalidate_conversation_cache_after_message_mutation(...)` loaded the conversation directly from `cosmos_conversations_container`. Although the helper only invalidated cache state, the direct read crossed an authorization boundary and bypassed the existing personal conversation ownership helper.

## Technical Details

Files modified:

* `application/single_app/route_backend_conversations.py`
* `functional_tests/test_chat_completion_notifications.py`
* `functional_tests/test_cosmos_wave3a_indexing_maintenance.py`
* `functional_tests/test_cosmos_wave3b_document_access_index.py`
* `functional_tests/test_cosmos_wave4a1_admin_document_access_ui.py`
* `functional_tests/test_cosmos_wave4a_document_access_backfill.py`
* `functional_tests/test_cosmos_wave4b_document_access_shadow_validation.py`
* `functional_tests/test_cosmos_wave5a_document_access_read_switch.py`

Code changes summary:

* Routed the cache invalidation conversation load through `_authorize_personal_conversation_read(user_id, conversation_id)`.
* Updated DAI functional test fake `config` modules to include the current document access index container imports.
* Updated the chat completion notification functional test to import app modules through a fake Cosmos client boundary so local regression tests do not reach live Cosmos configuration.

## Validation

Validation performed:

* `python scripts/check_broken_access_control.py --full-file application/single_app/route_backend_conversations.py`
* `python functional_tests/test_chat_completion_notifications.py`
* DAI functional tests covering indexing maintenance, write-through, admin UI, backfill, shadow validation, and read switch behavior.

Impact:

* Preserves cache invalidation behavior for authorized personal conversation mutations.
* Fails closed for unauthorized or missing conversations while still falling back to user-scoped cache version invalidation.