# Speech Resource ID Builder Fix

Fixed in version: **0.241.008**

## Overview

This fix makes the managed-identity Speech configuration easier to complete by helping admins build the Azure Resource Manager Speech resource ID directly in the Admin Settings page.

## Issue Description

The Speech Resource ID is required for managed-identity text-to-speech, but it is not easy to locate in the Azure portal. Users had to either find the value manually in the resource properties page or use Azure CLI commands outside the app.

## Root Cause

The admin UI only exposed a single raw Speech Resource ID field. It did not provide any assistance for constructing the ARM path even though the required parts are predictable.

## Technical Details

### Files Modified

- `application/single_app/config.py`
- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/templates/admin_settings.html`
- `application/external_apps/databaseseeder/artifacts/admin_settings.json`
- `docs/how-to/azure_speech_managed_identity_manul_setup.md`
- `functional_tests/test_multimedia_support_reorganization.py`
- `ui_tests/test_admin_multimedia_guidance.py`

### Code Changes Summary

- Added optional helper fields for Speech Subscription ID, Speech Resource Group, and Speech Resource Name.
- Added client-side builder logic that assembles the Speech ARM resource ID in the format `/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<name>`.
- Added endpoint-based resource-name inference for common custom-domain Speech endpoints.
- Persisted the helper fields in admin settings and the seeded sample admin settings artifact.

## Validation

### Before

- Admins had to find or type the full Speech Resource ID manually.
- The portal location for the Resource ID was easy to miss.

### After

- Admins can provide the subscription ID, resource group, and Speech resource name and let the UI build the full Resource ID.
- The built value is still editable, so manual overrides remain possible.