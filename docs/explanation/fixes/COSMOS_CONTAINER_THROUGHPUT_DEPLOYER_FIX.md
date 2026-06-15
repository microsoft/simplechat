# Cosmos Container Throughput Deployer Fix

Fixed in version: **0.241.206**
Deployer version: **1.0.14**

## Issue Description

New `azd up` deployments could fail during Gunicorn worker startup with a Cosmos DB error similar to:

```text
Collection create forbidden as collection count in database offer has exceeded 25.
```

The application imports `config.py` during worker boot and opens or creates all SimpleChat Cosmos containers. The deployer created the `SimpleChat` database with shared autoscale throughput, and Cosmos DB limits shared-throughput databases to 25 containers. Current SimpleChat deployments require more than 25 application containers.

## Root Cause Analysis

The deployment model used a provisioned Cosmos DB account, but attached the autoscale throughput offer to the `SimpleChat` SQL database. That made the database a shared-throughput database. When app startup reached the 26th container, Cosmos rejected the create operation even though the account itself was healthy and provisioned.

## Technical Details

Files modified:

- `deployers/bicep/modules/cosmosDb.bicep`
- `deployers/bicep/main.bicep`
- `deployers/bicep/main.json`
- `deployers/azurecli/deploy-simplechat.ps1`
- `deployers/terraform/main.tf`
- `deployers/version.txt`
- `application/single_app/config.py`
- `functional_tests/test_deployer_capacity_defaults.py`
- `docs/explanation/features/v0.241.085/DEPLOYER_CAPACITY_DEFAULTS.md`

Code changes summary:

- Provisioned Cosmos deployments now create the `SimpleChat` SQL database without a shared database throughput offer.
- SimpleChat containers are pre-created with dedicated autoscale throughput in provisioned mode.
- The default autoscale max is now 1000 RU/s per container.
- The existing `cosmosDatabaseAutoscaleMaxThroughput` Bicep parameter name is retained for deployment compatibility, but it now controls per-container autoscale max RU/s.
- Serverless Cosmos deployments continue to create containers without throughput settings.

## Testing Approach

Validation is covered by `functional_tests/test_deployer_capacity_defaults.py`, which checks the Bicep, generated one-click ARM template, Azure CLI deployer, Terraform deployer, documentation, application version, and deployer version.

## Impact Analysis

New provisioned deployments avoid the shared-throughput 25-container limit and should no longer fail at startup when SimpleChat reaches containers such as `public_workspace_identities`.

Existing deployments that already have a shared-throughput `SimpleChat` database may require an intentional migration plan because removing a shared database throughput offer is not generally an in-place Bicep update. Those environments should be reviewed before rerunning infrastructure deployment.

## Validation

Before:

- `azd up` created a shared-throughput `SimpleChat` database.
- App startup attempted to create more than 25 containers under that database offer.
- Gunicorn workers failed to boot with the Cosmos container-count error.

After:

- The deployer creates the database and all expected SimpleChat containers.
- Provisioned throughput is assigned at the container level.
- The app can open existing containers during startup without hitting the shared database container limit.
