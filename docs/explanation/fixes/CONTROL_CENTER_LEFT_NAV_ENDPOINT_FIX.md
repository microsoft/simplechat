# Control Center Left Nav Endpoint Fix

Fixed/Implemented in version: **0.250.052**

## Issue Description

Admins could open Control Center while the left navigation Control Center section stayed hidden, even when the ControlCenterAdmin and ControlCenterDashboardReader app-role settings were disabled.

## Root Cause Analysis

The full sidebar template checked for the unqualified endpoint name `control_center`. The route is registered on the `frontend_control_center` Blueprint, so Flask exposes the endpoint as `frontend_control_center.control_center`. The mismatch prevented the page-local Control Center left-nav section from rendering.

## Technical Details

Files modified:

- `application/single_app/templates/_sidebar_nav.html`
- `application/single_app/config.py`
- `functional_tests/test_control_center_left_nav_endpoint.py`

Code changes summary:

- Updated the Control Center sidebar condition to match the blueprint-qualified endpoint.
- Preserved the existing role fallback where regular `Admin` users get Control Center navigation when ControlCenterAdmin enforcement is disabled.
- Added a regression test for the endpoint condition and version bump.

## Validation

Validation approach:

- Run `python functional_tests/test_control_center_left_nav_endpoint.py`.
- Run `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.

Before: the Control Center page could load but the left nav section was not rendered because the endpoint check did not match.

After: the sidebar condition matches `frontend_control_center.control_center`, allowing authorized admins to see the Control Center left-nav section.

Related issue: Fixes #1009

Version reference: `application/single_app/config.py` version `0.250.052`.