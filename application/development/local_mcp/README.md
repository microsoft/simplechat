# SimpleChat Local MCP Server

The SimpleChat local MCP server is a development-only MCP fixture for testing outbound MCP actions without depending on Splunk or third-party MCP services.

Implemented in version: **0.250.059**

## Why this lives here

This server is stored under `application\development\local_mcp` because it is reusable development tooling. Functional tests that exercise it live under `functional_tests`.

## Install dependencies

Install the app and development requirements from the repository root:

```powershell
pip install -r application\single_app\requirements.txt -r requirements-dev.txt
```

## Run locally

From the repository root:

```powershell
python application\development\local_mcp\server.py --host 127.0.0.1 --port 8765
```

Confirm the server is healthy:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765/healthz
```

Use this MCP endpoint in SimpleChat:

```text
http://127.0.0.1:8765/mcp
```

## Configure SimpleChat to connect to the local server

Start SimpleChat separately in your normal local development terminal. Then open the SimpleChat UI and create or edit an action/plugin using the shared plugin modal.

Use these settings for the baseline Phase 1 smoke test:

| Field | Value |
| --- | --- |
| Action/plugin type | MCP |
| Name | `local_mcp_test` |
| Display name | Local MCP Test |
| Server preset | Generic |
| Transport | Streamable HTTP |
| Endpoint | `http://127.0.0.1:8765/mcp` |
| Authentication method | No Authentication |
| Custom Headers (JSON) | `{}` |
| Load tools | Enabled |
| Load prompts | Disabled |
| Allowed Tool Names | Leave empty for first discovery |
| Request Timeout | `30` |
| Connect Timeout | `10` |
| SSE Read Timeout | `300` |
| Retry Count | `0` |
| Retry Backoff Seconds | `1` |

Click **Discover Tools**. A successful discovery should return these tools:

```text
server_info
ping
inspect_headers
require_headers
require_auth
echo_payload
mock_search
slow_response
always_fail
```

Save the action and assign it to a test agent if you want to validate agent-driven tool use. For direct validation, ask the test agent for simple operations such as:

```text
Use the local MCP action to ping with message "hello from SimpleChat".
```

or:

```text
Use the local MCP mock_search tool to search for "phase one validation" with 2 results.
```

## Custom header test

Configure custom headers in SimpleChat:

```json
{
    "X-SimpleChat-Test": "phase1",
    "X-Splunk-Host": "local-search-head"
}
```

Call the `require_headers` MCP tool with:

```json
{
    "required_headers": ["X-SimpleChat-Test", "X-Splunk-Host"],
    "expected_headers": {
        "X-SimpleChat-Test": "phase1",
        "X-Splunk-Host": "local-search-head"
    }
}
```

Expected result: `success` is `true`.

## Auth precedence test

Configure SimpleChat MCP auth as Bearer with key value `real-auth-token`, then also add a custom `Authorization` header:

```json
{
    "Authorization": "Custom custom-header-value",
    "X-SimpleChat-Test": "phase1"
}
```

Call the `require_auth` MCP tool with:

```json
{
    "auth_type": "bearer",
    "expected_token": "real-auth-token"
}
```

Expected result: `success` is `true`, proving the configured auth header won over the custom `Authorization` header.

## Ingress auth tests

You can force discovery and all tool calls to require a header:

```powershell
python application\development\local_mcp\server.py --require-header-value X-SimpleChat-Test=phase1
```

Or require bearer auth at the MCP HTTP boundary:

```powershell
python application\development\local_mcp\server.py --require-bearer-token real-auth-token
```

These modes are useful for validating SimpleChat discovery errors and authentication configuration.

When running with the required header gate above, configure SimpleChat custom headers as:

```json
{
    "X-SimpleChat-Test": "phase1"
}
```

Discovery should succeed with the header and fail without it.

## Phase 1 validation checklist

Use this local server to validate the outbound MCP Phase 1 behavior:

- Baseline streamable HTTP discovery succeeds with no auth.
- Custom headers are sent during discovery and tool invocation.
- Header values are not displayed in the SimpleChat summary or logs.
- Configured auth headers override conflicting custom headers.
- Invalid custom header names are rejected before discovery.
- WebSocket transport rejects custom/auth headers.
- Retry settings are accepted in the configured range.
- `always_fail` produces a classified/redacted failure.
- `slow_response` can be used with low timeouts to validate timeout classification.
- Reopen/edit/rediscover preserves stored custom header references without exposing raw values.

## Available tools

| Tool | Purpose |
| --- | --- |
| `server_info` | Returns server capabilities and observed header names. |
| `ping` | Basic smoke-test response. |
| `inspect_headers` | Inspects selected headers and redacts sensitive values by default. |
| `require_headers` | Verifies required and expected custom headers. |
| `require_auth` | Verifies bearer, API key, or basic auth without echoing secrets. |
| `echo_payload` | Echoes JSON arguments for schema and payload tests. |
| `mock_search` | Returns deterministic mock search results. |
| `slow_response` | Delays for bounded timeout/retry testing. |
| `always_fail` | Raises a deterministic error for error classification testing. |

Use fake values only. Do not send production tokens or customer data to the local test server.
