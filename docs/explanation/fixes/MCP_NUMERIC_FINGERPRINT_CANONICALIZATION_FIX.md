# MCP Numeric Fingerprint Canonicalization Fix

Fixed in version: **0.261.459**

Related version update: `application/single_app/config.py` advances `VERSION`
from `0.261.458` to `0.261.459`.

## Issue and root cause

An outbound MCP tool could be discovered successfully but fail to save with
`MCP tool fingerprints do not match the approved discovery metadata.` even when
its definition had not changed.

Discovery computed a fingerprint from Python JSON serialization. A schema
default such as `90.0` was serialized with a decimal point. The browser parsed
the discovery response and later serialized the same value as `90` when saving
the action. The server then hashed a different JSON representation and rejected
the unchanged metadata.

The same representation mismatch could affect runtime filtering and live
manifest checks, as well as numbers nested in output schemas, annotations, or
prompt arguments.

## Technical details

`application/single_app/functions_mcp_tool_pinning.py` now recursively
canonicalizes finite whole-number floats to equivalent integers on a temporary
hash payload before applying the existing sorted JSON serialization and SHA-256
hash. For example, `90.0` and `90` now have the same fingerprint.

The implementation does not modify discovered metadata or tool arguments. It
preserves fractional values, booleans, strings, schema type declarations, and
array ordering. Actual metadata changes still require approval; numeric strings
are not treated as numbers, and booleans are not treated as zero or one.

Discovery, save validation, runtime tool filtering, and live manifest comparison
continue to share the same hash implementation. No frontend, route, scope
authorization, destination governance, or tool allowlist changes are needed.

The module also owns drift persistence. Its complete-module Cosmos inventory
fingerprint is therefore refreshed in
`functional_tests/cosmos_response_boundaries.json`, with real-owner SDK-shaped
runtime evidence in `functional_tests/test_mcp_drift_cosmos_contract.py`.
Storage behavior is unchanged.

## Existing approvals and recovery

Approvals containing whole-number floats whose hash representation changes
require **one-time rediscovery and reapproval**. Until then, their existing
fingerprints can fail save validation or mark affected tools as changed at
runtime. Fingerprints whose representation is unchanged remain compatible,
including integer-only schemas and fractional defaults such as `0.25`.

To recover an affected action, use its existing MCP discovery flow, review the
returned tools and prompts, and save the newly approved metadata. Do not edit
stored hashes manually. The fix deliberately provides no legacy-hash fallback
and does not automatically approve a changed fingerprint.

This is a focused numeric representation fix, not a general JSON
canonicalization standard implementation. It does not repair JavaScript
precision loss for integers outside its safe integer range; values that really
change must still fail fingerprint checks.

## Validation

`functional_tests/test_mcp_tool_fingerprint_pinning.py` covers whole-number
defaults, negative numbers, signed zero, nested objects and arrays, output
schemas, annotations, prompt arguments, discovery-to-save validation, runtime
filtering in both representation directions, unchanged input metadata,
unaffected legacy hashes, and rejection of affected old approvals. It also
checks that changed values, fractional changes, schema type changes,
boolean/number differences, string/number differences, and reordered arrays
still register as drift.

`functional_tests/test_mcp_drift_cosmos_contract.py` executes the real drift
owner for personal, group, and global actions using the installed SDK's
`CosmosDict`. It verifies retained fields and updated ETags, scope-specific read
routing, persisted drift, and idempotent notification retries through the
existing conflict/read path.

The targeted command passed **40 tests**:

```powershell
python -m pytest functional_tests\test_mcp_tool_fingerprint_pinning.py functional_tests\test_mcp_phase2_probe_metadata.py functional_tests\test_mcp_action_route_security.py functional_tests\test_mcp_drift_cosmos_contract.py -q -p no:cacheprovider
```

An additional real Node JSON parse/stringify check passed discovery, save, and
runtime filtering for seven values: `90.0`, `-90.0`, `-0.0`, `0.25`, `1e20`,
`1e21`, and `1e-7`.

The standalone fingerprint runner passed **19 tests**. A separate network-blocked
run passed **23 tests**, including the MCP regressions, all three drift-owner
scopes, and the installed SDK response-shape contract:

```powershell
python functional_tests\test_mcp_tool_fingerprint_pinning.py
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -m pytest -p test_support.cosmos_network_guard functional_tests\test_mcp_tool_fingerprint_pinning.py functional_tests\test_mcp_drift_cosmos_contract.py functional_tests\test_m365_cosmos_sdk_contract.py::test_real_sdk_point_documents_are_wrapped_but_nested_json_and_query_rows_are_plain -q -p no:cacheprovider
```

The changed MCP owner's inventory entry and runtime evidence reference pass
isolated inventory validation. The repository-wide command
`python scripts\check_cosmos_response_boundaries.py --run-contracts` stops before
running its full contract suite because of **26 pre-existing review gaps** in
`functions_settings.py` and `route_backend_orchestration.py`. Neither module is
changed by this fix; their unrelated inventory entries are left unchanged.

Before the fix, the unchanged `90.0` discovery / `90` save pair was rejected.
After the fix, that representation-only change passes while real definition
changes remain blocked pending approval.
