# Yamcs Action

Implemented in version: **0.250.212**

Related config.py version update: `application/single_app/config.py` is **0.250.212** for this implementation.

## Overview

The Yamcs action lets users connect SimpleChat agents to a [Yamcs](https://yamcs.org) mission control server through a first-class, read-only action. It uses the official Yamcs Python client, `yamcs-client`, and exposes telemetry, mission database, data link, and archive retrieval tools.

The action has its own configuration workflow in the Add/Edit Action modal, including a **Test Yamcs Connection** button. It does not reuse the OpenAPI, Databricks, or generic action forms.

Fixed/Implemented in version: **0.250.212**

## Safety Model

**This action is strictly read-only.** It cannot issue commands, set parameter values, run scripts, or enable/disable data links. The Yamcs Python client supports all of those operations; SimpleChat deliberately does not expose any of them. `list_commands` returns mission database command *definitions* only and never issues a command.

The read-only guarantee is enforced in three places:

1. Only read functions are declared in `YamcsPlugin.get_functions()` and in the plugin metadata, so no write operation is ever offered to an agent.
2. `additionalFields.read_only` is forced to `true` by `normalize_yamcs_additional_fields()` and cannot be turned off from a stored manifest.
3. The optional archive SQL function is disabled by default and, when enabled, is restricted to `SELECT`, `SHOW`, `DESC`, and `DESCRIBE` statements with a forbidden-keyword guard.

## Dependencies

- Python package: `yamcs-client==2.1.0`
- A reachable Yamcs server URL, for example `https://yamcs.example.com:8090`
- Yamcs username/password, API key, bearer token, or a reusable workspace identity — or no credentials for an unsecured server
- Existing SimpleChat action storage, Key Vault secret handling, and Semantic Kernel plugin loading

### Licensing note

`yamcs-client` is licensed **LGPL-3.0**. It is consumed as an unmodified, dynamically linked pip dependency, which is the standard-compliant usage pattern. It is the first LGPL dependency in this repository, so downstream redistributors should confirm this fits their compliance posture.

### Protobuf compatibility

`yamcs-client` vendorizes its own protobuf runtime under `yamcs/protobuf/_vendor`, so it does **not** conflict with the repository's pinned `protobuf==6.33.5`. This has been verified with both packages installed together.

## Technical Specifications

- Plugin type: `yamcs`
- Runtime plugin: `semantic_kernel_plugins.yamcs_plugin.YamcsPlugin`
- Factory: `semantic_kernel_plugins.yamcs_plugin_factory.YamcsPluginFactory`
- Shared defaults and normalization: `functions_yamcs_operations.py`
- Additional settings schema: `application/single_app/static/json/schemas/yamcs_plugin.additional_settings.schema.json`
- Allowed auth definition: `application/single_app/static/json/schemas/yamcs.definition.json`
- Test connection endpoint: `POST /api/plugins/test-yamcs-connection`

Supported Semantic Kernel functions, all read-only:

| Function | Purpose |
| --- | --- |
| `list_instances` | List Yamcs instances available on the server |
| `list_links` | List data links with status and packet counts |
| `list_parameters` | List mission database parameters, filterable by name text or parameter type |
| `describe_parameter` | Describe one parameter, including type, units, and enumerations |
| `list_commands` | List command *definitions* only; never issues a command |
| `get_parameter_values` | Read the latest processed values for one or more parameters |
| `list_parameter_history` | Read archived values for a parameter over a time range |
| `list_events` | Read archived events, filterable by severity, source, and text |
| `list_packets` | Read archived telemetry packet metadata |
| `list_alarms` | Read archived alarms |
| `execute_archive_sql` | Run a guarded read-only archive SQL statement; disabled by default |

### Endpoint handling

The action stores the normalized Yamcs server URL as its `endpoint`, mirrored into `additionalFields.server_url`. A URL entered without a scheme is normalized to `https://`.

This normalization matters: a bare `host:port` address such as `yamcs.example.com:8090` is interpreted by the Yamcs client as **plain HTTP**, and Python's `urlparse` misreads the hostname as a URL scheme. SimpleChat therefore detects the scheme with an explicit `^https?://` check and defaults to HTTPS.

### Result bounding

Every retrieval is bounded before it reaches an agent:

- Yamcs list APIs return lazily paginating iterables, so each call is capped with `itertools.islice(..., max_rows)`.
- Serialized results are truncated at `byte_limit`.
- Responses report `row_count` and a `truncated` flag.
- Error messages pass through a secret redaction filter before being returned or logged.

## Configuration Options

- `server_url`: Yamcs server base URL including port. TLS is derived from the scheme.
- `instance`: default Yamcs instance, for example `simulator`.
- `processor`: processor used for live parameter reads; defaults to `realtime`.
- `auth_method`: `username_password`, `api_key`, `bearer_token`, or `none`.
- `tls_verify`: verify the server TLS certificate; defaults to `true`.
- `read_only`: always `true`; stored for parity with other connector actions.
- `enable_archive_sql`: allow guarded read-only archive SQL; defaults to `false`.
- `max_rows`: per-call row limit, bounded from 1 to 5000; defaults to 500.
- `timeout`: HTTP request timeout in seconds, bounded from 1 to 300; defaults to 30.
- `byte_limit`: approximate serialized result size limit, bounded from 1000 to 2000000.

### Authentication mapping

| UI authentication method | `auth.type` | `auth.identity` | `auth.key` | Yamcs client credential |
| --- | --- | --- | --- | --- |
| Username and Password | `username_password` | username | password | `Credentials(username=..., password=...)` |
| API Key | `key` | — | API key | `APIKeyCredentials(key)`, sent as `x-api-key` |
| Bearer Token | `key` | — | access token | `Credentials(access_token=...)` |
| No Authentication | `NoAuth` | — | — | `None` |
| Reusable Identity | `identity` | identity id | resolved at runtime | resolved from the identity auth type |

Reusable identities are accepted when their auth type is `api_key`, `bearer_token`, or `username_password`.

## Usage Instructions

Create a new action from a personal, group, or admin action surface and choose **Yamcs**. Enter the Yamcs server URL and the instance name, and optionally change the processor from the `realtime` default.

Choose an authentication method and supply the matching credential, or select an action-capable reusable identity from the Yamcs identity selector. Choose **No Authentication** only for unsecured Yamcs instances such as a local simulator.

Use **Test Yamcs Connection** to confirm the server is reachable, the credentials are accepted, and the configured instance exists. The test reports the Yamcs version and the number of available instances. When editing a saved action, the stored credential is resolved from Key Vault automatically, so the secret does not need to be re-entered to run a test.

If your agents need ad hoc archive queries, enable **read-only archive SQL**. Leave it off unless it is needed.

After saving the action, assign it to agents that need Yamcs telemetry or archive access. Agents can read whatever the configured Yamcs credentials are authorized to read.

## Testing and Validation

- Functional coverage: `functional_tests/test_yamcs_action_plugin.py` (14 tests)
- Route policy coverage: `functional_tests/route_tests/` — the new endpoint is covered by the existing authenticated-route prefix rules
- JavaScript syntax checks: `plugin_modal_stepper.js` and `workspace/view-utils.js`
- Python compile checks cover the Yamcs helper, plugin, factory, loaders, health checker, routes, identity, Key Vault, and governance updates
- The credential mapping, client constructor behavior, and protobuf coexistence were verified against a real `yamcs-client==2.1.0` install

## Known Limitations

- The action is read-only in version 0.250.212. Commanding is intentionally out of scope.
- Yamcs permissions are enforced by Yamcs for the configured credentials.
- Streaming and subscription APIs (parameter, packet, event, and alarm subscriptions) are not exposed, because agent tool calls are request/response.
- Testing a connection that uses a reusable identity requires saving the action first.
- Live connectivity is validated only when credentials and a reachable Yamcs server are configured in the running app.
