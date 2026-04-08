# Support Latest Feature Images Fix

Fixed in version: **0.240.061**

## Issue Description

The user-facing Latest Features page displayed preview images, but users could not click those images to open a larger view the way admins can from the Admin Settings Latest Features tab. Several admin Latest Features cards were also still pointing at placeholder SVG assets even though real PNG screenshots were available. The user page also lagged behind the admin tab in screenshot coverage and did not explain where users should go next to actually try the announced features.

## Root Cause Analysis

The user template originally rendered plain image tags without any thumbnail trigger, modal markup, or JavaScript to populate a larger preview dialog. The shared support feature catalog also lagged behind the admin Latest Features tab, so some user-facing items and image assets were missing. The page content itself also focused on what changed without giving users enough guidance about why each change matters or which page they should open to use it.

## Technical Details

Files modified:

- `application/single_app/templates/latest_features.html`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/support_menu_config.py`
- `application/single_app/static/js/support/latest_features.js`
- `functional_tests/test_support_menu_user_feature.py`
- `ui_tests/test_support_latest_features_image_modal.py`
- `docs/explanation/fixes/SUPPORT_LATEST_FEATURE_IMAGES_FIX.md`
- `application/single_app/config.py`

Code changes summary:

- Added clickable thumbnail buttons around user-facing latest-feature images.
- Added a Bootstrap modal styled to match the admin latest-feature preview experience.
- Added support-page JavaScript to populate and open the modal from data attributes.
- Replaced admin placeholder SVG references with the new PNG screenshots for GPT selection, citation improvements, document versioning, and support menu imagery.
- Expanded the shared user-facing latest-features catalog so every user-facing card now carries an image when an admin-side screenshot exists.
- Added richer user-facing guidance for why each feature matters and how to try it.
- Added page-specific action links so users can jump from Latest Features into Chat, Personal Workspace, or Support destinations directly.
- Clarified tabular guidance so users know they should upload CSV/XLSX files to benefit from the newer analysis flow and can create a new revision by uploading the updated file instead of deleting the old one first.
- Added functional and UI regression coverage for the click-to-preview workflow.

## Validation

Test results:

- Functional support-menu coverage passes.
- Related admin latest-features coverage passes.
- Related admin send-feedback coverage passes.

Before/after comparison:

- Before: Users could see feature images but not open a larger preview, the admin/user latest-feature image assets were partially out of sync, and the page did not clearly tell users where to go next.
- After: Users can click feature images, open modal previews, see the missing Support-related cards, and use direct links plus clearer guidance to jump into Chat, Personal Workspace, or Support workflows.