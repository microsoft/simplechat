# Feedback And Plugin Log Access Control Fix

Fixed/Implemented in version: **0.241.013**

## Overview

This change closes two authenticated access-control gaps in the user feedback and plugin logging surfaces.

Version implemented:
`config.py` now reports `VERSION = "0.241.013"` for this fix.

## Issue Description

### Feedback Submission Ownership Enforcement (`f038`)

- `POST /feedback/submit` accepted caller-supplied `conversationId` and `messageId` values.
- The route queried the message container by that conversation id without checking whether the authenticated user owned the target conversation.
- When the target assistant message was found, the route copied prompt and response content into a new feedback row under the attacker's user id.
- The copied content could later be read back through the user's own feedback listing.

### Plugin Log Clear Authorization (`f039`)

- `POST /api/plugins/clear-logs` was protected only by authentication.
- Any authenticated user could trigger `clear_history()` on the shared in-memory plugin invocation logger.
- That wiped the global plugin invocation history for all users instead of only the caller's data.

## Root Cause

- Route entry authentication existed, but object-level or role-based authorization at the sensitive operation boundary was missing.
- The feedback route trusted caller-controlled identifiers after login.
- The plugin log clear route relied on a comment noting admin-only intent, but did not enforce the required admin role.

## Technical Changes

### Feedback Conversation Authorization

Changes implemented:

- Added `_authorize_feedback_conversation(...)` to `application/single_app/route_backend_feedback.py`.
- The helper loads the target personal conversation and fails closed when the current user does not own it.
- `feedback_submit()` now returns `404` for missing conversations and `403` for foreign-owned conversations before any message query runs.

Security outcome:

Feedback submission is now bound to the authenticated user's own conversation scope.

### Feedback Target Message Validation

Changes implemented:

- `feedback_submit()` now requires the target assistant message to exist inside the authorized conversation.
- Missing assistant messages now return `404` instead of falling through to placeholder text and feedback persistence.
- Feedback rows are no longer written when the target conversation or assistant message is invalid.

Security outcome:

The route no longer creates cross-tenant or invalid feedback records that can later surface copied content in the caller's feedback history.

### Plugin Clear-Logs Admin Gate

Changes implemented:

- Imported `admin_required` in `application/single_app/route_plugin_logging.py`.
- Added `@admin_required` to `clear_plugin_logs()` while preserving the existing `@login_required` and Swagger decorator chain.
- The success response and App Insights logging remain unchanged for authorized administrators.

Security outcome:

Only administrators can clear the shared plugin invocation history.

## Files Modified

- `application/single_app/route_backend_feedback.py`
- `application/single_app/route_plugin_logging.py`
- `application/single_app/config.py`
- `functional_tests/test_feedback_submission_authorization.py`
- `functional_tests/test_plugin_logging_clear_logs_authorization.py`

## Validation

Testing approach:

- Added an isolated feedback authorization regression using fake Cosmos containers and a Flask test app.
- Added an isolated plugin logging authorization regression using a fake shared logger and a Flask test app.
- Recompiled the touched Python modules and new functional tests with `py_compile`.

Validation performed for this implementation:

- `python -m py_compile application/single_app/route_backend_feedback.py`
- `python -m py_compile application/single_app/route_plugin_logging.py`
- `python -m py_compile functional_tests/test_feedback_submission_authorization.py`
- `python -m py_compile functional_tests/test_plugin_logging_clear_logs_authorization.py`
- `python functional_tests/test_feedback_submission_authorization.py`
- `python functional_tests/test_plugin_logging_clear_logs_authorization.py`

## Before And After

Before:

- Authenticated users could submit feedback against a foreign conversation and persist copied prompt and response content into their own feedback history.
- Any authenticated user could clear the shared plugin invocation history.

After:

- Feedback submission now requires ownership of the target conversation and existence of the target assistant message before a feedback row is created.
- `clear-logs` now requires the `Admin` role and preserves the prior `401` contract for unauthenticated requests.

## User Experience Impact

Normal feedback submission and admin plugin log maintenance continue to work. The visible changes are the expected secure outcomes:

- Users now receive `403` or `404` responses when they try to submit feedback for a conversation or assistant message they do not legitimately own.
- Non-admin users now receive `403 Forbidden` when they attempt to clear plugin logs.