# Cosmos Native Autoscale Migration Action Fix

## Issue Description

Fixed in version: **0.241.160**

The Admin Settings Scale tab could enable manual-to-Cosmos-autoscale conversion, but the background scheduler and immediate conversion action attempted to update `autoscaleSettings.maxThroughput` directly on an existing manual throughput offer.

Cosmos DB rejected that request with:

```text
Existing offer needs to be autoscale to be able to update autoscale settings
```

## Root Cause Analysis

Cosmos DB exposes manual-to-autoscale conversion as a dedicated Azure Resource Manager action:

- `Microsoft.DocumentDB/databaseAccounts/sqlDatabases/throughputSettings/migrateToAutoscale/action`
- `Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/throughputSettings/migrateToAutoscale/action`

A direct `PUT` to `autoscaleSettings.maxThroughput` is valid only after the offer is already in native Cosmos autoscale mode.

## Version Implemented

Fixed in version: **0.241.160**

Related config.py version update: `VERSION = "0.241.160"`

Related deployer version update: `deployers/version.txt` set to `1.0.13`

## Technical Details

### Files Modified

- `application/single_app/functions_cosmos_throughput.py`
- `deployers/bicep/modules/setPermissions.bicep`
- `deployers/version.txt`
- `functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `application/single_app/config.py`
- `docs/explanation/features/COSMOS_NATIVE_AUTOSCALE_CONVERSION.md`

### Code Changes Summary

- Manual throughput conversion now calls `POST {throughputSettings/default}/migrateToAutoscale`.
- Existing autoscale offers still use `PUT autoscaleSettings.maxThroughput` for normal RU max updates.
- The custom SimpleChat Cosmos Throughput Operator role now includes the database and container `migrateToAutoscale/action` permissions plus operation-result read permissions.
- Regression coverage verifies that manual offers use the migration action and do not send a direct autoscaleSettings `PUT`.

### Impact Analysis

The change preserves the least-privilege model: the app identity can migrate and adjust throughput settings, but it still receives no Cosmos DB data-plane permissions from this custom role.

## Validation

The fix should be validated with:

- Python compilation for changed backend and test files.
- Focused Cosmos throughput tests.
- Azure provider operation verification for the custom role actions.
- Live App Insights traces confirming that the background scheduler no longer records the manual-offer autoscaleSettings `BadRequest`.
