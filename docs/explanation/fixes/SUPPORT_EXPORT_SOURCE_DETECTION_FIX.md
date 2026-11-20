# Support Log Export Source Detection Fix

**Version:** 0.261.473

## Issue

Support Log Export asked admins to choose the Azure cloud and paste the
Application Insights and App Service resource IDs before telemetry or console logs
could be collected. The application already knows all three: `AZURE_ENVIRONMENT`
names the cloud, App Service publishes the site's identity in platform environment
variables, and `APPLICATIONINSIGHTS_CONNECTION_STRING` names the component the app
sends telemetry to.

## Root Cause

The export configuration was only ever read from the admin-saved document in Cosmos.
Blank fields meant "source unavailable", and the cloud defaulted to Azure Commercial
even for US Government deployments.

## Technical Details

### Files Modified

- `application/single_app/support_export_discovery.py` (new): detection, no I/O except one Resource Graph lookup.
- `application/single_app/support_export_contracts.py`: `normalize_overrides()`, `effective_configuration()`, slot-aware App Service IDs.
- `application/single_app/support_export_service.py`: effective configuration, `setup` block in readiness, clearer messages.
- `application/single_app/functions_support_exports.py`: detection wiring and a per-process lookup cache.
- `application/single_app/templates/admin/_support_log_export.html`, `static/js/support-exports.js`: classic admin UI.
- `application/v2_ui/src/components/admin/SupportExportPanel.tsx`, `src/lib/supportExports.ts`: v2 admin UI.
- `deployers/bicep/modules/appService.bicep`, `appServiceNativePython.bicep`, `bicep/main.json`, `terraform/main.tf`, `azurecli/deploy-simplechat.ps1`: set `APPLICATIONINSIGHTS_RESOURCE_ID`.

### How each value is resolved

| Value | Source, in order |
|-------|------------------|
| Azure cloud | `AZURE_ENVIRONMENT` (`public` / `usgovernment`). A saved cloud is only used when the environment is `custom`. |
| App Service resource ID | Saved override, else `WEBSITE_OWNER_NAME` (subscription), `WEBSITE_RESOURCE_GROUP`, `WEBSITE_SITE_NAME`, `WEBSITE_SLOT_NAME`. |
| Application Insights resource ID | Saved override, else `APPLICATIONINSIGHTS_RESOURCE_ID`, else an Azure Resource Graph lookup by the connection string's instrumentation key. |

The Resource Graph lookup needs no extra role: the application identity must already
be able to read the component to query its logs, and that read access is what makes
it visible to Resource Graph. A found ID is cached for six hours per process; a miss
is retried after five minutes so a newly granted role is noticed.

### UI

"Source and storage setup" now shows each resolved value and where it came from.
Inputs moved under "Override detected values"; blank means "use the detected
value". The cloud selector only appears when `AZURE_ENVIRONMENT` cannot name the cloud.
The setup section opens on its own when Application Insights could not be found.

### Compatibility

Existing saved configurations keep working: saved resource IDs act as overrides, and
the previously defaulted `cloud: "public"` no longer overrides a US Government
environment. Readiness keeps its `configuration` field and adds `setup`.

## Validation

- `functional_tests/test_admin_support_export_source_detection.py` covers cloud,
  App Service (including slots) and Application Insights detection, the bounded
  Resource Graph query, override precedence, and the readiness `setup` origins.
- Existing `test_admin_support_export_*` tests and
  `test_v2_admin_support_export_logic.mjs` pass unchanged.

Before: three fields to fill in before telemetry export worked.
After: on App Service deployments nothing needs to be entered; telemetry needs only
a reader role on Application Insights for the app identity.
