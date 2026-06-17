# Route Authentication Audit Findings Fix

Fixed in version: **0.242.050**

## Issue Description

The route authentication audit found several route-contract gaps where Swagger metadata, runtime role decorators, external API token checks, or object-level active-scope authorization patterns were incomplete or inconsistent.

## Root Cause Analysis

Several older route modules had grown independently and still relied on `@login_required` alone for user-facing API routes. Some public workspace and collaboration handlers also read stored active-scope settings directly instead of using the shared authorization helpers. The agent-template routes had valid runtime role protection, but their Swagger metadata decorator was below runtime decorators, which violates the repository route contract.

## Version Implemented

0.242.050

## Technical Details

### Files Modified

- `application/single_app/route_backend_agents.py`
- `application/single_app/route_backend_agent_templates.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/route_backend_speech.py`
- `application/single_app/route_migration.py`
- `application/single_app/route_plugin_logging.py`
- `application/single_app/route_external_public_documents.py`
- `application/single_app/route_external_health.py`
- `application/single_app/route_backend_public_documents.py`
- `application/single_app/route_backend_collaboration.py`
- `application/single_app/config.py`
- `functional_tests/test_route_authentication_audit_findings_fix.py`

### Code Changes Summary

- Added `@user_required` after `@login_required` on audited non-admin application API routes.
- Added `@accesstoken_required` to the external public document delete route.
- Reordered agent-template Swagger decorators to immediately follow the Flask route decorator.
- Added Swagger auth metadata to the no-auth health probe while preserving its public runtime behavior.
- Replaced raw `activePublicWorkspaceOid` reads in public document routes with `require_active_public_workspace(...)`.
- Replaced the collaboration group fallback `activeGroupOid` read with `require_active_group(...)`.
- Updated `config.py` from `0.242.049` to `0.242.050`.

### Testing Approach

The regression test statically parses the route modules and verifies the decorator order, runtime role decorator coverage, external token guard, active-scope helper usage, and version bump.

## Validation

### Test Results

- `functional_tests/test_route_authentication_audit_findings_fix.py`
- `scripts/check_swagger_routes.py`
- `scripts/check_broken_access_control.py --full-file`

### Before and After Comparison

Before the fix, the audit scripts reported misplaced or missing Swagger metadata, direct active-scope reads, and route stacks with only `@login_required`. After the fix, the affected routes use the expected runtime decorators and shared object-level authorization helpers.

### User Experience Improvements

Users with authenticated sessions but without the `User` or `Admin` role are blocked consistently from user-facing API routes. Public workspace and collaboration operations now revalidate active scope before sensitive reads or mutations, reducing stale-scope and cross-scope authorization risk.