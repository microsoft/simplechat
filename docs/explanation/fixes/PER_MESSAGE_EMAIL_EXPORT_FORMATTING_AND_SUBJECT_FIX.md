# Per-Message Email Export Formatting And Subject Fix

Fixed/Implemented in version: **0.240.079**

## Issue Description

Per-message "Open in Email" drafts used the raw message text directly in `mailto:`. Assistant responses could arrive with markdown syntax in the email body, and the subject line always fell back to a generic sender-based label even when the message already contained a subject or title.

## Root Cause Analysis

The email export path lived entirely in the frontend and read message content from the DOM. That meant it had no shared formatting pipeline with the backend Word export helpers and no access to the shared GPT initialization used for conversation summary generation.

Because the client built the mailto draft directly from the raw markdown, the body preserved markdown source instead of a document-style layout, and the subject line could not be inferred or generated from the message content.

## Technical Details

### Files Modified

- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/static/js/chat/chat-message-export.js`
- `application/single_app/config.py`
- `functional_tests/test_per_message_export.py`
- `docs/explanation/features/MESSAGE_EXPORT.md`

### Code Changes Summary

- Added `POST /api/message/export-email-draft` to build a mailto-ready subject and body on the backend.
- Reused the message export lookup path so Word and email exports pull the same message data and hydrated citations.
- Added helpers to render markdown into mailto-safe plain text that preserves headings, lists, tables, code blocks, and citations without raw markdown markers.
- Added subject extraction for explicit `Subject:` and heading-based titles, plus GPT-generated fallback subjects through the same shared model initialization path used by conversation summary generation.
- Updated the frontend email action to request the backend draft while continuing to launch the user's mail client with a `mailto:` URL.
- Removed the leading export metadata wrapper so email drafts start directly with the formatted message body.
- Bumped the application version to `0.240.079`.

### Testing Approach

- Extended `functional_tests/test_per_message_export.py`.
- Added regression checks for the backend email draft route, frontend `mailto:` usage, plain-text formatting output, explicit subject extraction, and GPT-backed subject generation.

## Validation

### Before

- Email drafts could include raw markdown markers in the message body.
- Subjects defaulted to a generic sender label even when the message already contained a subject or title.
- There was no path to generate a better subject from the message content.

### After

- Email drafts keep using `mailto:` but receive a backend-generated subject and document-style plain-text body.
- Explicit subjects and top-level headings are reused when present.
- When no subject is present, the backend can generate one with the same GPT initialization path used for conversation summary generation.

### User Experience Improvement

Users can hand off a chat response into email with a cleaner, document-style body and a subject line that is usually ready to send without manual cleanup.