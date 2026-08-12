# Admin Tabular Run Controls UI Coverage Fix (0.250.170)

Fixed in version: **0.250.170**

Related version update: `application/single_app/config.py` reports `0.250.170`.

Related issue: [#1201](https://github.com/microsoft/simplechat/issues/1201)

## Issue Description

The Admin Settings regression for large tabular run controls only scanned
`admin_settings.html` for expected text and element IDs. It did not render the
Jinja output, interact with the controls, submit the form, or prove that saved
values survived a reload.

## Root Cause

The original test treated template source as the UI contract. A malformed
render, broken label or selector, incorrect form field name, failed POST
binding, or missing save/reload persistence could therefore pass unnoticed.

## Technical Details

### Files Modified

- `ui_tests/test_admin_tabular_run_controls.py`
- `application/single_app/config.py`
- `docs/explanation/fixes/ADMIN_TABULAR_RUN_CONTROLS_UI_COVERAGE_FIX.md`

### Code Changes

- Replaced the template text scan with an authenticated Playwright test of the
  rendered `/admin/settings` page.
- Added assertions for the visible heading, labels, numeric bounds, model-mode
  options, deployment limit, and current control values.
- Changed every tabular run setting to a valid alternate value and submitted
  the production Admin Settings form. The alternate chunk deployment is
  selected from the environment's active legacy direct or APIM GPT
  configuration rather than using a placeholder that could break concurrent
  tabular work.
- Verified the alternate values after the POST redirect and an explicit page
  reload.
- Captured the original Enhanced Citations and tabular settings before the
  test. Enhanced Citations may be toggled temporarily to reveal the controls,
  but its original value is restored before each form submission.
- Restored all original tabular values through the same form in `finally` and
  reloaded to verify cleanup.
- Kept the test opt-in through `SIMPLECHAT_UI_BASE_URL` and authenticated
  Playwright storage-state environment variables.
- Added the explicit `SIMPLECHAT_UI_ALLOW_ADMIN_SETTINGS_MUTATION=true` safety
  gate so the shared settings mutation runs only in an isolated test
  environment.
- Skipped multi-endpoint environments because the configured tabular chunk
  setting stores only a deployment name and cannot safely preserve the
  endpoint context required by those models.

### Testing Approach

The exact Playwright test was exercised against a temporary local rendered
form and persistence endpoint. The browser changed, submitted, reloaded, and
restored all settings successfully. The persisted state was checked after the
test to confirm it matched the original values. The harness also provided a
distinct active GPT deployment so the configured-mode path used a valid model.

### Impact Analysis

This change affects regression coverage only. It does not change Admin
Settings runtime behavior, control defaults, route authorization, local
browser assets, or tabular execution behavior.

## Validation

- Controlled rendered Playwright execution: **1 passed**.
- Post-test persistence check: **all original values restored**.
- Save-navigation contract check: **POST-to-GET redirect accepted and direct
  POST 200 rejected**.
- Legacy model-source checks: **direct and APIM deployment discovery passed**.
- UI test collection: **1 test collected**.
- Version helper regressions: **3 passed**.
- Unconfigured repository-environment execution: **1 skipped as designed**
  because no authenticated UI base URL or storage state was present.

## Before and After

Before this fix, the test could pass without loading a browser or submitting
the settings form. After this fix, coverage follows the admin-visible workflow
through render, interaction, save, redirect, reload, and verified cleanup.

## User Experience Improvement

Administrators now have regression protection against controls that appear in
template source but fail to render, submit, or retain their saved values in
the actual Admin Settings experience.
