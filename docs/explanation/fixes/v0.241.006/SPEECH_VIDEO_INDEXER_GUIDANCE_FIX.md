# Speech And Video Indexer Guidance Fix

Fixed in version: **0.241.007**

## Overview

This fix aligns the admin multimedia setup experience with the way Simple Chat actually authenticates to Azure Speech Service and Azure AI Video Indexer.

The update removes stale Video Indexer API-key guidance, adds cloud-aware Video Indexer endpoint selection, and documents the additional Speech Resource ID required for managed-identity text-to-speech.

## Issue Description

Users were encountering conflicting instructions across the admin UI and documentation:

- Video Indexer walkthrough steps still implied an API-key-style setup even though the runtime uses ARM plus managed identity.
- Video Indexer guidance mixed the managed identity used by the Video Indexer resource itself with the App Service managed identity used by Simple Chat.
- The shared Speech section implied that all Speech features used the same minimal managed-identity inputs, but text-to-speech also needs the Speech Resource ID.

## Root Cause

The UI, backend, and written guidance drifted over time.

- The admin walkthrough still referenced legacy Video Indexer fields.
- The admin JavaScript only revealed the Speech configuration when audio uploads were enabled, not when speech-to-text input or text-to-speech were enabled.
- Text-to-speech still used a key-centric backend path while other Speech flows already supported managed identity.

## Technical Details

### Files Modified

- `application/single_app/config.py`
- `application/single_app/functions_authentication.py`
- `application/single_app/functions_documents.py`
- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_tts.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/templates/_video_indexer_info.html`
- `application/single_app/templates/admin_settings.html`
- `docs/admin_configuration.md`
- `docs/reference/admin_configuration.md`
- `docs/how-to/azure_speech_managed_identity_manul_setup.md`
- `docs/setup_instructions_special.md`
- `functional_tests/test_multimedia_support_reorganization.py`
- `functional_tests/test_video_indexer_dual_authentication_support.py`
- `ui_tests/test_admin_multimedia_guidance.py`

### Code Changes Summary

- Added `speech_service_resource_id` to admin settings and persistence.
- Added a shared Speech synthesis configuration helper so text-to-speech can use managed identity correctly.
- Updated the admin multimedia walkthrough to use Video Indexer cloud selection and ARM resource fields instead of a legacy API-key path.
- Updated admin JavaScript so the shared Speech section appears when any Speech feature is enabled.
- Added Video Indexer cloud selection, effective endpoint display, and clearer identity guidance in the admin UI and help modal.

### Testing Approach

- Updated source-inspection functional tests for the current multimedia UI.
- Updated the legacy Video Indexer functional test to validate the managed-identity-only flow.
- Added a Playwright admin UI regression test for the Video Indexer cloud selector and shared Speech managed-identity fields.

## Validation

### Before

- Users could still find walkthrough and documentation references to Video Indexer API keys.
- The Speech settings panel could stay hidden when only speech-to-text input or text-to-speech was enabled.
- Managed-identity text-to-speech lacked the required Speech Resource ID guidance and backend support.

### After

- The admin UI consistently points users to managed identity for Video Indexer.
- Video Indexer cloud selection and endpoint behavior are explicit.
- Shared Speech guidance now explains the extra managed-identity requirement for voice responses.
- Functional and UI regression coverage now checks the updated configuration path.