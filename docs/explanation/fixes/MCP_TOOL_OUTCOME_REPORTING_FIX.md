# MCP tool outcome reporting fix (v0.261.371)

Fixed/Implemented in version: **0.261.371**

Related configuration update: `VERSION = "0.261.371"` in
`application/single_app/config.py`.

## Issue and root cause

An MCP tool could fail while SimpleChat's reasoning and Sources inspector
reported that its invocation succeeded. There were two application boundaries
behind this mismatch:

- The pinned Semantic Kernel MCP connector converted the protocol's
  `CallToolResult` to content blocks, losing its `isError` flag. SimpleChat then
  wrapped those blocks with `success: true`.
- MCP validation and execution branches returned failure dictionaries without
  explicitly reporting failure to the invocation logger. A normal return was
  consequently recorded as successful, even when the returned envelope said
  `success: false`.

Dynamic MCP tools delegate to the generic `call_tool` function. Each has its own
invocation logging scope, so the failure must be reported in both scopes.

## Technical changes

`application/single_app/semantic_kernel_plugins/mcp_plugin_factory.py` calls the
connected MCP session directly to retain the typed protocol response. It checks
that a session exists and tool loading is enabled before invoking a tool.
The existing pinned SDK conversion helper still supplies the content blocks,
preserving their text, image, and audio representation.

A protocol response with `isError: true` now produces `success: false`,
`error_type: "tool_error"`, a stable failure message, and `retryable: false`.
Returned content remains subject to the existing result-size and sanitization
boundaries. Server error text is not promoted into the public failure message.
The factory records the protocol failure using the existing `MCP_OUTBOUND`
logging tag.

`application/single_app/semantic_kernel_plugins/mcp_plugin.py` uses the existing
`report_plugin_invocation_failure` helper at its generic and dynamic decorated
entry points. This covers locally rejected arguments, disallowed tools,
configuration and permission failures, transport exceptions, and server-reported
tool failures.

No shared logger heuristic is added. Business content containing fields such as
`error`, `isError`, or `success: false` does not become an invocation failure
when the protocol reports success.

The existing reasoning formatter and chat citation builder consume the recorded
outcome. The Sources inspector therefore displays **Tool call failed** and the
safe error message without a frontend-specific classifier.

## Compatibility and usage

No setting, migration, or action reconfiguration is required. After an agent
reply, expand the tool disclosure in **Sources** to compare the recorded outcome
with the returned evidence.

Successful result envelopes and SDK content conversion are retained. Existing
authorization, destination governance, fingerprint pinning, argument
normalization, connection cleanup, and configured bounded transport retries
remain in place. A protocol tool error does not trigger an automatic replay.

Tool selection and built-in math behavior are unchanged. This fix does not
force an agent to choose MCP over another available tool. It also does not
rewrite historical messages whose invocation outcomes were recorded earlier.

## Regression coverage

`functional_tests/test_mcp_tool_outcomes.py` executes real application modules,
typed MCP results, and real Semantic Kernel generic/dynamic invocation paths in
fresh normal and optimized Python processes. External I/O is mocked and network
access is blocked.

Coverage includes protocol errors with and without content; successful business
data resembling an error; validation and admission failures; configuration,
permission, and transport failures; bounded transport recovery; missing or
disabled sessions; result-size policies; unchanged multimedia conversion;
secret redaction; invocation/callback identity; reasoning and citation
construction; and subsequent or concurrent successful execution.

The existing argument-normalization and authorization fixtures are updated for
the native session call and SDK content-conversion boundary. They do not replace
the new real-module outcome coverage.

## Validation and limitations

Implementation validation uses a session-local environment with
`semantic-kernel==1.39.4`, `mcp==1.28.1`, and `pytest==9.0.3`. Shared machine
packages and application dependency manifests are unchanged.

The new normal/optimized outcome probes and existing OpenAPI/shared outcome
probes pass. The documented standalone MCP normalization, metadata, fingerprint,
manifest, and outbound logging regressions also pass.

| Command | Result |
| --- | --- |
| `python -m pytest functional_tests\test_mcp_tool_outcomes.py functional_tests\test_plugin_invocation_outcomes.py -q --tb=short` | Passed: 6 normal/optimized subprocess cases. |
| `python -m pytest functional_tests\test_mcp_authorization_context.py -q --tb=short -k "not agent_merges and not credential_hydration and not denied_or_retired_records and not failed_identity_hydration and not logged_and_fallback_loaders and not python_loader"` | Passed: 22 tests and 130 subtests; 7 baseline loader-fixture failures deselected. |
| `python functional_tests\test_mcp_tool_argument_normalization.py` | Passed. |
| `python functional_tests\test_mcp_phase2_probe_metadata.py` | Passed. |
| `python functional_tests\test_mcp_tool_fingerprint_pinning.py` | Passed. |
| `python functional_tests\test_mcp_action_manifest_workflow.py` | Passed. |
| `python functional_tests\test_mcp_outbound_logging.py` | Passed. |
| `python functional_tests\test_docs_app_surface_coverage.py` | Passed: 7 checks; inventory unchanged and current. |
| `python functional_tests\test_docs_site_quality.py` | Passed: 6 checks. |
| `python scripts\check_xss_sinks.py application\single_app\semantic_kernel_plugins\mcp_plugin.py application\single_app\semantic_kernel_plugins\mcp_plugin_factory.py --base-sha HEAD` | Passed. |
| `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check` | Passed. |

The broader authorization suite has seven pre-existing loader-fixture failures:
its mocked `functions_msgraph_operations` module lacks
`MSGRAPH_CAPABILITY_DEFINITIONS`. The same loader failure was reproduced with
the unchanged `HEAD` authorization test, MCP plugin, and factory loaded from
Git objects without editing the worktree. Those unrelated fixtures are not
repaired or waived by this change.

The older `python functional_tests\test_local_mcp_server.py` runner is also
blocked before tool execution because its manifests omit the required trusted
action origin. The same failure occurs with the unchanged `HEAD` plugin and
factory. Its loopback server was stopped by the runner's cleanup; no
authorization guard was bypassed to make that test pass.

Live investigation was read-only. This change has not been deployed, no new
live acceptance run was submitted, and existing conversations, agents, actions,
and settings were not modified. External harness findings are retained
separately as a session artifact.
