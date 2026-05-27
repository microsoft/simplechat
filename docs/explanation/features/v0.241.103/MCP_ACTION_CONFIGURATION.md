# MCP Action Configuration

Implemented in version: **0.241.103**

## Overview

SimpleChat now includes first-class action configuration for Model Context Protocol (MCP) servers. The shared action modal can create MCP action manifests with the fields Semantic Kernel needs for transport, authentication, timeout, tool discovery, and tool exposure setup.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.103"`.

## Dependencies

- Semantic Kernel MCP connector support from `semantic-kernel==1.39.4`
- Shared action modal and action validation pipeline
- Existing action secret handling through `auth.key` and reusable workspace identities

## Technical Specifications

### Architecture

- Action type: `mcp`
- Backend defaults and normalization: `application/single_app/functions_mcp_operations.py`
- Plugin descriptor and factory: `application/single_app/semantic_kernel_plugins/mcp_plugin.py`, `application/single_app/semantic_kernel_plugins/mcp_plugin_factory.py`
- Discovery endpoint: `POST /api/plugins/mcp/discover`
- Manifest validation: `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`
- Shared modal UI: `application/single_app/templates/_plugin_modal.html`
- Modal controller: `application/single_app/static/js/plugin_modal_stepper.js`
- Schemas: `application/single_app/static/json/schemas/mcp.definition.json`, `application/single_app/static/json/schemas/mcp_plugin.additional_settings.schema.json`

### Manifest Shape

MCP actions use the normal action document format with MCP-specific `additionalFields`:

```json
{
  "type": "mcp",
  "endpoint": "https://example.com/mcp",
  "auth": {"type": "key", "key": "..."},
  "additionalFields": {
    "transport": "streamable_http",
    "auth_method": "bearer",
    "load_tools": true,
    "load_prompts": false,
    "request_timeout": 30,
    "connect_timeout": 10,
    "sse_read_timeout": 300,
    "allowed_tool_names": [],
    "mcp_tools": []
  }
}
```

Supported transports:

- `streamable_http`
- `sse`
- `websocket`
- `stdio`

Supported auth methods:

- `none`
- `bearer`
- `api_key`
- `basic`
- `identity`

## Usage Instructions

1. Open the workspace action modal.
2. Select the `MCP` action type.
3. Choose the transport and provide the endpoint or stdio command.
4. Choose an authentication method or reusable identity.
5. Use **Discover Tools** to fetch available MCP tools into cached metadata.
6. Configure tool loading, optional allowlisted tool names, and cached discovered tool metadata.
7. Set timeout values between 1 and 300 seconds.
8. Review the MCP summary and save the action.

## Testing and Validation

Functional coverage:

- `functional_tests/test_mcp_action_manifest_workflow.py`

UI coverage:

- `ui_tests/test_workspace_mcp_action_modal.py`

Validation focus:

- Transport and endpoint requirements
- Stdio command setup
- Auth method and credential shape
- Timeout ranges
- Tool allowlist and metadata normalization
- Dynamic tool registration and invocation dispatch
- Browser discovery flow
- Shared workspace action save payload

## Known Limitations

- Stdio MCP servers run server-side and should be limited to trusted/admin-managed actions.
- OAuth and managed-identity token acquisition for arbitrary remote MCP servers is not implemented; bearer/API key/basic auth and reusable identities are supported for the current action flow.