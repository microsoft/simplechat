# Font Size and 200 Percent Zoom Fix

Fixed in version: **0.250.073**

## Issue Description

Users who enlarged SimpleChat to 200 percent browser zoom on a typical laptop
could lose most of the visible chat history because navigation, headers, tools,
and the composer consumed or clipped the reduced effective viewport. Users also
lacked an account-level text-size preference.

## Root Cause Analysis

- Chat height calculations repeated fixed 66px and 106px offsets instead of
  sharing the active navigation and classification-banner offsets.
- Fixed-height panes and hidden overflow could clip the composer when the
  effective viewport height became small.
- Desktop chat tools occupied significant vertical space until the existing
  mobile breakpoint activated.
- SimpleChat did not persist a validated global font-size preference.

## Technical Details

### Files Modified

- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_users.py`
- `application/single_app/templates/base.html`
- `application/single_app/templates/profile.html`
- `application/single_app/templates/chats.html`
- `application/single_app/static/css/styles.css`
- `application/single_app/static/css/navigation.css`
- `application/single_app/static/css/sidebar.css`
- `application/single_app/static/css/chats.css`
- `functional_tests/test_font_size_preference.py`
- `functional_tests/test_user_settings_allowlist_keys.py`
- `functional_tests/test_user_settings_cache_optimization.py`
- `ui_tests/test_profile_font_size_and_chat_zoom.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added a validated `fontSizePreference` setting with `xs`, `s`, `m`, `l`, and
  `xl` values. Missing or unsupported stored values render as medium.
- Mapped the choices to 75, 87.5, 100, 150, and 200 percent root font sizes.
- Added an accessible Appearance Preferences radio group with immediate preview,
  explicit Save persistence, live status updates, and rollback after save errors.
- Applied the saved preference as a controlled HTML data attribute before CSS
  renders, preventing a default-size flash and arbitrary style injection.
- Replaced duplicated chat viewport offsets with shared navigation-aware values
  and dynamic viewport units.
- Preserved a minimum-size flex message region, reduced nonessential spacing in
  short viewports, and reused the mobile tools drawer at the 200 percent
  zoom-equivalent breakpoint.
- Preserved Development's whole-sidebar scroll-boundary behavior while updating
  the sidebar shell to use dynamic viewport sizing.

## Testing Approach

- Added a functional contract test for enum normalization, API validation,
  pre-paint rendering, profile controls, and CSS percentage mappings.
- Updated existing settings allowlist and lightweight UI cache tests.
- Added an authenticated Playwright test for live preview, Save-only
  persistence, XL rendering, top navigation, sidebar navigation, page overflow,
  and chat/composer visibility at a 720x450 CSS viewport.

## Validation

### Test Results

- Font-size functional contract tests pass.
- User-settings allowlist and cache regression tests pass.
- Updated Jinja templates parse successfully.
- Python syntax validation passes for the new UI test.
- The authenticated UI regression test requires `SIMPLECHAT_UI_BASE_URL` and a
  valid Playwright storage-state file in the target environment.

### Before and After

- **Before:** At 200 percent zoom, fixed offsets and clipped panes could leave
  only a line or two of chat visible and make lower controls unreachable.
- **After:** Chat uses the reduced viewport as a flex layout with independently
  scrolling content, compact tools, and a reachable composer.
- **Before:** Users relied entirely on browser zoom for larger text.
- **After:** Users can save a global XS through XL preference, including a
  200 percent text option, while browser zoom remains independently supported.

### User Experience Improvements

- Text size follows the signed-in user across SimpleChat pages.
- Profile selections preview immediately without silently saving.
- Navigation, messages, tools, and the composer remain reachable in compact
  laptop and zoomed layouts.
