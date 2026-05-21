# Deep Research Allowed Users Modal

Version implemented: **0.241.066**

Fixed/Implemented in version: **0.241.066**

## Overview

Deep Research admin access control now uses an allow-only user policy with a compact management modal. The main Search & Extract settings card keeps domain allow/block editors visible, while user management moves behind a **Manage Users** button to keep the page usable as the allowlist grows.

## Dependencies

- `application/single_app/config.py` version `0.241.066`
- Bootstrap modal components in `application/single_app/templates/admin_settings.html`
- Admin settings behavior in `application/single_app/static/js/admin/admin_settings.js`
- User search endpoint: `GET /api/userSearch?query=...`

## Technical Specifications

- Deep Research no longer exposes or enforces blocked-user policy lists.
- Legacy `source_review_blocked_users` values are ignored by the runtime access check and cleared on admin save.
- Allowed users are stored in the existing `source_review_allowed_users` setting as newline-delimited email addresses or user IDs.
- The modal supports manual adds, directory search selection, filtering current allowed users, remove actions, and CSV upload.
- CSV upload accepts `userId,displayName,email` or `email` headers and adds email addresses first, falling back to user IDs.
- New Deep Research defaults use the current hard maximum safety budgets and enable the optional research helpers behind the master feature toggle.

## Usage Instructions

1. Open **Admin Settings** > **Search & Extract**.
2. Enable **Deep Research** when needed.
3. Use **Allowed Domains** and **Blocked Domains** for domain policy.
4. Select **Manage Users** to open the allowed-user modal.
5. Add users by directory search, manual email/user ID, or CSV upload.
6. Leave the allowed-user list empty to allow all signed-in users.

## Testing and Validation

- `functional_tests/test_source_review_security.py` validates allow-only user access, ignored legacy blocked-user settings, safe max defaults, URL safety, and evidence extraction behavior.
- `functional_tests/test_deep_research_query_planning_and_ledger.py` validates Deep Research max defaults and query/ledger behavior.
- `ui_tests/test_admin_source_review_settings.py` validates the compact admin policy UI, absence of blocked-user controls, allowed-user modal behavior, and CSV upload.

## Configuration Notes

The application version was updated in `application/single_app/config.py` to `0.241.066`. Deep Research defaults were updated in `application/single_app/functions_settings.py` and mirrored in `application/single_app/functions_source_review.py`.
