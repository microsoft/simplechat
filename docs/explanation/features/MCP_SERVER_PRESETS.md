# MCP Server Presets

Current documentation version: **0.261.029**

Remote-only preset compatibility implemented in version: **0.261.029**.

Related configuration update: `application\single_app\config.py` advances `VERSION` from `0.261.028` to `0.261.029`.

## Overview

MCP server presets are server-side JSON definitions that describe known-good defaults for Model Context Protocol actions. They let SimpleChat ship curated presets, such as Generic MCP Server and Splunk MCP Server, while allowing organizations to add their own definitions without hard-coding provider behavior in browser JavaScript.

The browser does not read preset files directly. It calls:

```text
GET /api/plugins/mcp/presets
```

The server loads, validates, transforms, and returns safe preset definitions for the shared action modal.

## File Structure

Bundled presets live in:

```text
application\single_app\mcp_presets\
    mcp_server_preset.schema.json
    implementation_schemas\
        generic.preset.schema.json
        splunk.preset.schema.json
    definitions\
        generic.json
        splunk.json
```

Optional organization preset directories can be configured with:

```text
SIMPLECHAT_MCP_PRESET_PATHS=C:\SimpleChat\mcp-presets;D:\OrgPresets
```

Use the platform path separator for multiple directories. On Windows, use `;`.

## Preset Definition Requirements

Each preset file must:

1. Be a `.json` file.
2. Use a file name that matches the preset `id`, such as `contoso.json` for `"id": "contoso"`.
3. Validate against `application\single_app\mcp_presets\mcp_server_preset.schema.json`.
4. Avoid secrets, tokens, passwords, tenant-specific credentials, customer data, or production endpoint values.

Preset IDs must match:

```text
^[a-z0-9][a-z0-9_-]{0,63}$
```

## Example Preset

```json
{
    "id": "contoso",
    "version": "1.0.0",
    "displayName": "Contoso MCP Server",
    "description": "Contoso-specific MCP compatibility defaults.",
    "provider": "Contoso",
    "enabled": true,
    "sortOrder": 15,
    "defaults": {
        "transport": "sse",
        "auth_method": "api_key",
        "api_key_header_name": "X-Contoso-Key",
        "load_tools": true,
        "load_prompts": false,
        "request_timeout": 45,
        "connect_timeout": 15,
        "sse_read_timeout": 120,
        "retry_count": 1,
        "retry_backoff_seconds": 2,
        "validate_tool_arguments": false,
        "tool_result_policy": "truncate",
        "allowed_tool_names": []
    },
    "ui": {
        "helpText": "Use this preset for Contoso MCP endpoints.",
        "endpointPlaceholder": "https://mcp.contoso.example/mcp",
        "websocketEndpointPlaceholder": "wss://mcp.contoso.example/mcp"
    },
    "constraints": {
        "allowedTransports": ["sse"],
        "allowedAuthMethods": ["api_key"],
        "customHeadersAllowed": true
    },
    "implementation": {
        "id": "contoso",
        "schemaVersion": "1.0.0"
    },
    "additionalSettings": {
        "compatibilityProfile": "contoso_mcp"
    },
    "suggestedHeaders": [],
    "warnings": []
}
```

## Security Rules

- Do not include bearer tokens, API keys, passwords, client secrets, or connection strings.
- Do not include production tenant/customer endpoint URLs as defaults. Use placeholders.
- Presets may define header names and descriptions through `suggestedHeaders`, but should not define secret header values.
- Presets with `additionalSettings` must include an `implementation` block and a matching `implementation_schemas\{id}.preset.schema.json` file.
- Runtime credentials must still be entered through the SimpleChat action modal or reusable workspace identities.
- Presets cannot authorize a destination or restore stdio support. All roles and scopes use remote streamable HTTP, SSE, or WebSocket; local command, argument, and environment configuration is unsupported.
- Invalid preset definitions are skipped and logged through the application logging pipeline.

## Runtime Behavior

1. The modal calls `/api/plugins/mcp/presets`.
2. The server returns enabled, validated remote-only presets.
3. The modal populates the Server Preset dropdown from the API response.
4. Selecting a preset applies non-secret defaults such as transport, auth method, timeouts, retries, argument-validation preference, result policy, and help text.
5. Existing saved actions keep their values when opened for editing; preset defaults are not reapplied unless the user changes the preset.

### Compatibility With Older Custom Presets

An otherwise valid remote custom preset can retain legacy `stdioAllowed` or process-only fields in its source file. The loader normalizes a copy, removes those inert fields and stdio entries from `allowedTransports`, and validates the remote-only result. A valid remote default, authentication, headers, timeouts, and other remote compatibility settings are preserved. This cleanup is limited to retired MCP fields, not similarly named provider settings or tool arguments.

A preset whose default is stdio, or whose only allowed transport is stdio, becomes unavailable with a diagnostic. It is not converted to HTTP, and its failure does not prevent valid presets from loading. Authors should explicitly revise that preset for a supported remote server or remove it from their catalog.

Retired saved actions are not migrated by preset loading. They remain unsupported until the owner explicitly selects a remote transport and supplies a valid endpoint, or explicitly deletes them. See [MCP stdio removal and migration](../fixes/MCP_STDIO_REMOVAL_AND_AUTHORIZATION_FIX.md).

## Bundled Presets

### Generic MCP Server

The generic preset keeps broad MCP defaults:

- Streamable HTTP by default.
- No authentication by default.
- Tools enabled.
- Prompts disabled.
- Custom headers allowed.
- Reusable identity auth is allowed for preconfigurations that require workspace identity.
- Supported transports are streamable HTTP, SSE, and WebSocket in every scope.

### Splunk MCP Server

The Splunk preset is a compatibility preset, not a separate MCP implementation:

- Streamable HTTP.
- Token-based authorization defaults.
- Tools enabled.
- Prompts disabled.
- Custom headers allowed.
- No local process transport.

The MCP runtime remains generic. The preset only configures known-good defaults and UI guidance.

## Validation

Related validation:

- `functional_tests\test_mcp_server_presets.py`
- `ui_tests\test_workspace_mcp_action_modal.py`
- Route policy tests under `functional_tests\route_tests\`

Coverage includes implementation-specific preset schemas, secret-like field rejection in `additionalSettings`, reusable identity defaults, opt-in MCP argument validation defaults, and large-result policy behavior. The 0.261.029 regressions also cover legacy remote preset normalization, unavailable stdio-default/stdio-only presets, failure isolation, and the absence of stdio/process controls in the modal. These descriptions do not assert test execution results.
