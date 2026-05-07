# Agent Template Gallery Actions To Load XSS Fix

Fixed/Implemented in version: **0.241.020**

## Overview

This fix closes finding **f045**, a stored XSS in the agent template gallery.

Version implemented:
`config.py` now reports `VERSION = "0.241.020"` for this fix.

## Issue Description

- The gallery renderer in `application/single_app/static/js/agent_templates_gallery.js` built the `Recommended actions` line with `innerHTML` and interpolated `template.actions_to_load` directly into that sink.
- The submission path stored `actions_to_load` values without a shared normalizer, so malformed payloads could survive into storage and later reach the gallery renderer.
- The admin review UI already rendered `actions_to_load` safely with `textContent`, which made malicious entries look inert during review while still leaving the gallery path vulnerable.

## Root Cause Analysis

- The gallery mixed trusted label markup with untrusted action names inside a single `innerHTML` assignment.
- Template helper code normalized `actions_to_load` ad hoc instead of through one shared helper, so read and write paths could drift and invalid shapes were not rejected consistently.

## Technical Details

### Files Modified

- `application/single_app/static/js/agent_templates_gallery.js`
- `application/single_app/functions_agent_templates.py`
- `application/single_app/config.py`
- `functional_tests/test_agent_template_gallery_actions_to_load_xss_fix.py`
- `ui_tests/test_agent_template_gallery_actions_escaping.py`

### Code Changes Summary

- Replaced the gallery `actions_to_load` `innerHTML` sink with DOM node creation and a text node for the untrusted action names.
- Added `_normalize_actions_to_load(...)` in `functions_agent_templates.py` and reused it from `_sanitize_template(...)`, `_base_template_from_payload(...)`, and `update_agent_template(...)`.
- Write paths now reject non-list `actions_to_load` payloads and non-string entries with `ValueError`, while read sanitization still coerces stored values into a safe list of trimmed strings.
- Added a focused functional regression for the sink removal and the shared normalizer, plus a Playwright regression that renders malicious action labels through the actual gallery module.

## Validation

### Testing Approach

- Functional regression: `functional_tests/test_agent_template_gallery_actions_to_load_xss_fix.py`
- UI regression: `ui_tests/test_agent_template_gallery_actions_escaping.py`
- Targeted backend compile check: `python -m py_compile application/single_app/functions_agent_templates.py`

### Expected Results

- Malicious `actions_to_load` values render as literal text in the gallery.
- The gallery does not create attacker-controlled `img` or `svg` nodes.
- Backend template helpers reject invalid `actions_to_load` write shapes and normalize read output consistently.

## Before And After

Before:

- A stored `actions_to_load` payload could reach the gallery through `innerHTML` and execute in any viewer's browser.
- Invalid `actions_to_load` payload shapes could be coerced inconsistently by create and update code.

After:

- The gallery renders `actions_to_load` through text nodes only.
- Shared backend normalization keeps the field shape consistent across read, create, and update flows.