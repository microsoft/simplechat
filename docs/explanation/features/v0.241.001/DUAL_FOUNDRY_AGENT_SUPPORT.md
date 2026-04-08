# Dual Foundry Agent Support

Version implemented: 0.239.154
Dependencies: Azure AI Foundry project endpoints, agent modal stepper, scoped agent CRUD routes, Semantic Kernel loader, Foundry runtime helpers

Fixed/Implemented in version: **0.239.154**

## Overview

SimpleChat now supports both Foundry experiences at the same time instead of forcing a migration path.

- `aifoundry` remains the persisted classic Foundry agent type and is displayed in the UI as `Foundry (classic)`.
- `new_foundry` is a new persisted agent type for the application-based Foundry experience.
- The agent modal, schema validation, backend payload sanitizer, loader, and chat runtime now recognize both modes side by side.

This change is intentionally additive. Existing classic Foundry agents continue to work without migration.

## Technical Specifications

### Architecture overview

The implementation separates the two Foundry paths instead of trying to coerce them into one shared runtime contract.

- Classic Foundry continues to use the existing SDK-backed agent invocation flow.
- New Foundry uses a separate runtime path that calls the application Responses endpoint directly.
- The loader instantiates different agent wrappers based on `agent_type`.
- The modal stepper renders separate configuration fields for classic and new Foundry while preserving the local agent flow.

### Backend and runtime changes

Files modified:
- `application/single_app/functions_agent_payload.py`
- `application/single_app/static/json/schemas/agent.schema.json`
- `application/single_app/foundry_agent_runtime.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_backend_models.py`
- `application/single_app/route_backend_agents.py`
- `application/single_app/functions_settings.py`
- `application/single_app/functions_global_agents.py`

Key behaviors:
- `sanitize_agent_payload()` now accepts `local`, `aifoundry`, and `new_foundry`.
- Classic Foundry still uses `other_settings.azure_ai_foundry`.
- New Foundry uses `other_settings.new_foundry` with application-centric fields such as `application_id`, `application_name`, `application_version`, and `responses_api_version`.
- `route_backend_chats.py` dispatches both Foundry types through Foundry-style invocation instead of falling back to local handling.
- `foundry_agent_runtime.py` adds a dedicated new Foundry runtime that calls `/applications/{application}/protocols/openai/responses`.

### Frontend changes

Files modified:
- `application/single_app/templates/_agent_modal.html`
- `application/single_app/templates/_multiendpoint_modal.html`
- `application/single_app/static/js/agent_modal_stepper.js`
- `application/single_app/static/js/agents_common.js`
- `application/single_app/static/js/admin/admin_model_endpoints.js`
- `application/single_app/static/js/workspace/workspace_model_endpoints.js`
- `application/single_app/static/js/workspace/view-utils.js`

Key behaviors:
- The agent modal now exposes `Local`, `Foundry (classic)`, and `New Foundry`.
- Classic Foundry keeps the endpoint fetch-and-select flow for existing Foundry agents.
- New Foundry exposes application reference fields and Responses API version fields.
- New Foundry now supports fetching project agents/applications to populate the application identifier fields.
- Endpoint management now includes a `new_foundry` provider option.

## Usage Instructions

### How to configure classic Foundry

1. Open the agent modal.
2. Select `Foundry (classic)`.
3. Choose a configured Foundry endpoint.
4. Fetch and select a classic Foundry agent.
5. Save the agent.

### How to configure new Foundry

1. Open the agent modal.
2. Select `New Foundry`.
3. Choose or enter the Foundry project endpoint and project name.
4. Enter the application identifier from the new Foundry portal.
5. Enter the Responses API version.
6. Save the agent.

### Scope support

Both classic and new Foundry agent types are supported in all three scopes:
- Personal agents
- Group agents
- Global agents

## Testing and Validation

Functional coverage:
- `functional_tests/test_dual_foundry_agent_support.py`

UI coverage:
- `ui_tests/test_agent_modal_dual_foundry_modes.py`

Validation focus:
- Classic Foundry payloads remain valid.
- New Foundry payloads validate through the schema and sanitizer.
- Runtime and loader files contain explicit support for `new_foundry`.
- The modal exposes both Foundry modes and type-specific fields.

## Known Limitations

- Phase 1 does not add activity protocol polling yet.
- Phase 1 expects existing new Foundry portal applications to already exist.
- The dedicated web search Foundry configuration remains on the classic Foundry path.

## Related Config Version Update

The application version in `application/single_app/config.py` was incremented to `0.239.154` as part of this feature.
