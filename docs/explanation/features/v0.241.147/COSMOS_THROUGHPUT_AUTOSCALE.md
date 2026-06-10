# Cosmos Throughput Autoscale

Overview

Implemented in version: **0.241.147**

This feature adds Cosmos DB RU monitoring and guarded throughput automation to the Admin Settings Scale tab. It helps administrators monitor Cosmos DB RU pressure and automatically adjust the shared SimpleChat database throughput, or dedicated container throughput, when utilization crosses configured thresholds.

Fixed/Implemented in version: **0.241.147**

Enhanced in version: **0.241.148** with container-targeted throughput fallback and per-container policy controls.

Enhanced in version: **0.241.161** with grouped scale-up and scale-down policy controls plus save-blocking validation for policy threshold and interval relationships.

Enhanced in version: **0.241.162** with a dedicated Validate Access action that tests the current form values before admins save or enable throughput automation.

Enhanced in version: **0.241.180** with container table filtering and sortable columns for container name, current RU/s, RU utilization, request units, and policy.

Enhanced in version: **0.241.181** with a table-local Refresh Table action for reloading container rows beside the container filter.

Enhanced in version: **0.241.183** with explicit setup guidance for the web app managed identity RBAC assignment and detailed Validate Access pass/fail diagnostics.

Enhanced in version: **0.241.184** with neutral informational status copy when the environment uses container-targeted throughput instead of database-level throughput.

Dependencies

- Admin Settings Scale tab in `application/single_app/templates/admin_settings.html`
- Admin settings JavaScript in `application/single_app/static/js/admin/admin_settings.js`
- Cosmos throughput helper in `application/single_app/functions_cosmos_throughput.py`
- Background scheduler in `application/single_app/background_tasks.py`
- Azure Monitor metrics through `azure-monitor-query`
- Azure Resource Manager access through `DefaultAzureCredential`
- Deployer app settings and RBAC in `deployers/bicep/modules/appService.bicep` and `deployers/bicep/modules/setPermissions.bicep`

Technical Specifications

Architecture overview

- The Scale tab now includes a Cosmos DB Throughput card for database identity, automation settings, live status, manual scale controls, per-container RU visibility, and a container policy modal.
- The card header includes a Setup Guide button, while operational actions such as Refresh and Validate Access are grouped separately in the card body.
- Current SimpleChat Bicep deployments use database-level autoscale throughput on the `SimpleChat` database, so the preferred path scales the database autoscale max RU/s.
- Environments without database-level throughput fall back to container-targeted management for containers with dedicated throughput.
- Container-targeted management is a normal supported capacity mode, so the Admin Settings status message is informational unless metrics or permissions fail.
- Azure Monitor metrics provide recent normalized RU utilization and per-container request-unit visibility.
- The per-container metrics table can be filtered by container name and sorted by container, current RU/s, RU utilization, request units, or policy.
- The per-container metrics table includes a Refresh Table action so admins can reload rows directly from the table controls.
- Manual Scale Up and Scale Down buttons call admin-only backend APIs.
- Automatic scaling runs in the existing background task framework every five minutes.
- A Cosmos-backed distributed lock prevents multiple app instances from scaling at the same time.

Automation behavior

- Scale up defaults to 1000 RU/s every 5 minutes when utilization reaches 90% or higher.
- Scale down defaults to 1000 RU/s every 20 minutes when utilization is 70% or lower.
- Scale up and scale down can be enabled or disabled independently.
- Scale Up At must be higher than Scale Down At when automation is enabled.
- Scale Up Interval and Scale Down Interval must be greater than or equal to the Metrics Window.
- Minimum and maximum RU/s guardrails are available.
- Admins can explicitly ignore the minimum or maximum guardrail when needed.
- Runtime state is saved back into app settings for last check, last observed utilization, last scale action, and last error.
- Validate Access runs a non-mutating setup check with the current form values and does not update the saved runtime status cache.
- Validate Access reports each setup dependency independently: resource configuration, database throughput read, scalable throughput target discovery, container discovery, and Azure Monitor metrics read access.
- Container-targeted runtime state stores last scale-up/down timestamps per container so cooldowns are enforced independently.

