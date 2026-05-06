# Profile And Admin Review Tabs

Documentation Version: 0.241.119
Version Implemented: 0.241.115
Related Config Update: `application/single_app/config.py` -> `VERSION = "0.241.119"`

## Overview
This feature consolidates user feedback and safety history into the profile experience while upgrading the admin review pages to a control-center-style layout with tabs, summary stats, filtered data tables, and CSV export actions.

## Purpose
The goal is to reduce page fragmentation for end users and give admins a denser, easier-to-scan moderation surface. Users now stay inside the profile page for stats, settings, feedback, and violations. Admins keep dedicated feedback and safety pages, but those pages now lead with summary metrics and a separate all-data view.

## Dependencies
- Frontend: Bootstrap 5 tabs, existing profile hero layout, dedicated page scripts
- Backend: Flask route modules for profile, feedback, and safety flows
- Data Sources: feedback Cosmos container and safety Cosmos container
- Export Format: CSV download responses from feedback and safety backend routes

## Technical Specifications

### Architecture Overview
The implementation follows the existing page-shell pattern used by other management screens:
1. The profile page keeps its hero section and introduces four tabs: Stats, Settings, Feedback, and Violations.
2. Legacy user routes for My Feedback and My Safety Violations now redirect into the profile page with `tab=` deep links.
3. Profile feedback and profile violations use dedicated JavaScript to lazy-load stats, tables, modals, pagination, and export actions.
4. Admin feedback and admin safety pages use separate dedicated scripts and a two-tab shell: Stats and All Data.
5. Backend feedback and safety routes expose matching stats and export endpoints so both user and admin pages share the same server-side aggregation logic.

### API Endpoints
- `GET /feedback/my/stats`
- `GET /feedback/my/export`
- `GET /feedback/review/stats`
- `GET /feedback/review/export`
- `GET /api/safety/logs/my/stats`
- `GET /api/safety/logs/my/export`
- `GET /api/safety/logs/stats`
- `GET /api/safety/logs/export`

### File Structure
Modified frontend and route files:
- `application/single_app/route_frontend_profile.py`
- `application/single_app/route_frontend_feedback.py`
- `application/single_app/route_frontend_safety.py`
- `application/single_app/templates/profile.html`
- `application/single_app/templates/_top_nav.html`
- `application/single_app/templates/_sidebar_nav.html`
- `application/single_app/templates/_sidebar_short_nav.html`
- `application/single_app/static/js/profile/profile-tabs.js`
- `application/single_app/templates/admin_feedback_review.html`
- `application/single_app/templates/admin_safety_violations.html`
- `application/single_app/static/js/admin/admin-feedback-review.js`
- `application/single_app/static/js/admin/admin-safety-violations.js`
- `application/single_app/route_backend_feedback.py`
- `application/single_app/route_backend_safety.py`

## Usage Instructions

### User Workflow
1. Open `/profile` to land on the Stats tab by default.
2. Switch to Settings for existing profile preferences and profile-specific controls.
3. Switch to Feedback to review your submitted feedback, filter the table, inspect details, and export matching rows.
4. Switch to Violations to review your content safety history, inspect moderation details, and export matching rows.
5. Existing navigation items for My Feedback and My Safety Violations continue to work through redirects and deep links.

### Admin Workflow
1. Open the admin feedback review page to see aggregate stats first.
2. Use the All Data tab for filters, editing, retesting, pagination, and export.
3. Open the admin safety review page to see moderation status and action distributions.
4. Use the All Data tab to filter, edit notes and actions, and export the current result set.

## Testing and Validation
- Added functional regression coverage in `functional_tests/test_profile_and_admin_review_tabs.py`.
- Verified the new JavaScript files with `node --check`.
- Checked touched routes, templates, and scripts with workspace diagnostics.
- Confirmed admin save flows use inline modal status text instead of browser `alert()` fallbacks.
- Fixed the profile tab loader race in 0.241.118 by initializing `window.profilePageConfig` before `profile-tabs.js` loads.
- Fixed feedback type normalization in 0.241.119 so lowercase stored `positive` and `negative` values count, filter, and render consistently in profile and admin feedback views.

## Known Notes
- The user profile keeps the existing hero section at the top to match the requested layout.
- The admin pages intentionally do not reuse the profile hero and instead align more closely with the control center style.
