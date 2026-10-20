# Action connection-test credential intent fix

**Fixed in version: 0.261.351**

Application version: `application/single_app/config.py`, advanced from
`0.261.350` to `0.261.351`. Dependencies are the existing V2 build, Flask,
workspace-authoring validation, and connector testers; no new package or setting
is required.

## Issue and root cause

New no-auth OpenAPI drafts could fail with
`Invalid action connection test configuration.` before reaching a connector.
The shared V2 OpenAPI/MCP request builder unconditionally declared six auth
fields as stored-secret clears, even without a saved action or when only some
fields were stored secrets. The backend correctly rejected that intent but
collapsed its typed validation error into a generic message.

The same producer serves connection testing and MCP discovery across personal,
group, and global editors. This was not specific to an API, operation, action
name, or acceptance scenario. Contract coverage also exposed an MCP discovery
fallback that could restore a stored username after a no-auth edit. Discovery's
request feedback was not rendered, hiding both success and failure details.

## Technical changes

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/workspaceActionConnectors.ts` | Derive auth clears only from the original resource's owned secret paths; canonicalize no-auth before mask translation and retain independent header clears. OpenAPI keeps its compatible empty-key representation; MCP uses `NoAuth`. |
| `application/single_app/route_backend_plugins.py` | Preserve typed authoring-validation messages and preparation-stage categories; log safe rejection metadata without arbitrary exception text; skip discovery credential fallback for `NoAuth`. |
| `application/v2_ui/src/components/workspaceActions/McpActionConfiguration.tsx` | Render the existing shared feedback panel and discovery progress beside the discovery control. |
| `functional_tests/test_action_connection_payload_contract.py` | Execute the shipping TypeScript producer and feed its JSON through real Flask route bodies, preparation, and validation under scoped external-service seams. |
| `functional_tests/test_v2_workspace_action_connectors_logic.mjs` | Cover new and saved no-auth intent across editor scopes and commands. |
| `ui_tests/test_v2_workspace_authoring.py` | Exercise the built SPA's unsaved/saved commands and visible preparation diagnostics across supported layouts. |

Existing backend credential-clear validation, route authentication, ownership,
group policy, Admin requirements, and MCP destination policy remain in place.
Invalid or foreign secret paths do not become valid because a client declares
them. No automatic save, operation invocation, retry, or external-write replay
was added. Clearing credentials for a transient test does not change storage.

## Validation and behavior

Before the fix, no-auth drafts sent phantom clears and could be rejected before
connector I/O. After the fix, new drafts send no clears; saved drafts clear only
owned auth secrets and preserve unrelated headers. Known failures identify
`invalid_editor_configuration` at `request_preparation`; unexpected errors remain
generic. MCP discovery retains its operation identifier.

The producer-to-route regression covers all three commands in personal, group,
and global scopes, including saved credential subsets and legacy auth aliases.
It checks a single tester/probe call, no storage mutation, no unnecessary secret
read, independent custom-header removal, malformed/non-secret path rejection,
and response/log redaction. External sockets and DNS are blocked, with only
Windows asyncio's internal wakeup socketpair permitted.

Browser tests use the real production SPA with synthetic HTTP fixtures. They
verify emitted requests and visible feedback, not an external connector or model
result. The producer-to-route contract independently covers the real backend
boundary that those fixtures replace.

Recorded focused results: **98** network-blocked endpoint, producer/backend,
redaction, group-policy, and Cosmos-owner tests passed. Together with **50** core
Cosmos SDK contracts, the final focused run passed **148** tests using the
application's pinned SDK. **37** shared client logic checks and **26** new
responsive browser cases passed. Type checking, the production SPA build,
route policy, and documentation checks passed.

The Cosmos inventory was refreshed and the three unchanged storage owners in
the edited route module were reviewed with dedicated runtime evidence in
`functional_tests/test_action_route_cosmos_response_contract.py`; no storage
normalization was added. The inventory has no review gaps. Its full runtime
gate passed **1,126** tests and **244** subtests with external network access
blocked.

The initial local collection and bootstrap failures were resolved in a
session-only virtual environment, restoring the repository's Flask, Werkzeug,
Semantic Kernel, YAMCS client, and Cosmos SDK pins and a cryptography version
compatible with the installed PyOpenSSL. The shared Python installation and
application dependency manifests were not changed. The gate excluded an
unrelated inherited Dash pytest plugin; no application modules or contract
checks were replaced.

Other existing workspace-backend and MCP route-security suites still have
baseline failures: their exact failed-case sets matched untouched `HEAD` route
source in fresh processes. This is not a claim that every repository suite
passes.

Base integration advanced this fix from the initial branch version 0.261.349
to 0.261.351, preserving the base's 0.261.350 memory-resolution changes.
Post-merge validation passed **219** connector, SDK, memory-resolution,
bootstrap, and documentation tests with **5** subtests, plus the **37** client
checks and **26** browser cases. The inventory again had no review gaps.
The full runtime-gate result above was recorded before this base merge.

### Limits

This fix does not qualify downstream agent/tool execution, deploy the application,
or rerun live acceptance cases. OpenAPI connection success verifies specification
loading and base-URL reachability, not a selected operation result. MCP testing
and discovery do not invoke tools. Original failures must remain recorded when a
separately authorized deployment is later qualified.

See [Action Test Connection](../features/ACTION_TEST_CONNECTION.md) for connector
checks and [OpenAPI](../../reference/actions/openapi.md) /
[MCP](../../reference/actions/mcp.md) for user workflows.
