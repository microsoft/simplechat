# CosmosClient Import Binding CodeQL Fix

Fixed/Implemented in version: **0.250.047**

## Issue Description

CodeQL reported that direct imports of `CosmosClient` would not observe later changes to `azure.cosmos.CosmosClient`. This can happen when tests or diagnostics patch the Azure SDK module attribute before importing app modules.

## Root Cause Analysis

Python `from azure.cosmos import CosmosClient` binds the current class object to a local module name. If a test later replaces `azure.cosmos.CosmosClient`, that local binding still points to the original class. The affected SimpleChat modules included direct `CosmosClient` imports in Cosmos initialization and plugin paths.

## Technical Details

Files modified:

* `application/single_app/config.py`
* `application/single_app/functions_data_management.py`
* `application/single_app/route_backend_plugins.py`
* `application/single_app/semantic_kernel_plugins/cosmos_query_plugin.py`
* `functional_tests/test_cosmos_query_plugin.py`

Code changes summary:

* Replaced direct `CosmosClient` imports with `import azure.cosmos as azure_cosmos`.
* Updated client creation to call `azure_cosmos.CosmosClient(...)` at runtime.
* Updated the Cosmos query plugin functional test to patch `module.azure_cosmos.CosmosClient` and to import app modules through a fake Cosmos client boundary.

## Validation

Validation performed:

* Python syntax compilation for affected app and test files.
* `functional_tests/test_cosmos_query_plugin.py`.
* Search verification that direct `from azure.cosmos import CosmosClient` imports were removed from affected app files.

Impact:

* Runtime behavior is unchanged for normal app execution.
* CodeQL can observe module-qualified SDK lookups.
* Tests that patch `azure.cosmos.CosmosClient` now affect app modules consistently.