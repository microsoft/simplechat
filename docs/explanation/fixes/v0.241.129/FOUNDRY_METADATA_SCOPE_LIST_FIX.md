# Foundry Metadata Scope List Fix

Fixed in version: **0.241.129**

## Issue Description

Foundry workflow and new-Foundry Responses calls could fail with HTTP 400 when SimpleChat passed internal scope arrays such as `active_group_ids` into the outbound Foundry `metadata` object. Foundry metadata values must stay under 512 characters, while a user with many active groups can exceed that limit when the list is stringified.

## Root Cause Analysis

SimpleChat needs `active_group_ids`, `active_public_workspace_ids`, and `selected_document_ids` internally to resolve authorized selected files and workspace context. The payload builders were also stringifying those internal lists into the Foundry request metadata, where they were not required and could exceed Foundry's metadata limits.

## Technical Details

- Files modified: `application/single_app/foundry_agent_runtime.py`, `functional_tests/test_foundry_workflow_agent_payload.py`, `application/single_app/config.py`
- Added Foundry response metadata sanitization that omits internal scope lists before sending requests to Foundry.
- Preserved internal metadata for SimpleChat file resolution before outbound payload construction.
- Added scalar metadata truncation to 512 characters to stay within Foundry request constraints.

## Validation

- Added a regression test that builds workflow and new-Foundry payloads with large `active_group_ids`, `active_public_workspace_ids`, and `selected_document_ids` lists.
- Confirmed the internal lists are not present in outbound Foundry metadata and long scalar metadata is capped at 512 characters.
- Related config.py version update: `VERSION = "0.241.129"`.