# Support Menu Sidebar Visibility Fix

Fixed in version: **0.240.058**

## Issue Description

The Support menu could be enabled in Admin Settings but still fail to appear in the left sidebar for some signed-in sessions.

## Root Cause Analysis

The sidebar templates only rendered the Support menu when the session had the `User` role, which excluded Admin-only accounts. On the Admin Settings page, the template was also missing the derived `support_feedback_recipient_configured` flag, so the sidebar could hide the Support section when Send Feedback was the only enabled destination. The compact sidebar variant also had no Support section at all.

## Technical Details

Files modified:

- `application/single_app/templates/_sidebar_nav.html`
- `application/single_app/templates/_top_nav.html`
- `application/single_app/templates/_sidebar_short_nav.html`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/route_frontend_support.py`
- `application/single_app/route_backend_settings.py`
- `functional_tests/test_support_menu_user_feature.py`
- `ui_tests/test_support_menu_sidebar_visibility.py`
- `application/single_app/config.py`

Code changes summary:

- Broadened Support menu visibility and access checks to signed-in app users with either `Admin` or `User` roles.
- Added the derived `support_feedback_recipient_configured` flag to the Admin Settings template context.
- Added Support navigation to the compact sidebar used with top-nav chat layouts.
- Added functional and UI regression coverage for Support sidebar visibility.

## Validation

Test results:

- Functional support-menu coverage passes.
- Related admin latest-features coverage passes.
- Related admin send-feedback coverage passes.

Before/after comparison:

- Before: Support could be enabled but still remain hidden in left-nav layouts for Admin-only sessions.
- After: Support appears consistently in the sidebar and nav surfaces whenever it has at least one enabled destination and the signed-in account has normal app access.