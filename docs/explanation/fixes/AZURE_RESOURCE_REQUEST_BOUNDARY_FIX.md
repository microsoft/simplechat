# Azure resource request boundary fix (0.261.457)

**Fixed/Implemented in version: 0.261.457**

`application/single_app/config.py` records the implementation version. The branch
now incorporates merged Graph Development commit
`709426a41ffda5a34de453f9f00677a50fe6bcf0` (0.261.456), making Azure 0.261.457
the next patch version. Passing required checks and specific user approval are
still required before merging the Azure PR.

## Issue and root cause

This fix addresses CodeQL alerts
[1089](https://github.com/microsoft/simplechat/security/code-scanning/1089) and
[1092](https://github.com/microsoft/simplechat/security/code-scanning/1092),
`py/partial-ssrf`, originally observed on Development commit
`4dd6d80230fe60e3cbfe8544d1d52308a14a7387` (0.261.422).

Existing resource quoting, authorization, cloud configuration, and non-admin
application-identity policy already constrain the requests. The reproduced gaps
are in path construction, not evidence that critical exploitation is established.

Cosmos resource quoting leaves `.` and `..` unchanged. Requests normalizes these
segments when preparing a request, so a `..` container name selects the database
throughput path instead of the container throughput path. The outbound ARM helper
previously accepted the assembled path without validating its structure.

Foundry discovery previously appended a separate `project_name` without quoting.
Traversal, query delimiters, and fragments could therefore change the effective
project discovery path after the existing origin policy check. The route also
acquired its token before resolving the project base.

## Technical changes

### Cosmos ARM requests

`functions_cosmos_throughput.py` retains the existing resource builders,
`_quote_part`, management-endpoint resolution, and synchronous credentials.
Literal dot-segment names are refused. At `_arm_request`, before credential
acquisition or HTTP, the already-encoded path must match an existing Cosmos SQL
database/container throughput, container-list, or autoscale migration operation.
Components must have valid URI escapes and cannot decode into dot segments,
path/query/fragment delimiters, backslashes, or control characters.

The path is validated, not quoted a second time. The fixed ARM API version is
passed through Requests `params`. Authorization, JSON payloads, supported
operations, the 30-second timeout, and shared request-context reuse are preserved.

### Foundry project discovery

`resolve_foundry_project_base` in `foundry_agent_runtime.py` validates HTTP(S)
structure, refuses embedded credentials, query/fragment injection, malformed
authorities/ports, and literal or encoded dot segments, and quotes an appended
project name as one URI component.

An embedded `/api/projects/` endpoint still takes precedence over the separate
project-name field. Existing URI escapes are preserved while raw spaces and
Unicode are encoded. Configured administrator gateway prefixes and suffix paths
remain opaque project bases; private/custom origins, HTTP(S), explicit ports,
and IP destinations are not replaced with a public-cloud allowlist.

`route_backend_models.py` resolves the project base and API-version parameters
before constructing the existing synchronous token credential.

### Compatibility and scope

The shared Azure host and application-identity policy modules are unchanged.
Group and personal application-identity violations still fail before credential
construction, token acquisition, or HTTP. Compliant Commercial and Government
endpoints, caller-owned service principals, and stored global endpoints reached
through group routes retain their intended trust.

The shared group endpoint harness receives only current import-contract parity:
resolver standard-library globals, two content-safety constants, and the existing
bootstrap-free inference URL helper. No Cosmos double, route, authorization
decorator, settings key, browser asset, deployer, or provisioning behavior changes.

Only the unchanged Foundry upload query owner's inventory entry is reviewed for
the changed module AST fingerprint. The live base's existing witness is retained,
and the real-module installed-SDK upload regression is added. No unrelated owner
reviews are approved and no storage-source correction is introduced.

## Testing and validation

The initial regression selectors reproduced seven failures and four passes on
the unchanged source. New regressions capture actual Requests `PreparedRequest`
objects at `Session.send`, checking the effective origin/path/query,
authorization, method, JSON body, timeout, and refusal before credential/token/HTTP
operations.

### Initial publication (historical)

On Development `21f2b9c8c2d795df445eadaf3250532edf972b08`, the combined ARM,
Foundry, identity, scoped discovery/membership/transport, and both query-owner
witness selections passed: **256 tests**. The optimized-Python boundary and
synchronous-credential selection passed: **107 tests**.

The route policy scripts passed 15/15, 10/10, and 5/5 checks respectively. The
changed-line broken-access-control and XSS guardrails passed for the four modified
production files, and `git diff --check` passed.

At that publication, the Cosmos gate stopped before runtime contracts on
**31 inherited owner-review gaps**:
eight in `functions_settings.py`, 18 in `route_backend_orchestration.py`, and
five in `route_backend_users.py`. The five profile reviews were subsequently
addressed within the separately merged Graph module scope; 31 is not the
post-Graph gate count.

### Post-Graph base synchronization

After merging Development `709426a41ffda5a34de453f9f00677a50fe6bcf0`, the combined
Azure, Graph, scoped compatibility, and installed-SDK owner-witness selection
passes: **457 tests**. The optimized-Python boundary and synchronous-credential
selection passes: **107 tests**. The sole merge conflict was the application
version; retaining 0.261.457 resolves it as the next version after Graph 0.261.456.
The route policy scripts again pass 15/15, 10/10, and 5/5 checks. The four-file
changed-line access-control and XSS guardrails, plus staged/unstaged whitespace
checks, also pass against the merged base.

All canonical Graph, profile, and interface-selection inventory reviews and
witnesses are preserved exactly from that base. Only the Azure-owned unchanged
Foundry query-owner entry differs from the base inventory.

`python scripts\check_cosmos_response_boundaries.py --run-contracts` still stops
before runtime contracts on **26 inherited owner-review gaps**: eight in
`functions_settings.py` and 18 in `route_backend_orchestration.py`. Of these,
25 differ only in the module fingerprint; `orchestration_plan` also differs in
its owner AST fingerprint. No fingerprint is blanket-approved, no affected
storage consumer is repaired in this PR, and no runtime-contract pass is claimed.

The regression files are:

- `functional_tests/test_cosmos_throughput_request_boundary.py`
- `functional_tests/test_foundry_project_request_boundary.py`
- `functional_tests/test_foundry_model_fetch_sync_credentials.py`

Run Python selections with:

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -m pytest -q -p test_support.cosmos_network_guard -p no:cacheprovider functional_tests\test_cosmos_throughput_request_boundary.py functional_tests\test_foundry_project_request_boundary.py functional_tests\test_foundry_model_fetch_sync_credentials.py --tb=short
```

Both `test_recent_chat_upload_inputs_consume_sdk_query_rows` in
`test_foundry_orchestration_polling_budget.py` and
`test_foundry_chat_upload_query_owner_contract` in
`test_agent_credential_owner_runtime.py` pass on the integrated branch. The
former runs the real module with installed-SDK point wrappers and plain query
rows, covering partition routing, upload filtering, size limits, and deduplication
with Blob I/O isolated.

No live Azure request or shared-host dependency mutation is required. Network
access is blocked before pytest collection by `test_support.cosmos_network_guard`.

### Before and after

| Input or behavior | Before | After |
| --- | --- | --- |
| ARM container `..` | Prepared URL selects database throughput | Refused before credential/HTTP |
| Encoded dot segment in supplied ARM path | Not checked at outbound boundary | Refused before credential/HTTP |
| Raw Foundry project traversal/query/fragment | Can change prepared discovery path | Quoted as one component, or refused for a dot segment |
| Invalid Foundry project base | Can acquire a token before resolution fails | Validated before credential construction |
| Already-encoded embedded project endpoint | Used as configured | Precedence and escapes preserved |
| Administrator private/custom gateway | Configured trust | Valid origins, ports, prefix/suffix paths retained |
| Non-admin application-identity violation | Existing policy refusal | Same refusal before credential/token/HTTP |

## CodeQL evidence and limitations

The exact baseline analysis is Python SARIF `2117078539`, CodeQL 2.27.4,
`codeql/python-queries` 1.9.0, build
`1be292a1e54696ca543b4ad0f9b4537b9687caa7`. With that unchanged bundled
`PartialServerSideRequestForgery.ql`, separate local databases reproduce one
result at each selected baseline sink and zero results in either corrected sink
function. Both selected files are present in both finalized source archives.

The initial publication scan at head
`dda0be25f30cb0bb728e4157a2a3bed512c74895`, PR merge-ref SHA
`78d6f3411474321612096ff816254c3662e39ad8`, also reported no selected sinks.
That clearance is historical after the Graph base merge, not clearance for the
new source head. Fresh GitHub confirmation must use the post-sync PR ref and
`.github/workflows/codeql.yml:analyze`, category `/language:python`, rather than
unrelated fixed instances on default/main setup.
No exclusions, suppressions, dismissals, severity changes, or query/configuration
changes are used. Other alerts and inherited unrelated CI review gaps remain
outside this fix.
