# Plugin outbound destination guard (v0.261.432)

Fixed/Implemented in version: **0.261.432**.

The application version is recorded in `application/single_app/config.py`.
There is no new capability toggle, administrator destination allowlist, or
deployer version change.

## Issue and root cause

Configurable action connection tests and runtime clients did not consistently
enforce a destination boundary. URL shape checks, optional MCP literal-address
checks and user authentication did not establish which address a client would
actually connect to. Redirects and a second DNS lookup could undermine an
earlier check.

Some connection tests also did not apply the corresponding authoring/type
permissions, and changing an endpoint could implicitly reuse an opaque saved
credential. Hiding a secret in the editor does not prevent the server from
forwarding it to a different destination.

## Technical changes

`functions_outbound_destinations.py` supplies bootstrap-free URL/origin and IP
rules. Legitimate private routing remains allowed. Loopback, link-local,
unspecified, multicast, reserved non-host and cloud infrastructure destinations
are rejected, including mapped address representations.

`functions_outbound_http.py` binds direct Requests, aiohttp and HTTPX connections
to vetted addresses without substituting an IP for the original HTTP Host or
TLS hostname. All DNS candidates must be acceptable. Redirects are bounded and
cannot cross origins or downgrade TLS; a default-port upgrade on the same host
is allowed. Requests clients do not import ambient server `.netrc` credentials.
Connection probes consume only headers or a bounded response body as needed.

MCP SSE/streamable HTTP use the native client's guarded HTTPX factory hook.
The compatible WebSocket adapter preserves native MCP message streams while
using a vetted socket, rechecking redirected connections and closing resources.
Existing MCP scope, allowlist, tool-pinning and authentication rules remain.
Destination-policy failures are non-retryable and use safe error categories.

The client integrations cover OpenAPI, RocksDB, Yamcs, Tableau, Smart HTTP,
Databricks and the shared HTTP connection probes. SDK transport protection is
installed before initial authentication or version discovery. The loader does
not fall back to an unguarded HTTP plugin.

`route_backend_plugins.py` authorizes personal/group/global connection tests
before credential use. `functions_workspace_authoring.py` checks authoritative
connection origins during merges; the legacy personal/global write paths and
transient test/discovery paths apply the same credential-retention rule.
Changing an origin or connector requires explicit replacement or clearing of
retained credentials. Unchanged-origin edits and credential rotation are not
blanket-reset.
Client-supplied Key Vault names must match the selected stored action field;
scope membership alone is not permission to dereference a name in a new draft.

The existing Cosmos response normalization and conditional-write contracts
remain intact. Module fingerprint reviews are renewed with owner-runtime SDK
evidence. The touched Yamcs bootstrap doubles use the shared SDK-default
container, including native point responses, ETags, query rows and stale-write
rejection.

## Compatibility and upgrade impact

Public services, reachable private IPs/FQDNs and enterprise private DNS remain
supported. Unchanged actions do not require a mandatory re-save or credential
reset. Shared-action execution does not acquire a new editor-role requirement.
Application-owned Azure identity authentication and App Service inbound routing
are outside this action transport guard.

Yamcs reverse-proxy authentication remains supported with No Authentication or
API Key authentication, including reusable/personal proxy identities. A remote
proxy forwarding to localhost on its own server is not a localhost target for
SimpleChat. A localhost URL configured on an App Service action instead points
at the SimpleChat worker/container and is refused.

Cross-origin redirects require configuring the final service URL. Deployment-
wide HTTP(S) forward-proxy routing is explicitly refused by the guarded clients,
not silently disabled or used as a destination-check bypass. Deployments using
that routing need separate compatibility review. Existing supported TLS/CA and
timeout options remain; certificate verification is not disabled to pin an IP.

This is not a redesign of non-HTTP database protocols or a complete audit of
every application feature. Custom server-side plugin implementations must use
the guarded connection helpers for their own configurable HTTP calls.

## Validation

The regressions use synthetic credentials, scoped storage seams and blocked
network access; no production, on-premises or metadata service is probed.

- `functional_tests/test_outbound_destination_policy.py` exercises forbidden
  literal/DNS targets, mixed answers, rebinding, mapped addresses, redirects,
  actual connection selection, TLS/Host preservation and cleanup.
- `functional_tests/test_plugin_outbound_destination_security.py` executes
  route/merge behavior and installed Yamcs, Tableau and MCP integration seams.
  It covers private/public compatibility, reverse-proxy headers, unchanged TLS
  settings, authoring/type denial and saved-credential retargeting.
- Existing action payload, shared-secret, connector, route policy and Cosmos
  owner-runtime suites check preservation of the established contracts.

Before the fix, forbidden targets could reach unguarded request clients and an
edited destination could inherit a saved key. After the fix, those regression
paths stop before a forbidden connection or retained-credential request, while
the positive enterprise-private and Yamcs reverse-proxy cases remain valid.

See the [connection compatibility guide]({{ '/guides/workspace-agents-and-actions/' | relative_url }}#connection-destinations-and-compatibility)
for the user/admin-facing impact matrix.
