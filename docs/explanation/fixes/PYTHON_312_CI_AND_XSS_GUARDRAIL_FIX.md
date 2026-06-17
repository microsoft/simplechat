# Python 3.12 CI and XSS Guardrail Fix

Fixed/Implemented in version: **0.242.066**

## Issue Description

GitHub PR checks were failing because workflow jobs used Python 3.11 while SimpleChat targets Python 3.12. The branch also had changed browser-rendering lines that triggered the XSS sink guardrail.

## Root Cause Analysis

Python 3.11 rejects f-string forms that Python 3.12 accepts, so syntax-sensitive guardrail jobs could not parse valid app code. Separately, the XSS checker flagged changed template lines that used `|safe`, dynamic `innerHTML`, or interpolated image markup instead of explicit JSON/DOM boundaries.

## Technical Details

Files modified:

* `.github/workflows/python-syntax-check.yml`
* `.github/workflows/swagger-route-check.yml`
* `.github/workflows/broken-access-control-check.yml`
* `.github/workflows/broken-access-control-full-scan.yml`
* `.github/workflows/xss-sink-check.yml`
* `.github/workflows/staging-azd-ui-tests.yml`
* `application/single_app/templates/admin_settings.html`
* `application/single_app/templates/group_workspaces.html`
* `application/single_app/templates/profile.html`
* `application/single_app/config.py`

Code changes summary:

* Updated workflow Python setup to `3.12`.
* Removed an unnecessary `|safe` filter from `tojson`-rendered Admin Settings data.
* Replaced group delete modal dynamic HTML insertion with DOM construction and `textContent`.
* Replaced profile hero `innerHTML` rendering with DOM construction and `replaceChildren()`.
* Updated `config.py` to version `0.242.066`.

## Validation

Test results:

* Python 3.12 compile validation passes for changed application Python files.
* XSS sink validation passes for the changed application browser-rendering surfaces.
* First-party JavaScript syntax validation passes for the changed template-adjacent JavaScript files.

Before/after comparison:

* Before: CI syntax and parser-based guardrail jobs failed under Python 3.11, and XSS guardrail jobs flagged changed rendering lines.
* After: CI uses the supported Python 3.12 runtime, and changed rendering code uses explicit safe JSON/DOM boundaries.

User experience improvements:

* Maintainers get PR checks aligned with the supported runtime while retaining XSS guardrail coverage for browser-rendering changes.

Reference: `config.py` version updated to `0.242.066` as part of this fix.