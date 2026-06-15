# Deployer Capacity Defaults

Version implemented: **0.241.085**
Implemented in version: **0.241.085**
Updated in version: **0.241.206**

## Overview

SimpleChat deployers now default to production-leaning capacity for core retrieval and data services:

- Azure AI Search: Standard S1 (`standard`) with standard Semantic Ranker.
- Azure Cosmos DB: provisioned throughput using dedicated autoscale throughput on each SimpleChat container.

These defaults reduce first-deployment surprises where workspace search, semantic retrieval, or document ingestion can fail because a free quota or serverless capacity mode is too constrained for realistic testing.

## Dependencies

- `deployers/bicep/modules/search.bicep`
- `deployers/bicep/modules/cosmosDb.bicep`
- `deployers/azurecli/deploy-simplechat.ps1`
- `deployers/terraform/main.tf`
- `deployers/version.txt`
- `application/single_app/config.py` version update to `0.241.085`

## Technical Specifications

The Bicep and one-click ARM templates expose these parameters:

- `searchSkuName`, default `standard`
- `searchSemanticSearchSku`, default `standard`
- `cosmosCapacityMode`, default `provisioned`
- `cosmosDatabaseAutoscaleMaxThroughput`, default `1000`; the parameter name is retained for deployment compatibility, but it now controls per-container autoscale max RU/s.

The Azure CLI deployer uses matching PowerShell variables, and the Terraform deployer uses matching input variables. Provisioned Cosmos deployments create the `SimpleChat` SQL database without a shared database throughput offer, then create the application containers with dedicated autoscale throughput so deployments are not capped by the 25-container shared-throughput database limit.

## Usage Instructions

Use the repository defaults for normal development, demos with document upload, user testing, and production-aligned environments.

For short-lived MVP or evaluation phases, Free Azure AI Search/Semantic Ranker or Cosmos DB serverless can still be selected by explicitly changing the deployer parameters or script variables. These settings should not be treated as the default path because they can hit semantic query, indexing, or request-unit limits.

## Testing and Validation

Functional coverage is provided by `functional_tests/test_deployer_capacity_defaults.py`, which validates the Bicep, generated ARM template, Azure CLI, and Terraform deployer defaults stay aligned with S1 Search and provisioned Cosmos DB.

Known limitation: this change affects new deployments and parameter-driven redeployments. Existing Azure resources may require an intentional migration plan if they were originally created as serverless Cosmos DB, shared-throughput Cosmos databases, or lower-tier Search services.
