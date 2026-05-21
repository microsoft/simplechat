# Deep Research Admin Policy Editor - v0.241.055

Fixed/Implemented in version: **0.241.055**

Superseded in version: **0.241.066** for user policy management. Deep Research now uses allowed users only; blocked-user lists are no longer exposed or enforced. See `docs/explanation/features/v0.241.066/DEEP_RESEARCH_ALLOWED_USERS_MODAL.md`.

Related version update: `application/single_app/config.py` was incremented to `0.241.055` for this enhancement.

## Overview

The Deep Research admin policy controls now use structured editors instead of raw list textareas. Administrators can add, edit, and delete allowed or blocked domains directly, and can manage allowed or blocked users with Microsoft Graph user search plus bulk entry support.

## Dependencies

- Deep Research settings in `application/single_app/functions_settings.py`
- Admin settings form handling in `application/single_app/route_frontend_admin_settings.py`
- User search endpoint `GET /api/userSearch`
- Browser behavior in `application/single_app/static/js/admin/admin_settings.js`

## Technical Specifications

- Hidden form fields preserve the existing setting names:
  - `source_review_allowed_domains`
  - `source_review_blocked_domains`
  - `source_review_allowed_users`
  - `source_review_blocked_users`
- Client-side editors serialize policy values as newline-delimited text, keeping compatibility with `parse_source_review_list()`.
- Domain values are normalized client-side by trimming whitespace, lowercasing, and removing `http://` or `https://` prefixes when admins paste full URLs.
- User values are added from Graph search results by email when available, falling back to the user ID.
- Untrusted values are rendered with DOM node creation and `textContent`/form input values instead of dynamic HTML interpolation.

## Usage Instructions

1. Open Admin Settings and navigate to Search & Extract.
2. Enable Deep Research if needed.
3. Add allowed or blocked domains with the policy domain input.
4. Edit existing domain entries inline or remove them with the delete button.
5. Search for individual users by name or email for allowed/blocked user policies.
6. Paste multiple emails or user IDs into Bulk Add to add several user policy entries at once.

## Testing and Validation

- Updated `ui_tests/test_admin_source_review_settings.py` to validate the new domain add/edit/delete flow and user bulk controls.
- Validated that the admin UI continues to submit the same backend field names, so existing settings persistence remains unchanged.
- Client rendering follows the repository XSS-safe DOM creation pattern for policy values and Graph user search results.

## Known Limitations

- User search depends on the existing Microsoft Graph-backed `/api/userSearch` endpoint and requires the same permissions/configuration as group member search.
- Bulk user entry accepts explicit emails or user IDs; it does not resolve display names from pasted text.