Container policy controls

- The Containers button opens a modal with all discovered containers.
- Each container can be enabled or disabled for automation.
- Each container has independent scale-up and scale-down thresholds, step sizes, cooldown intervals, minimum RU/s, maximum RU/s, and min/max ignore flags.
- Containers using shared database throughput are shown for visibility but cannot be scaled individually until they have dedicated throughput.

Security model

- No Cosmos DB connection string, query surface, or management client is exposed to agents or user-defined actions.
- Throughput operations are available only through admin-only Flask routes and the internal background scheduler.
- The deployer adds resource metadata app settings so the backend can target the deployed Cosmos account without user-supplied resource IDs.
- The deployer adds a custom `SimpleChat Cosmos Throughput Operator` role for the web app identity. This role allows throughput-setting reads/writes and metric reads without adding Cosmos data-plane permissions.
- Role assignments must target the Azure App Service managed identity service principal for the running SimpleChat web app. In the Azure portal this is the Object (principal) ID shown under the Web App Identity blade, and in Microsoft Entra ID it appears as the matching Enterprise Application. Do not assign throughput-management RBAC to the user-facing Microsoft Entra sign-in app registration unless that app registration is also the credential used by the running web app.
- Assign `SimpleChat Cosmos Throughput Operator` at the resource group scope containing the Cosmos account, or directly on the Cosmos account when a narrower scope is required.
- The custom role includes these management-plane actions: `Microsoft.DocumentDB/databaseAccounts/read`, `Microsoft.DocumentDB/databaseAccounts/sqlDatabases/read`, `Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/read`, database and container `throughputSettings/read`, `throughputSettings/write`, `throughputSettings/migrateToAutoscale/action`, throughput operation-result reads, and `Microsoft.Insights/metrics/read`.
- If a deployment does not have the SimpleChat custom role, create an equivalent custom Azure RBAC role with those actions and assign it to the web app managed identity. Broad built-in roles such as Contributor can satisfy the checks but are not the recommended least-privilege path.
- Managed identity deployments still retain the existing Cosmos Contributor role because other deployment/runtime flows depend on it.
- Key-auth deployments can still use the system-assigned web app identity for management-plane throughput changes.

Manual RBAC assignment example

Use these commands when the deployer did not create or assign the throughput role automatically. Replace the placeholder values with the deployed resource names.

```bash
web_app_principal_id=$(az webapp identity show --resource-group <app-resource-group> --name <web-app-name> --query principalId -o tsv)
cosmos_account_id=$(az cosmosdb show --resource-group <cosmos-resource-group> --name <cosmos-account-name> --query id -o tsv)

az role assignment create \
  --assignee-object-id "$web_app_principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role "SimpleChat Cosmos Throughput Operator" \
  --scope "$cosmos_account_id"
```

To assign at the resource group scope instead, use:

```bash
resource_group_id=$(az group show --name <cosmos-resource-group> --query id -o tsv)

az role assignment create \
  --assignee-object-id "$web_app_principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role "SimpleChat Cosmos Throughput Operator" \
  --scope "$resource_group_id"
```

After assigning the role, wait a few minutes for Azure RBAC propagation, then run **Validate Access** from Admin Settings. A failed result now identifies which dependency failed and preserves successful checks for comparison.

API endpoints

- `GET /api/admin/settings/cosmos-throughput/status`
  - Returns configured resource metadata, database throughput mode/current RU, recent metrics, and per-container metric rows.
- `POST /api/admin/settings/cosmos-throughput/validate-access`
  - Accepts the current Cosmos throughput form values and validates resource configuration, database throughput read access, scalable target discovery, container discovery, and Azure Monitor metrics without saving settings or changing RU/s.
  - Returns a `checks` array with `name`, `label`, `passed`, and `message` values so admins can see what succeeded, what failed, and the Azure error detail for failed checks.
- `POST /api/admin/settings/cosmos-throughput/scale`
  - Accepts `{ "direction": "up" }` or `{ "direction": "down" }` and applies the configured step and guardrails.
  - Accepts an optional `container_name` value for dedicated container throughput scaling.

Configuration options

