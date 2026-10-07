# Terms of Use

## Overview

Implemented in version: **0.250.055**
Current documentation version: **0.250.057**

Terms of Use lets administrators require users to accept configurable terms, rules of behavior, or an entry notice before using SimpleChat. It is separate from the existing upload-focused User Agreement.

## Technical Specifications

* **Admin settings**: General tab settings control enablement, title, message, recurrence, cancel redirect, and button labels.
* **Recurrence options**:
  * Every session: stored in the Flask session.
  * Once per day: stored in user settings with the accepted UTC date.
  * Just once: stored in user settings for the current terms version.
* **Terms versioning**: A hash of the title, message, and frequency invalidates older acceptances when admins change the Terms of Use.
* **Authentication integration**:
  * Standard Microsoft sign-in users see the Terms of Use before being sent to Entra ID.
  * SSO/passive sign-in users are gated immediately after the SimpleChat session is created.
* **Redirect safety**: User-controlled return paths are local-only and stored server-side in the session. The decline destination is admin-configured and may be local or an HTTPS URL.
* **Server-side enforcement**: Authenticated browser requests are redirected to the Terms of Use page until accepted. Authenticated API requests receive a `403` response with `terms_of_use_required`.
* **Audit logging**: Accepted and declined events are written to activity logs when a user identity is known.
* **V2 interface** (from **0.261.287**): A request under `/v2` is gated to `/v2/terms-of-use` instead of the classic page, so V2 users stay in the V2 experience. The V2 page reads and answers the terms through `GET /api/v2/terms-of-use`, `POST /api/v2/terms-of-use/accept` and `POST /api/v2/terms-of-use/decline`, which share the classic acceptance, versioning, redirect-safety and audit logic. See [V2 Terms of Use and Approval Requests](V2_TERMS_AND_APPROVALS.md).

## Usage Instructions

1. Open **Admin Settings**.
2. Select the **General** tab.
3. Enable **Require terms of use**.
4. Enter the Terms of Use title and message.
5. Choose the recurrence:
   * **At the start of every session**
   * **Once per day**
   * **Just once per terms version**
6. Configure the cancel redirect URL. Use a local path such as `/` or an admin-approved HTTP(S) URL.
7. Save settings.

Users who decline are logged out locally and redirected to the configured cancel destination.

## Testing and Validation

* Functional coverage: `functional_tests/test_terms_of_use.py`
* Route policy coverage: `functional_tests/route_tests/`
* UI template coverage: `ui_tests/test_terms_of_use_ui.py`
* V2 coverage: `functional_tests/test_v2_terms_and_approvals.py`, `ui_tests/test_v2_approvals_and_terms_pages.py`

## Known Limitations

Before standard authentication, SimpleChat cannot know which user is signing in. Daily and once-per-version persistence is therefore applied after authentication, while the pre-auth prompt is tracked in the anonymous Flask session.
