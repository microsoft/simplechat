# Governance Admin Rendering XSS Hardening

Fixed/Implemented in version: **0.242.022**

## Issue

The PR readiness XSS sink check flagged changed admin browser-rendering paths where governance, endpoint, agent, and plugin metadata could reach dynamic HTML sinks or interpolated `data-*` attributes.

## Root Cause

Several changed JavaScript renderers built table rows and action buttons with template strings. Even when values were escaped, the repository guardrail requires new browser-rendering code to prefer DOM node creation, `textContent`, and inert `dataset` assignments for untrusted data.

## Technical Details

Files modified:

- `application/single_app/static/js/admin/admin_agents.js`
- `application/single_app/static/js/admin/admin_governance.js`
- `application/single_app/static/js/admin/admin_model_endpoints.js`
- `application/single_app/static/js/plugin_common.js`
- `functional_tests/test_governance_enforcement_logic.py`
- `functional_tests/test_governance_route_and_wiring_coverage.py`

Code changes summary:

- Replaced dynamic admin agent, model endpoint, and plugin table row HTML with DOM nodes and `textContent`.
- Replaced icon-only `innerHTML` swaps with a Bootstrap icon helper that creates `i` elements directly.
- Kept static Bootstrap modal shells in place with narrow `xss-check: ignore` comments that document the safe boundary.
- Updated governance functional tests to align with multi-policy item access and DOM-based endpoint button wiring.

## Validation

Validation run:

- `git diff --check origin/Development`
- `python -m py_compile` for tracked `application/single_app` Python files
- `python scripts/check_swagger_routes.py <changed application Python files>`
- `python scripts/check_xss_sinks.py --base-sha origin/Development --head-sha HEAD <changed browser files>`
- `python scripts/check_broken_access_control.py --base-sha origin/Development --head-sha HEAD <changed application Python files>`
- `python -m pytest` for the changed functional test files
- `python -m pytest` for the changed UI test files

Result: static validation passed, changed functional tests passed, and changed UI tests produced one pass with environment-gated skips for authenticated Playwright scenarios.

## Impact

Admin governance and related endpoint, agent, and action management tables now follow the repository XSS-safe rendering pattern for changed surfaces while preserving the existing user workflows.