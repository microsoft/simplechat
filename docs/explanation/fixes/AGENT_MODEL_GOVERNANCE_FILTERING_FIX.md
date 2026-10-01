# Agent Model Governance Filtering Fix

Fixed/Implemented in version: **0.261.048**

## Issue Description

The chat window model selector respected endpoint governance policies, but the persona workspace agent setup modal could show globally configured models that the signed-in user was not allowed to use. A user could therefore see a restricted model, such as a GPT 5.1 deployment intended only for another user, while creating or editing a personal agent.

## Root Cause Analysis

The chat bootstrap path filtered model endpoints through the governance helper before serializing dropdown options. The agent settings endpoint built its own combined endpoint list and appended global endpoints directly, so item-level global endpoint governance was skipped for user-facing agent modal payloads.

## Technical Details

Files modified:

- `application/single_app/route_backend_agents.py`
- `application/single_app/static/js/agents_common.js`
- `application/single_app/config.py`
- `functional_tests/test_agent_model_governance_filtering.py`

The agent settings endpoint now uses the shared model endpoint governance filter when building user-facing global, personal, and group endpoint lists. Admin/internal calls without a user context still receive the full endpoint catalog needed for management and migration workflows.

The shared agent modal loader also treats multi-endpoint mode as authoritative. If governance filters every endpoint out of the user-facing response, the dropdown shows no available models instead of falling back to the legacy global `gpt_model.selected` list.

## Validation

Added `functional_tests/test_agent_model_governance_filtering.py` to verify that governed agent settings payloads exclude denied global, personal, and group endpoints while preserving the unfiltered admin/internal endpoint list.

Reference version update: `application/single_app/config.py` now reports **0.261.048**.