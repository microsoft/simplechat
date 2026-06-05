# Cosmos Native Autoscale Conversion

## Implemented in Version

Implemented in version: **0.241.159**

Migration action fixed in version: **0.241.160**

Related config.py version update: `VERSION = "0.241.160"`

## Overview

SimpleChat admins can convert Cosmos DB manual throughput offers to native Cosmos autoscale from the Admin Settings Scale tab. The feature supports shared database throughput and dedicated container throughput, and it can be applied through the global container policy for current and future containers.

## Dependencies

- Azure Resource Manager access to the configured Cosmos DB account, database, and throughput settings.
- The SimpleChat Cosmos Throughput Operator role assigned to the web app identity with throughput read/write, `migrateToAutoscale/action`, and migration operation-result read permissions.
- Cosmos DB SQL database or container throughput using manual provisioned throughput.

## Technical Specifications

### Architecture

Manual-to-autoscale conversion is handled by `functions_cosmos_throughput.py`. When conversion is requested for an existing manual throughput offer, SimpleChat calls the Cosmos throughput migration action:

```text
POST {throughputSettings/default}/migrateToAutoscale
```

After an offer is already in native Cosmos autoscale mode, SimpleChat can update the autoscale max throughput with:

```json
{
    "properties": {
        "resource": {
            "autoscaleSettings": {
                "maxThroughput": 5000
            }
        }
    }
}
```

The conversion target preserves the current manual RU/s as the autoscale max throughput, rounded up to Cosmos autoscale's 1000 RU/s increment. Minimum and maximum RU guardrails still apply.

### API Endpoints

- `POST /api/admin/settings/cosmos-throughput/convert-autoscale`
  - Admin-only endpoint.
  - Optional JSON body field: `container_name`.
  - Converts the database throughput when `container_name` is omitted.
  - Converts a dedicated container throughput offer when `container_name` is supplied.

### Configuration Options

- `cosmos_throughput_convert_manual_to_autoscale_enabled`
  - Enables background conversion for manual throughput offers.
  - Applies to database throughput when the database has a scalable manual throughput offer.
  - Applies to dedicated containers when global policy enforcement is enabled.

- Container policy field: `convert_manual_to_autoscale_enabled`
  - Enables conversion for a specific dedicated-throughput container.
  - Inherited from the global setting when global policy enforcement is enabled.

### File Structure

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/route_backend_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`

## Usage Instructions

1. Open Admin Settings and select the Scale tab.
2. Enable Cosmos throughput automation.
3. Enable **Convert manual throughput to Cosmos autoscale**.
4. For container-targeted deployments, enable **Enforce global policy for all containers** to apply the conversion setting to all current and future dedicated-throughput containers.
5. Save Admin Settings.
6. Use Refresh or the background scheduler to discover current throughput state.

Admins can also use the **Convert** action for database-level manual throughput or the lightning action button in the container table or policy modal to convert a single manual dedicated-throughput container immediately.

## Testing and Validation

- Functional tests validate opt-in conversion, global policy inheritance, and ARM autoscale payload shape.
- UI tests validate that the Admin Settings Scale tab exposes the global conversion switch, container policy field, and conversion endpoint wiring.
- Validation should include `py_compile`, focused pytest, `node --check`, and CRLF-aware whitespace checks.

## Known Limitations

- Conversion is not attempted for serverless capacity, shared-throughput containers without a dedicated throughput offer, or containers whose current manual RU/s exceeds the configured maximum guardrail.
- Background automation converts one eligible throughput offer per scheduler run.
- The feature changes Cosmos native throughput mode; it is separate from SimpleChat's scale-up and scale-down threshold automation.
