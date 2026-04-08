# Agent Default Model Migration & Fallback Fix

Fixed/Implemented in version: **0.240.071**

## Issue Description

After multi-endpoint model management was enabled, legacy agents that still relied on inherited global routing could miss `model_endpoint_id` and `model_id`, or retain stale bindings. Chat already had a default-model fallback for some agent requests, but the shared Semantic Kernel loader and admin tooling did not provide a complete compatibility and cleanup path.

## Root Cause Analysis

- The shared loader only resolved multi-endpoint agent models when the agent document already stored a valid endpoint/model binding.
- There was no admin workflow to review all global, group, and personal agents that still depended on inherited legacy routing.
- Admins could select a default fallback model, but they could not bulk-bind legacy agents to that saved default.

## Technical Details

### Files Modified

- `application/single_app/functions_agent_payload.py`
- `application/single_app/functions_personal_agents.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_backend_agents.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/static/js/admin/admin_model_endpoints.js`
- `application/single_app/config.py`
- `functional_tests/test_default_model_selection_fallback.py`
- `functional_tests/test_admin_agent_default_model_migration.py`
- `ui_tests/test_admin_agent_default_model_migration_panel.py`

### Code Changes Summary

- Added shared helpers to distinguish inherited/default-routing agents from agents with explicit legacy custom connections.
- Updated the shared Semantic Kernel loader to fall back to the saved admin default model for eligible local agents when their binding is missing, incomplete, or stale.
- Added admin preview and bulk migration APIs that scan global, group, and personal agents and classify each record as ready, already migrated, manual review, or blocked by a missing default model.
- Added an AI Models admin workflow to review migration candidates, block migration when the default model is not saved, and bulk-bind eligible agents to the saved default.
- Automatically clears the admin migration notice once inherited-routing agents no longer require action.

## Validation

- Legacy local agents now have a shared runtime fallback path through the saved admin default model, so users do not need to manually edit working inherited agents.
- Admins can preview and bulk-migrate eligible agents across global, group, and personal scopes from the AI Models page.
- Agents with explicit custom connections or Foundry-managed routing are excluded from bulk overwrite and surfaced for manual review instead.

## Config Version Reference

`config.py` updated to `VERSION = "0.240.071"`.