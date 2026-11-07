# Orchestration Unseeded Agent Availability and Catalog Ranking Fix

**Version: 0.261.378**

Fixed in version: **0.261.378**, recorded in `application/single_app/config.py`.

## Issue

In V2 chat with **Orchestrate** enabled, asking a natural-language request that named a
configured agent alongside an action and attached documents (without pinning a single
agent in **Manual controls**) produced a plan that omitted **Ask an agent**
(`agent_invoke`) and disclosed that the requested agent could not be invoked because
agent invocation was unavailable for the request.

In deployments where a user had more than 25 accessible agents or File Sync sources,
newly created agents or sources named in the prompt could also be omitted from
`workflow_planning` catalogs (`workflow_propose` and `workflow_handoff`) because only
existing workflows were ranked by whether the request named them before applying the
25-entry catalog cap.

Additionally, when a chat file upload targeted a group workspace, background ingestion
completion (`sync_chat_upload_workspace_attachment_status`) overwrote the message's
`workspace_attachment.scope` to `'personal'` and its `workspace_url` to `/workspace`.

## Root Cause Analysis

1. **Classic `/chats` `enable_agents` toolbar toggle state blocked unseeded V2 orchestration agent steps**:
   - `update_user_settings()` in `application/single_app/functions_settings.py`
     initialized missing `doc['settings']['enable_agents']` to `False` whenever any user
     setting was saved (such as Terms of Use acceptance, V2 sidebar rail collapse, or
     orchestration approval mode), even though `get_user_settings()` readers in
     `semantic_kernel_loader.py` and `route_backend_chats.py` default `enable_agents` to
     `True`.
   - `enable_agents` in `user_settings` is the UI toggle state of the `#enable-agents-btn`
     button on the classic `/chats` toolbar, which switches the classic composer between
     the Model dropdown and the Agent dropdown. The V2 interface (`/v2`) has no control
     for `enable_agents`.
   - Version `0.261.289` (`ORCHESTRATION_SELECTED_AGENT_DISABLED_PREFERENCE_FIX.md`)
     bypassed `enable_agents: False` only when an agent was manually pinned in
     `seeds['agent']`. However, in normal V2 Orchestrate usage—and whenever a plan combines
     `agent_invoke` with `action_invoke` (since setting `seeds['agent']` suppresses
     `action_catalog` in `resolve_action_catalog`)—no agent is pinned in `seeds['agent']`.
   - When `user_settings.settings.enable_agents` was `False` and `seeds['agent']` was
     `None`, `route_backend_orchestration.py` (`_request_identity`) set
     `user_enable_agents = False`, skipped `resolve_agent_catalog()`, and caused
     `resolve_available_capabilities()` to withhold `agent_invoke` with
     `unavailable['agent_invoke'] = 'agents_disabled_for_user'`. Execution preparation
     (`current_execution_identity` in `functions_orchestration_bootstrap.py`) and
     external-source preflight/admission/read (`OrchestrationExternalSourceProvider._capability`
     in `functions_orchestration_external_sources.py`) had the same restriction.

2. **Workflow planning agent and source catalogs truncated alphabetically at 25 entries**:
   - In `application/single_app/functions_orchestration_workflow_context.py`,
     `_workflow_entries()` ranked workflows named in `request_text` first via
     `_named_by(request_text)` before slicing to `CATALOG_MAX_WORKFLOWS`, whereas
     `_agent_entries()`, `_handoff_agent_entries()`, and `_source_entries()` sorted
     alphabetically or in reader order and truncated at `CATALOG_MAX_AGENTS = 25` and
     `CATALOG_MAX_SOURCES = 25` without prioritizing entries named in `request_text`.

3. **Group chat upload status sync hardcoded personal scope**:
   - In `application/single_app/functions_documents.py`,
     `sync_chat_upload_workspace_attachment_status()` hardcoded `'scope': 'personal'` and
     `'workspace_url': f"/workspace?document_id={document_id}"` even when `group_id` was
     present on `document_metadata` or the existing `workspace_attachment`.

## Technical Details

### Files Modified

| File | Summary of Changes |
| --- | --- |
| `application/single_app/functions_settings.py` | Default missing/unset `enable_agents` in `update_user_settings()` to `True` rather than `False`. |
| `application/single_app/route_backend_orchestration.py` | Return `user_enable_agents: True` from `_request_identity()` so V2 orchestration planning, revision, retry, and execution admission offer accessible agents regardless of the classic `/chats` button state. |
| `application/single_app/functions_orchestration_bootstrap.py` | Return `user_enable_agents: True` from `current_execution_identity()` (headless plan replay still overrides `identity_context={'user_enable_agents': False}`). |
| `application/single_app/functions_orchestration_external_sources.py` | Treat `source_type == "agent"` in `OrchestrationExternalSourceProvider._capability()` as an explicit V2 orchestration agent invocation while preserving `seeded_agent` catalog narrowing, scope, membership, governance, and enabled-state checks. |
| `application/single_app/functions_orchestration_workflow_context.py` | Rank agents and File Sync sources named in `request_text` first in `_agent_entries()`, `_handoff_agent_entries()`, and `_source_entries()` before applying the 25-entry catalog cap. |
| `application/single_app/functions_documents.py` | Preserve `'group'` scope, `group_id`, `group_name`, and `/group_workspaces` URL in `sync_chat_upload_workspace_attachment_status()` when `group_id` is present. |
| `application/single_app/config.py` | Increment `VERSION` to `0.261.378`. |
| `docs/admin/orchestration.md` | Document that V2 orchestration offers and runs accessible agents regardless of the classic `/chats` button state. |
| `functional_tests/test_orchestration_unseeded_agent_availability_fix.py` | New regression test suite covering unseeded `agent_invoke` planning and execution with `enable_agents: False`, workflow planning agent/source ranking past 25 entries, and group chat upload attachment status sync. |

## Validation

- Ran `pytest functional_tests/test_orchestration_unseeded_agent_availability_fix.py`
- Ran `pytest functional_tests/test_orchestration_seeded_agent_preference_fix.py functional_tests/test_orchestration_external_sources.py functional_tests/test_orchestration_agent_document_type_fix.py functional_tests/test_orchestration_workflow_planning_context.py`
- Verified `scripts/check_cosmos_response_boundaries.py` contract checks.
