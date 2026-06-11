# Foundry Auth-Required Stream Message Fix

Fixed/Implemented in version: **0.241.186**

## Issue Description

When a signed-in user needed Azure AI Foundry consent or access during a Foundry agent or workflow run, the chat stream failed with a generic Microsoft 365 consent message. The chat alert also discarded the structured `auth_url` and `consent_url` fields emitted by the backend, so the user saw a stream interruption without an actionable Foundry sign-in or consent link.

## Root Cause Analysis

Foundry delegated auth reused the shared plugin token helper, whose consent-required fallback text is written for Microsoft 365 plugins. The Foundry runtime passed that generic helper message through unchanged. On the client side, `chat-streaming.js` only passed the `error` string into the stream error renderer and interpolated it into an HTML alert, which prevented the Foundry-specific auth metadata from being displayed safely.

## Version Implemented

- Application version updated in `application/single_app/config.py` from `0.241.185` to `0.241.186`.

## Technical Details

### Files Modified

- `application/single_app/foundry_agent_runtime.py`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/config.py`
- `functional_tests/test_foundry_delegated_user_auth.py`

### Code Changes Summary

- Added a Foundry-specific delegated auth-required message for agents and workflows.
- Preserved the shared MSAL helper's consent URL, auth URL, and scope metadata while replacing only the generic Microsoft 365-facing message.
- Updated the chat streaming client to carry auth-required metadata from both SSE error events and non-OK JSON stream responses.
- Rendered the stream error banner with DOM APIs and `textContent`, and normalized the auth URL before assigning it to a link.

### Testing Approach

- Extended the Foundry delegated auth functional regression test to verify the Foundry-specific message, structured stream metadata handling, safe banner rendering, and version/fix documentation traceability.

## Impact Analysis

Users who need Foundry access during a chat run now see Foundry-specific guidance and a safe link to sign in or grant access. Microsoft 365 plugin consent messaging remains unchanged because the override is scoped to the Foundry runtime.

## Validation

Run:

```bash
python functional_tests/test_foundry_delegated_user_auth.py
node --check application/single_app/static/js/chat/chat-streaming.js
python -m py_compile application/single_app/foundry_agent_runtime.py functional_tests/test_foundry_delegated_user_auth.py
```
