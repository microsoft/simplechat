# CSRF State-Changing Route Guard Fix

Fixed in version: **0.242.053**

## Issue Description

SimpleChat had many state-changing Flask routes using browser session cookies, including admin, workflow, document, collaboration, external public document, and Microsoft 365 pending-action endpoints. These routes did not have an explicit CSRF token, same-origin request validation, or configured session cookie SameSite boundary in the Flask request lifecycle.

## Root Cause Analysis

The application relied on authenticated Flask/Easy Auth sessions and route-level authorization, but ambient browser cookies can be attached automatically to cross-site POST, PUT, PATCH, and DELETE requests. The app also did not define session cookie SameSite defaults in `config.py` or `app.py`.

## Technical Details

Files modified:

- `application/single_app/app.py`
- `application/single_app/config.py`
- `functional_tests/test_csrf_state_changing_route_guard.py`

Code changes summary:

- Added explicit session cookie defaults for `SESSION_COOKIE_SAMESITE`, `SESSION_COOKIE_HTTPONLY`, and `SESSION_COOKIE_SECURE`.
- Added `CSRF_ENFORCE_ORIGIN_FOR_UNSAFE_METHODS` and `CSRF_TRUSTED_ORIGINS` configuration knobs.
- Added a global before-request guard that checks authenticated POST, PUT, PATCH, and DELETE requests for same-origin browser metadata using `Sec-Fetch-Site`, `Origin`, and `Referer`.
- Fixed the same-origin browser fetch path so normal in-app `fetch()` calls are allowed even when Azure proxy metadata makes Flask see a different scheme or host than the public browser origin.
- Covered the GET stream reattach endpoint because it mutates in-memory stream consumer state while keeping the existing fetch-based streaming contract.
- Included forwarded host/proto, Front Door URL, login/home redirect URLs, and configured trusted origins when resolving allowed origins.
- Kept non-browser clients without browser origin headers compatible while rejecting browser requests that clearly originate cross-site.

## Validation

Testing approach:

- Added a functional regression test to verify the guard structure, origin-header checks, trusted-origin handling, and explicit session-cookie settings.
- Ran Python compilation and the focused functional test.

Before/after comparison:

- Before: authenticated unsafe-method routes had no explicit same-origin or CSRF-related boundary in Flask.
- After: cross-site browser mutations with authenticated sessions are rejected before route handlers run.

Related config.py version update:

- Updated `VERSION` to **0.242.053**.