# Microsoft Graph Pending Actions Container Import Fix

Fixed/Implemented in version: **0.241.177**

## Issue Description

Starting the Flask app could fail while importing `functions_msgraph_pending_actions.py` because the module imported `cosmos_msgraph_pending_actions_container`, but `config.py` did not define that Cosmos container export.

## Root Cause Analysis

The Microsoft Graph pending-action helper expected a dedicated `msgraph_pending_actions` Cosmos container for user-owned mail and calendar actions. The container name and object were missing from the centralized Cosmos initialization block in `config.py`.

## Technical Details

- Files modified: `application/single_app/config.py`
- Added `cosmos_msgraph_pending_actions_container_name = "msgraph_pending_actions"`.
- Added `cosmos_msgraph_pending_actions_container` using `PartitionKey(path="/user_id")` so pending actions remain user-scoped.
- Updated `VERSION` in `config.py` to `0.241.177`.

## Validation

- Added `functional_tests/test_msgraph_pending_actions_config_container.py` to verify the container name, exported container symbol, and `/user_id` partition key without requiring a live Cosmos connection.
- Ran Python syntax checks for `config.py`, `functions_msgraph_pending_actions.py`, and the new functional test.