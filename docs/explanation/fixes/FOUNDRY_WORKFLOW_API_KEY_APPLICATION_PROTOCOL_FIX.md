# Foundry Workflow API-Key Application Protocol Fix

Fixed in version: **0.241.193**

Superseded in version: **0.241.196**

> Current behavior: Foundry Workflow agents no longer route API-key configurations through the application protocol. Workflow invocation now uses Microsoft Entra ID/RBAC only, while API keys remain limited to model endpoint inference. See `FOUNDRY_AGENT_WORKFLOW_ENTRA_AUTH_BOUNDARY_FIX.md`.

## Issue Description

Foundry Workflow agents configured with an API key could still fail during streaming with a downstream `403` from Foundry:

```text
Identity(object id: ) does not have permissions for Microsoft.MachineLearningServices/workspaces/agents/action actions.
```

This happened for discovered Foundry project agents that were saved as workflow-capable entries.

## Root Cause Analysis

SimpleChat normalized discovered project agents into `foundry_workflow` records and invoked them through the generic project Responses endpoint with an `agent_reference`. That path creates a Foundry conversation item and can require Azure RBAC for `Microsoft.MachineLearningServices/workspaces/agents/action`.

For API-key backed discovered agents, the key is valid for the OpenAI-compatible application protocol endpoint, but it does not provide an Entra object id for the identity-gated `agent_reference` conversation item creation path.

## Technical Details

Files modified:

- `application/single_app/foundry_agent_runtime.py`
- `functional_tests/test_foundry_workflow_agent_payload.py`
- `functional_tests/test_foundry_delegated_user_auth.py`
- `ui_tests/test_agent_modal_foundry_workflow.py`
- `application/single_app/config.py`
- `docs/explanation/features/v0.241.127/FOUNDRY_WORKFLOW_AGENTS.md`

Code changes summary:

- API-key authenticated Foundry Workflow agents with a discovered `application_name` or `application_id` now route through the application Responses protocol endpoint.
- Delegated-user workflow calls continue using the generic workflow `agent_reference` conversation path.
- Workflow metadata still reports `runtime_type: foundry_workflow` and records that the application protocol was used.
- Existing workflow reference persistence is unchanged for delegated calls.

## Validation

Regression coverage added to `functional_tests/test_foundry_workflow_agent_payload.py` verifies that API-key discovered workflow agents call the New Foundry application streaming path and do not create Foundry conversations.

Expected user impact:

- API-key-backed discovered Foundry agents selected in Workflow mode should no longer fail with the empty identity object id `agents/action` authorization error.
- Users still need a valid Foundry project API key for the selected project/application.
