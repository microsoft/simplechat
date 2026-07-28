# GPT 5.6+ Multi-Modal Vision Selector Fix (v0.250.066)

Fixed in version: **0.250.066**

Related issue: [#1086](https://github.com/microsoft/simplechat/issues/1086)

## Issue

Enabled GPT 5.6 deployments appeared in the Global Endpoints table but were
missing from the Multi-Modal Vision Analysis model selector. The selector could
therefore leave admins on GPT 5.4 even when Luna, Sol, Terra, or later GPT
deployments were configured.

## Root Cause

The browser-side vision filter inspected only `modelName` or `displayName` and
required narrow punctuation patterns. Endpoint records that exposed the model
family through `deploymentName`, used a provider prefix, or formatted a display
name as `GPT 5.6` did not match.

## Technical Details

### Files Modified

- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/functions_model_capabilities.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/config.py`
- `ui_tests/test_admin_multimodal_vision_model_options.py`
- `docs/explanation/features/v0.229.088/MULTIMODAL_VISION_ANALYSIS.md`

### Code Changes

- Normalized spaces, periods, and underscores before capability matching.
- Recognized GPT major version 5 and later, including provider-prefixed names.
- Evaluated model, display, deployment, and fallback name fields.
- Applied the same capability contract during initial server rendering and
  client-side endpoint updates.
- Allowed templates loaded ahead of a restarted application worker to fall
  back to client-side option population instead of returning a Jinja error.
- Preserved filtering for disabled endpoints, disabled models, and unsupported
  model families.
- Incremented `config.py` from `0.250.065` to `0.250.066`.

## Impact

Azure OpenAI, New Foundry, and classic Foundry endpoints can expose supported
GPT 5.6 and later deployments in the same Vision Model selector without
requiring one exact metadata field or separator format.

## Validation

The focused Playwright regression test executes the production matcher, actual
Jinja selector, and dropdown population functions with GPT 5.6 Luna, Sol,
Terra, GPT 5.7, GPT-4o, disabled model, disabled endpoint, and non-GPT cases.
It also renders the selector without the route helper to verify that a stale
worker cannot return an `UndefinedError`.

Before the fix, only the placeholder and GPT-4o option were rendered. After the
fix, all enabled supported options render while excluded models remain absent.