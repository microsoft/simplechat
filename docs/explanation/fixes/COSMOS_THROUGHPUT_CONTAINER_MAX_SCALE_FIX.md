# Cosmos Throughput Container Max Scale Fix

Fixed/Implemented in version: **0.241.194**

## Issue Description

Dedicated Cosmos DB containers could remain at 9,000 RU/s even after crossing the configured scale-up threshold when the configured maximum was 10,000 RU/s and database-level throughput also existed in the account.

## Root Cause Analysis

The autoscale decision path evaluated database throughput first whenever a scalable database throughput target was present. In mixed database and dedicated-container throughput configurations, this could mask a hotter dedicated container candidate. A container at 9,000 RU/s with a 10,000 RU/s maximum could therefore be skipped or the database target could be selected instead of the container target.

## Technical Details

### Files Modified

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/config.py`
- `functional_tests/test_cosmos_throughput_autoscale_logic.py`

### Code Changes Summary

- Evaluated dedicated container autoscale decisions before applying database-level scale actions when both throughput scopes are present.
- Preserved the existing fallback to container-only scaling when database throughput is not scalable.
- Added regression coverage for 9,000 RU/s scaling up to the configured 10,000 RU/s maximum.
- Bumped `config.py` version to `0.241.194`.

### Testing Approach

- Extended Cosmos throughput functional tests to cover database one-step-to-max scale-up.
- Added mixed database/container throughput coverage to ensure the hot dedicated container is selected and scaled from 9,000 RU/s to 10,000 RU/s.

## Impact Analysis

Mixed Cosmos throughput deployments now scale the specific dedicated container under pressure instead of letting a database throughput target mask the container action. Existing database-level scaling behavior remains unchanged when no dedicated container needs scaling.

## Validation

- `python functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `python -m py_compile application/single_app/functions_cosmos_throughput.py functional_tests/test_cosmos_throughput_autoscale_logic.py application/single_app/config.py`