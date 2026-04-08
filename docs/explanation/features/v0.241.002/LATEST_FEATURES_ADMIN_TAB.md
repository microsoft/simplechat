# Latest Features Release Grouping (v0.241.002)

## Overview
This update extends the existing **Latest Features** experience so admins and end users can see both the current release highlights and the immediately previous release highlights without merging them into one long list.

Version Updated: 0.241.002

## Dependencies
- `application/single_app/support_menu_config.py`
- `application/single_app/route_frontend_support.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/latest_features.html`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/_sidebar_nav.html`

## Implemented in version: **0.241.002**

## Technical Specifications

### Shared Release Metadata
- The support latest-features catalog is now grouped by release metadata instead of behaving like one flat list only.
- The current release remains the primary `Latest Features` section.
- A new `Previous Release Features` group preserves the earlier `v0.239.001` release highlights.
- Visibility still uses the same per-feature setting keys, so existing admin sharing choices continue to work.

### User-Facing Latest Features Page
- The user-facing Support > Latest Features page still renders the current release cards directly.
- Previous Release Features now appear below the current cards in a collapsed section.
- The previous-release cards reuse the same feature-card layout, guidance, and action-card treatment as the current release items.
- External guide links now use the public documentation site at `https://microsoft.github.io/simplechat/` for the previous release walkthroughs that already exist there.

### Admin General Settings
- `General > User-Facing Latest Features` is now grouped by release.
- The current release checklist stays expanded.
- The previous release checklist is collapsed by default so admins can preserve N and N-1 visibility without making the settings area too long.

### Admin Latest Features Tab
- The admin-only Latest Features tab keeps the current release cards as the primary content.
- A new collapsed `Previous Release Features` card sits after the current release items.
- Each previous-release item shows its summary, details, guidance, and whether it is currently shared with end users.
- The admin sidebar submenu now includes a direct link to the Previous Release Features card.

## Usage Instructions
- Open **Admin Settings** and select **Latest Features** to review the current release summary cards.
- Expand **Previous Release Features** when you want to revisit the immediately prior release set.
- Open **General > User-Facing Latest Features** when you want to control which current and previous release items are shared to end users.
- Open **Support > Latest Features** as an end user to verify the current release appears first and the previous release group appears below it in a collapsed section.

## Testing and Validation
- Confirm the support catalog exposes both current and previous release groups.
- Confirm the user-facing Latest Features page renders the current release directly and the previous release in a collapsed section.
- Confirm previous-release guide links open the public documentation pages when present.
- Confirm the admin General checklist groups current and previous release items separately.
- Confirm the admin Latest Features tab contains the collapsed Previous Release Features card.
- Confirm the admin sidebar submenu can jump directly to the Previous Release Features card.