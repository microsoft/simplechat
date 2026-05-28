# Assigned Knowledge

Implemented in version: **0.241.068**

Updated in version: **0.241.070**

Updated in version: **0.241.071**

Updated in version: **0.241.087**

Updated in version: **0.241.117**

Updated in version: **0.241.118**

Updated in version: **0.241.119**

## Overview

Assigned Knowledge lets an agent creator bind an agent to a governed set of workspace and web knowledge. When the agent is selected in chat, document search and assigned URL review are forced on from the configured knowledge sources. Agent creators can optionally allow users to add their own workspace documents as task-specific context alongside the assigned baseline.

## Purpose

The feature gives agent owners a predictable retrieval boundary without relying on chat users to manually pick the same documents, tags, or URLs each time. Assigned URLs reuse the existing URL Access and Deep Research policy controls instead of granting broad web browsing on their own.

## Dependencies

- Agent records store configuration in `other_settings.assigned_knowledge`.
- Chat retrieval uses the existing hybrid search pipeline.
- Document access is validated against personal, group, and public workspace document stores.
- The feature uses the current application version from `application/single_app/config.py`.

## Technical Specifications

### Architecture Overview

Assigned Knowledge is stored with the agent and normalized through a shared backend helper before it is saved. During chat, the selected agent is resolved from trusted server-side agent records, then its Assigned Knowledge is applied as the agent baseline. If the agent does not allow user workspace context, browser-provided document scope, selected documents, active group IDs, public workspace IDs, and tag filters are ignored. If the creator allows user workspace context, Assigned Knowledge and user workspace context are searched separately and merged after retrieval. Assigned web sources are passed to Source Review as trusted seed URLs from the stored agent record.

Explicit documents and selected tags are additive at runtime: explicitly selected documents are included alongside documents that match the selected dynamic tag set. Tags remain dynamic criteria and are not expanded into stored document IDs.

User workspace context policy is opt-in and supports separate action permissions for Search, Analyze, and Compare. These permissions are enforced server-side for regular chat, streaming chat, and chat document-action workflows.

Assigned web source modes:

- Review URL reviews the exact assigned URL as URL Access evidence.
- Deep Research uses the assigned URL as a Source Review seed and can follow bounded child links within the existing Deep Research limits.
- Both modes still honor admin enablement, role requirements, domain allow/block lists, internal host protections, redirects, robots.txt settings, and page limits.

Scope rules for v1:

- Personal agents can use personal documents and visible public workspaces.
- Group agents can use only the active group that owns the agent.
- Global agents can use public workspaces only.

### API Endpoints

- `GET /api/agents/assigned-knowledge/catalog` returns authorized sources, documents, and tags for the agent modal.
- Existing personal, group, and global agent save endpoints validate and persist `other_settings.assigned_knowledge`.
- Existing `/api/chat` and `/api/chat/stream` requests enforce assigned knowledge at runtime when the selected agent has it enabled.

### Configuration Options

No new app-level setting is required. Each agent stores:

```json
{
  "assigned_knowledge": {
    "enabled": true,
    "scopes": {
      "personal": false,
      "group_ids": [],
      "public_workspace_ids": ["public-workspace-id"]
    },
    "document_ids": ["document-id"],
    "tags": ["Finance"],
    "web_sources": [
      {
        "url": "https://example.com/guide",
        "mode": "deep_research"
      }
    ],
    "allow_user_workspace_context": true,
    "allowed_user_workspace_actions": ["search", "analyze", "compare"]
  }
}
```

### File Structure

- `application/single_app/functions_assigned_knowledge.py` contains normalization, validation, catalog, and runtime filter helpers.
- `application/single_app/route_backend_agents.py` exposes the catalog endpoint and validates agent saves.
- `application/single_app/route_backend_chats.py` enforces runtime search filters and assigned URL source review for regular and streaming chat.
- `application/single_app/functions_source_review.py` accepts trusted assigned URL seeds while preserving URL Access and Deep Research policy checks.
- `application/single_app/functions_search.py` and `application/single_app/utils_cache.py` support list-valued public workspace filters and Assigned Knowledge's additive document/tag filter mode.
- `application/single_app/templates/_agent_modal.html` adds the Knowledge wizard step.
- `application/single_app/static/js/agent_modal_stepper.js` manages Assigned Knowledge authoring.
- `application/single_app/static/js/chat/chat-agents.js`, `chat-documents.js`, and `chat-messages.js` apply chat behavior for assigned baseline knowledge and optional user workspace context.

## Usage Instructions

1. Open the agent create or edit modal.
2. Go to the Knowledge step.
3. Enable Assigned Knowledge.
4. Use Source Workspaces to define the document pool, then optionally add Tag Limits or Specific Documents to narrow the final active set.
5. Add optional Web Sources by pasting one or more URLs and choosing Review URL or Deep Research mode.
6. Optionally enable User Workspace Context and choose whether users can Search, Analyze, and Compare with their own selected workspace documents.
7. Save the agent.
8. Select the agent in chat to force the assigned document and assigned URL context.

The Knowledge step includes an Active Documents preview that shows the final indexed documents the agent will use from the selected source workspaces. With only source workspaces selected, every document in those sources is active. Tag limits narrow the pool to documents that match the selected tag set, and specific documents are included explicitly alongside tag matches. The source workspace picker lists all public workspaces, including public workspaces hidden from the user's normal directory view, so agent creators can find them through search without changing their personal public workspace selector. Web Sources are listed separately because they are live reviewed evidence, not indexed workspace documents.

When users ask an Assigned Knowledge agent what documents, files, sources, or assigned knowledge it can access, chat injects the complete active document inventory so the answer can include the exact active document count and list rather than only the top retrieved citations. Personal agents remain personal conversations even when their Assigned Knowledge comes from public workspaces; the assigned public workspace is tracked as additional locked context so the personal agent remains selectable on later turns.

When Assigned Knowledge is enabled for the selected agent, the chat workspace picker no longer displays the assigned sources as a read-only selection. If User Workspace Context is disabled, the Workspaces button acts as an Assigned Knowledge indicator and user document selections are ignored by the backend. If User Workspace Context is enabled, the Workspaces panel remains available for task-specific user selections while Assigned Knowledge still runs as the agent baseline.

## Testing and Validation

### Test Coverage

- `functional_tests/test_assigned_knowledge_agent_policy.py` validates backend normalization, scope policy, user workspace context policy, assigned web source normalization, Source Review seed URLs, save payload canonicalization, runtime filter conversion, and additive document/tag search semantics.
- `ui_tests/test_agent_modal_assigned_knowledge_step.py` validates the modal Knowledge step, searchable transfer lists, resolved document preview, web source controls, user context controls, and settings serialization.
- `ui_tests/test_chat_assigned_knowledge_lock.py` validates chat behavior for assigned-only agents and assigned agents that allow user workspace context.

### Performance Considerations

The catalog endpoint caps returned documents and source IDs to avoid oversized modal payloads. Runtime search uses the existing hybrid search flow and cache keys now include all active public workspace IDs plus the document/tag filter mode to prevent cross-workspace or cross-mode cache reuse.

### Known Limitations

- Assigned web sources are explicit URL seeds only; site-wide or domain-wide crawling is intentionally out of scope.
- Web search remains a separate chat capability and is not automatically granted by assigned web sources.
- Group agents are intentionally limited to their owning active group.
- Global agents cannot use personal or group-scoped knowledge.
