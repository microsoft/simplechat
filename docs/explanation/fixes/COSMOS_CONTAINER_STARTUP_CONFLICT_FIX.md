# Cosmos Container Startup Conflict Fix

Fixed in version: **0.250.058**

## Issue Description

Local Docker startup could fail when gunicorn booted multiple workers and more than one worker imported `config.py` while Cosmos containers were still being initialized. The observed failure was a Cosmos `NotFound` during `create_container_if_not_exists`, followed by a `Conflict` because another worker created the same container first.

## Root Cause

`config.py` called the Azure Cosmos SDK `create_container_if_not_exists` helper directly for each application container at import time. The SDK helper performs a read-then-create flow, so concurrent workers can race when a container is missing: one worker creates the container after another worker has already observed `NotFound`, causing the second worker's create operation to receive `CosmosResourceExistsError` and crash during app import.

## Technical Details

Files modified:

- `application/single_app/config.py`
- `functional_tests/test_cosmos_container_conflict_recovery.py`

Code changes:

- Added a local wrapper around `cosmos_database.create_container_if_not_exists`.
- Preserved the normal SDK helper behavior for successful reads and creates.
- On `CosmosResourceExistsError`, re-read the container by id and return the now-existing container.
- Left conflicts without a resolvable container id unchanged so unexpected errors are not hidden.
- Updated `VERSION` in `config.py` from `0.250.057` to `0.250.058`.

## Validation

Test results:

- `python -m py_compile application/single_app/config.py` passed.
- `python functional_tests/test_cosmos_container_conflict_recovery.py` passed with 2/2 tests.

User impact:

- Local Docker gunicorn workers can now tolerate concurrent first-run Cosmos container creation instead of failing the whole app startup.
- Existing single-worker and already-provisioned Cosmos startup behavior remains unchanged.
