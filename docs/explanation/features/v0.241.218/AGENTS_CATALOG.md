# Agents Catalog

Implemented in version: **0.241.218**

## Overview

The Agents Catalog adds a global **Agents** page for users to browse and launch every agent they can access from one place. The catalog combines personal agents, enabled global agents, and group agents from groups where the user is a member.

UI refined through version: **0.241.231**

## Technical Specifications

- Frontend route: `route_frontend_agents.py` renders `/agents` behind login, user role, Swagger security, and the `enable_semantic_kernel` feature gate.
- Backend catalog APIs: `route_backend_agents.py` exposes `/api/agents/catalog` and `/api/agents/popular`.
- Shared catalog helper: `functions_agent_catalog.py` centralizes accessible agent serialization for both chat preload and the Agents page.
- Agent metadata: agents now support non-secret `tags` and `icon` fields in `agent.schema.json` and `functions_agent_payload.py`.
- Agent icons can be selected from the local Bootstrap Icons catalog or uploaded as a PNG/JPEG image. Uploaded images are resized client-side and saved as a small data image payload on the agent Cosmos record to avoid blob-storage reads for tiny avatar assets.
- Agent usage analytics: `functions_activity_logging.log_agent_run()` records completed agent responses as `agent_run` activity log records for popularity ranking.
- Chat rendering: selected agent icon and tags flow through selected-agent settings, chat request metadata, assistant message persistence, streaming final payloads, collaboration message serialization, and browser rendering.
- Model icons: multi-endpoint model records support optional icon metadata, normalized through `functions_settings.normalize_model_endpoints()` and rendered in the chat model selector.

## Usage Instructions

- Users open **Agents** from the left navigation under **Chat** when agents are enabled.
- The page supports search, Popular/Personal/Group/Enterprise tabs, tag filters, list view, and card view.
- Search activates a temporary **Search Results** tab and searches across all accessible agents.
- The **Popular** tab shows top-used accessible agents when usage data exists and supports **Most Popular All Time** and **Last 30 Days** ranking filters.
- Popular ranking uses agent usage counts without showing implementation-oriented run counts in the main list. Agent details show **Times Used All Time** and **Times Used Last 30 Days**.
- The **Enterprise** tab displays global agents using user-facing enterprise terminology.
- The **Personal** tab shows a **New Agent** link when user agent creation is allowed. It opens the personal workspace Agents tab and launches the existing new-agent modal.
- The **Group** tab shows a **New Agent** link when group agent creation is allowed. It opens the group workspace Group Agents tab without opening a modal.
- Agent details resolve model and action display names instead of showing raw identifiers when those names are available.
- Agent creation/edit modals support a searchable Bootstrap icon picker and an image upload mode for custom icons.
- Agent rows/cards use workspace-style hover highlighting, open details when clicked, and use a compact information icon instead of a full Details button.
- Agent details include instructions, scope, type, model, actions, tags, all-time usage count, and last-30-days usage count.
- Selecting **Chat** saves the selected agent through `/api/user/settings/selected_agent` and opens the chat page with that agent selected.

## Testing and Validation

Functional coverage:

- `functional_tests/test_agents_catalog_feature.py`
- `functional_tests/test_global_agent_chat_selection_visibility.py`
- `ui_tests/test_agents_catalog_details_modal.py`

Validation areas:

- Catalog routes and navigation are present and protected.
- Agent tags/icons are accepted by backend payload normalization and schema validation.
- Browser catalog rendering avoids dynamic HTML sinks for untrusted agent data.
- Agent icon/tag metadata is preserved through chat selection and assistant message rendering.
- Model icon metadata is normalized and exposed to the chat selector.

## Related Version Updates

- Initial feature implementation updated `application/single_app/config.py` to **0.241.218**.
- Sidebar settings fallback fix updated `application/single_app/config.py` to **0.241.219**.
- Tabbed directory UI and catalog label refinement updated `application/single_app/config.py` to **0.241.221**.
- Agent icon picker and upload support updated `application/single_app/config.py` to **0.241.222**.
- Usage count wording refinement updated `application/single_app/config.py` to **0.241.223**.
- Card click/details refinement updated `application/single_app/config.py` to **0.241.224**.
- Icon-only details control and rank alignment follow-up updated `application/single_app/config.py` to **0.241.230**.
- Popular usage-window filtering and split usage counts updated `application/single_app/config.py` to **0.241.231**.
