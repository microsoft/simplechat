# Enhanced Citations Startup Storage Degradation Fix

Issue description: Enhanced Citations storage connectivity could block application startup when the feature was enabled but the configured Azure Storage account was unreachable, inaccessible, or misconfigured.

Root cause analysis: startup created the Enhanced Citations Blob service client and immediately performed container `exists()` and `create_container()` calls for every expected source container. Those network-bound calls made optional storage availability part of the app boot path.

Fixed in version: **0.250.126**

## Technical details

Files modified:

- `application/single_app/config.py`
- `application/single_app/functions_documents.py`
- `application/single_app/route_backend_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `functional_tests/test_enhanced_citations_startup_storage_degradation.py`
- `ui_tests/test_admin_enhanced_citations_storage_status.py`

Code changes summary:

- Startup now builds the Enhanced Citations Blob service client without probing Azure Storage containers.
- Startup records a non-secret runtime status so admins can see whether Enhanced Citations storage is disabled, configured, or failed to initialize.
- Blob container creation moved to the upload path where Enhanced Citations storage is actually required.
- Admin Settings now shows the startup storage status and provides an explicit Enhanced Citations Storage connection test.
- Connection-test failures return a stable admin-safe error while logging exception type and context server-side.

Testing approach:

- Added `functional_tests/test_enhanced_citations_startup_storage_degradation.py` to verify startup initialization avoids container `exists()` and `create_container()` calls, upload-time readiness owns container creation, and admin diagnostics are exposed.
- Added `ui_tests/test_admin_enhanced_citations_storage_status.py` to verify the Admin Settings storage status alert and explicit test button wiring.

Impact analysis:

- Cosmos DB remains the hard startup dependency.
- Enhanced Citations storage outages no longer prevent app startup.
- Enhanced Citations upload and preview paths still fail if storage is unavailable, but those failures are isolated to the feature path and surfaced through admin diagnostics.

## Validation

Before: enabling Enhanced Citations could cause app boot to depend on storage account reachability because startup checked and created storage containers.

After: startup does not perform live Enhanced Citations storage container checks; admins can explicitly test storage from Admin Settings, and uploads create containers on demand when permissions allow it.
