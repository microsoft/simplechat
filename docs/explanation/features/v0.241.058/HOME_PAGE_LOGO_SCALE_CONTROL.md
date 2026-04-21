# Home Page Logo Scale Control

## Overview

- Version implemented: 0.241.058
- Dependencies: Admin Settings branding form, landing page template, admin settings JavaScript
- Purpose: Let admins control the home page logo size independently from the top and sidebar navigation logos.

## Technical Specifications

### Architecture Overview

The feature adds a persisted numeric setting, `landing_page_logo_scale_percent`, to the application settings document. The admin settings page exposes the value through a bounded range slider, and the landing page uses the saved value when rendering the logo on `index.html`.

### Configuration

- Setting name: `landing_page_logo_scale_percent`
- Default value: `100`
- Allowed range: `50` to `500`
- Scope: Home page only

### File Structure

- `application/single_app/functions_settings.py`: default setting value
- `application/single_app/route_frontend_admin_settings.py`: input parsing and persistence
- `application/single_app/templates/admin_settings.html`: branding slider control
- `application/single_app/static/js/admin/admin_settings.js`: live slider value display
- `application/single_app/templates/index.html`: home page logo render sizing
- `ui_tests/test_admin_home_page_logo_scale_slider.py`: UI regression coverage

## Usage Instructions

1. Open Admin Settings.
2. Go to the General tab and find the Branding card.
3. Move the Main Page Logo Size slider between `50%` and `500%`.
4. Save the settings.
5. Open the home page to verify the updated logo size.

The slider only affects the large logo rendered on the home page. It does not resize the logo in `_top_nav.html`, `_sidebar_nav.html`, or `_sidebar_short_nav.html`.

## Testing And Validation

- UI regression coverage: `ui_tests/test_admin_home_page_logo_scale_slider.py`
- Input validation: admin settings parsing clamps out-of-range or invalid values back into the supported `50` to `500` range.
- Rendering validation: the landing page reads the saved percentage and applies it only to the home page logo height.

## Limitations

- The UI regression test verifies the slider behavior without saving shared admin settings in a live environment.
- Navigation logos intentionally keep their existing fixed sizes.