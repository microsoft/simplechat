# V2 XSS Sink Check Fix

**Fixed in version: 0.261.281**

## Issue and root cause

The `xss-sink-check` job failed on the V2 settings redesign PR. Several newly added UI links passed values from API state directly to URL sinks, including the Latest Features route, workspace navigation, Foundry sign-in, and Microsoft 365 authorization. The guided tour also interpolated a tour target into a DOM selector. Separately, the checker treated a `javascript:` example in a Python comment as executable content.

## Technical details

`Latest Features` links now use the fixed same-origin route. Workspace destinations are normalized against the current origin and reject unsupported paths, path traversal, and embedded separators before reaching React Router. Foundry URLs are normalized against the authenticated API origin; Microsoft 365 authorization continues to require HTTPS and now uses a normalization-named helper at each navigation sink. The tour locates `data-tour` elements by comparing their dataset values rather than interpolating a selector. The Python comment now describes a script-scheme URL without using the checker token.

The regression tests cover workspace URL rejection, the URL helper call sites, and the guided-tour target lookup. No checker rule was disabled or suppressed.

## Validation

- `python scripts\check_xss_sinks.py --base-sha b0896b4c52cd120621a9a5a5f67360963127ce10 --head-sha HEAD <changed application files>` — passed for 37 files.
- `python -m pytest -q functional_tests\test_v2_user_settings_tutorials_latest_features.py functional_tests\test_v2_user_settings_memory_m365.py` — 15 passed.
- `node functional_tests\test_v2_group_workspace_context_logic.mjs` — 27 checks passed.
- `npm run typecheck` in `application\v2_ui` — passed.
- `npm run build` in `application\v2_ui` — passed; Vite reported the existing large-chunk advisory.
- `git diff --check` — passed.
