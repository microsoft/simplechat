# Personal Conversation Read Authorization Fix

Finding reference: **f024** — `GET /api/get_messages` returns full message history of any conversation without ownership check.

## Overview

This fix closes an authenticated broken-object-level-authorization gap in the personal conversation read APIs and hardens the adjacent image retrieval path that exposed the same conversation data boundary.

Version implemented:
`config.py` now reports `VERSION = "0.241.011"` for this fix.

## Issue Description

- `GET /api/get_messages` trusted the caller-supplied `conversation_id`, loaded the conversation record, and returned the full message history without confirming that the authenticated user owned that conversation.
- `GET /api/image/<image_id>` reconstructed `conversation_id` from `image_id` and served image content from that conversation without an ownership check.
- Both routes were protected only by authentication and role decorators, which do not provide object-level authorization for a specific conversation resource.
- This note tracks the execution-verified remediation for the adjacent image-read path hardened in the same change set.

## Root Cause

- Route entry authentication was present.
- The read handlers trusted conversation identifiers derived from request input.
- Existing sibling handlers in the same route module enforced `conversation_item['user_id'] == user_id`, but these two read paths omitted that check.

## Technical Changes

### Personal Conversation Read Authorization Helper

Changes implemented:

- Added `_authorize_personal_conversation_read(...)` to `route_backend_conversations.py`.
- The helper loads the personal conversation and fails closed when the current user does not own it.
- The helper returns a `LookupError` for missing conversations and a `PermissionError` for foreign-owned conversations so the caller can preserve endpoint-specific response contracts.

Security outcome:

Personal conversation reads now pass through a single explicit ownership gate before any message or image query executes.

### Message History Authorization

Changes implemented:

- Updated `api_get_messages` to authorize the conversation before querying `cosmos_messages_container`.
- Foreign conversation access now returns `403 Forbidden`.
- Missing conversations preserve the prior empty-message payload contract.

Security outcome:

Authenticated users can no longer read another user's personal chat transcript by supplying a leaked `conversation_id`.

### Image Retrieval Authorization

Changes implemented:

- Updated `api_get_image` to authorize the reconstructed `conversation_id` before querying image records.
- Foreign conversation image reads now return `403 Forbidden`.
- Missing conversations and missing images continue to return `404` for that endpoint.

Security outcome:

Authenticated users can no longer fetch inline or chunked image content from another user's personal conversation by supplying a foreign image id.

## Files Modified

- `application/single_app/route_backend_conversations.py`
- `functional_tests/test_conversations_read_ownership_authorization.py`
- `application/single_app/config.py`

## Validation

Testing approach:

- Added a focused functional regression that registers the conversation routes with in-memory containers and verifies owner success plus foreign-user `403` behavior for both message and image read paths.
- Verified that foreign requests fail before the message container is queried.
- Preserved the legacy missing-conversation and missing-image response contracts in the regression coverage.

Validation performed for this implementation:

- `python functional_tests/test_conversations_read_ownership_authorization.py`
- `python -m py_compile application/single_app/route_backend_conversations.py`
- `python -m py_compile functional_tests/test_conversations_read_ownership_authorization.py`