- `cosmos_throughput_autoscale_enabled`
- `cosmos_throughput_auto_scale_up_enabled`
- `cosmos_throughput_auto_scale_down_enabled`
- `cosmos_throughput_subscription_id`
- `cosmos_throughput_resource_group`
- `cosmos_throughput_account_name`
- `cosmos_throughput_database_name`
- `cosmos_throughput_metrics_window_minutes`
- `cosmos_throughput_scale_up_threshold_percent`
- `cosmos_throughput_scale_down_threshold_percent`
- `cosmos_throughput_scale_up_step_ru`
- `cosmos_throughput_scale_down_step_ru`
- `cosmos_throughput_scale_up_cooldown_minutes`
- `cosmos_throughput_scale_down_cooldown_minutes`
- `cosmos_throughput_min_ru`
- `cosmos_throughput_max_ru`
- `cosmos_throughput_ignore_min_limit`
- `cosmos_throughput_ignore_max_limit`
- `cosmos_throughput_container_policies`

Usage Instructions

Admin workflow

- Open Admin Settings.
- Select the Scale tab.
- Review the Cosmos DB Throughput card.
- Save resource metadata if the deployed app settings do not auto-populate it.
- Enable Cosmos throughput automation.
- Adjust scale-up and scale-down thresholds, step sizes, cooldown intervals, and min/max guardrails.
- Keep the Metrics Window less than or equal to both scale intervals and keep Scale Up At higher than Scale Down At.
- Use Containers to configure per-container policies when the environment uses dedicated container throughput.
- Use the container table filter and sortable headers to find high-utilization or high-request-unit containers quickly.
- Use Refresh Table to reload the container rows from the same controls after changing the filter or reviewing sorted results.
- Save Admin Settings.
- Use Validate Access after changing resource identity or permissions to confirm the current form values work before enabling automation.
- When Validate Access fails, review the pass/fail list. Database throughput read failures usually point to missing `throughputSettings/read`; container discovery failures point to missing `containers/read`; metric failures point to missing `Microsoft.Insights/metrics/read`; and write or conversion failures during manual actions point to missing `throughputSettings/write` or `migrateToAutoscale/action`.
- Use Refresh to view current throughput and metrics.
- Use Scale Up or Scale Down for guarded manual changes.

Testing and Validation

Functional coverage

- `functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`

Validation performed

- `python -m py_compile application/single_app/functions_cosmos_throughput.py application/single_app/route_backend_settings.py application/single_app/route_frontend_admin_settings.py application/single_app/background_tasks.py application/single_app/functions_settings.py`
- `node --check application/single_app/static/js/admin/admin_settings.js`
- `python functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `python -m pytest functional_tests/test_cosmos_throughput_autoscale_logic.py ui_tests/test_admin_cosmos_throughput_settings_ui.py`
- Focused Playwright UI test for the new Scale-tab controls

Known limitations

- The preferred path scales the shared `SimpleChat` database throughput because that is how the current deployer provisions Cosmos DB capacity.
- Per-container scaling applies only to containers with dedicated throughput. Containers sharing database throughput remain visibility-only.
- Azure Monitor metrics can lag by a few minutes, so decisions use recent observed utilization rather than instantaneous request pressure.
- Serverless Cosmos accounts cannot be scaled by this feature.

Related config.py version update

- Application version updated to `0.241.148` in `application/single_app/config.py` for container-targeted fallback controls.
- Application version updated to `0.241.161` in `application/single_app/config.py` for grouped policy controls and save-blocking validation.
- Application version updated to `0.241.162` in `application/single_app/config.py` for the Validate Access setup test action.
- Application version updated to `0.241.180` in `application/single_app/config.py` for container table sorting and filtering.
- Application version updated to `0.241.181` in `application/single_app/config.py` for the table-local Refresh Table action.
- Application version updated to `0.241.183` in `application/single_app/config.py` for explicit Cosmos throughput access guidance and detailed Validate Access diagnostics.
- Application version updated to `0.241.184` in `application/single_app/config.py` for neutral container-targeted throughput status language.
- Deployer version updated to `1.0.12` in `deployers/version.txt` for Bicep app-setting and RBAC changes.
