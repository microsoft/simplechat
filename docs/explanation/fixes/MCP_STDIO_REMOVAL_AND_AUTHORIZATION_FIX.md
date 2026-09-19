# MCP Stdio Removal and Authorization Fix

Current documentation version: **0.261.031**

Fixed in version: **0.261.029**

Related configuration update: `application\single_app\config.py` advances `VERSION` from `0.261.028` to `0.261.031`. The transport and authorization fix was implemented in `0.261.029`; the initial review follow-up was implemented in `0.261.030`.

## Issue and Root Cause

Outbound MCP action configuration previously included a transport that launched a local server process. SimpleChat no longer supports that capability. Remote MCP also needs a consistent authorization contract across configuration, discovery, connection testing, and execution so that current permissions and destination restrictions apply throughout the action lifecycle.

This release removes stdio rather than introducing another privileged exception. It retains supported remote connections and provides a non-destructive path for owners to manage retired configurations.

## Supported Behavior

| Area | Behavior in 0.261.029 |
| --- | --- |
| Transports | Remote streamable HTTP, SSE, and WebSocket only. |
| Stdio | Removed for all roles and scopes, including Admin and global actions. No opt-in or privileged exception. |
| Process settings | Local command, argument, and environment configuration is no longer consumed or offered by MCP actions. |
| Existing stdio actions | Visible with an unsupported status, but cannot discover, connect, or execute. Existing IDs and agent references are retained. |
| Reconfiguration | Requires explicit remote transport selection and a valid endpoint, plus normal validation and current governance. |
| Deletion | Requires an explicit, authorized delete. Migration or omission from a bulk save is not deletion. |
| Remote compatibility | Authentication methods, headers, timeouts, tool controls, and destination/preconfiguration policies remain supported. |

Retired stdio and explicitly unknown transports are configuration errors, not retryable network failures. Stdio is rejected before credentials or connectors are used. Opening or cancelling an edit does not select HTTP or change the saved record. Unrelated supported remote actions remain usable.

## Remote Authorization

MCP type resolution is consistent across validation and execution. The server establishes each action's personal, group, or global origin from its authorized collection and partition, then evaluates the current authenticated user or the workflow's established execution identity against current settings.

These checks also apply when a previously cached tool is invoked. A global action retains its global origin when referenced from a personal or group agent. Missing required authorization context prevents a connection.

Environment-enforced destination restrictions are a non-overridable minimum. Admin Settings may tighten restrictions, but cannot disable environment-required enforcement, widen an environment allowlist, or undo environment-required unsafe-address blocking. A successful earlier test does not authorize later calls after permissions or policy change.

## Retained Records and Migration

Retired actions have a management-only representation that identifies their unsupported state without resolving credentials or exposing process configuration and secrets. This representation does not authorize execution.

Stdio records still stored in legacy `settings.plugins` stay in their existing location. They are available through management-only listing, lookup, explicit reconfiguration, and deletion rather than being copied through an executable-action save path.

The retention contract is:

- An unchanged authoritative retired record may pass through a bulk save without an action rewrite or secret write.
- Leaving a retired record out of a bulk payload does not delete it.
- New stdio records and edits that still select stdio are rejected.
- Migration processes supported records individually and removes a source record only after its successful migration is verified.
- Unsupported, conflicting, or failed records remain available; one retained record does not prevent other valid records from migrating.
- Failed replacement or source-update conflicts do not silently discard the original record. Migration reports distinguish migrated, retained, and failed outcomes.

Owners can inspect and delete their retired records even when MCP-usage governance prevents execution. This cleanup exception does not change personal ownership, group-management roles, or Admin boundaries. It does not grant execution or permission to reconfigure an action outside normal current governance.

## Owner Upgrade Workflow

1. Review actions marked as retired or unsupported in the appropriate personal, group, or global action list. Do not assume an enabled action can still execute.
2. If a replacement is needed, identify an approved, separately operated remote MCP server. SimpleChat will not launch a local process on behalf of the action.
3. Explicitly select streamable HTTP, SSE, or WebSocket and enter a valid endpoint. Review authentication, headers, timeouts, and allowed tools for that remote service.
4. Use **Test Connection** and **Discover Tools** with the required current permissions, then save the remote configuration. An unavailable endpoint or policy denial is a reason to fix the remote configuration, not to fall back to stdio.
5. If no replacement is needed, explicitly delete the retired action using the authorized management operation. Do not rely on bulk-save omission or migration to remove it.

The HTTP-based local development MCP server is unchanged and is not a new local-command execution mechanism. Inbound SimpleChat MCP is also unchanged.

## Custom Preset Compatibility

Otherwise valid remote custom presets can still load when older files contain `stdioAllowed` or retired process-only fields. The loader normalizes a copy, removes those inert fields, filters stdio out of the allowed transport list, and validates the remote-only result. A valid remote default and remote authentication, header, timeout, and provider settings are preserved.

A stdio-default or stdio-only preset becomes unavailable with a diagnostic; it is not converted to HTTP. Invalid presets are isolated so valid presets still load. Preset normalization does not modify tool arguments or similarly named provider fields, and does not automatically reconfigure a saved stdio action.

See [MCP Server Presets](../features/MCP_SERVER_PRESETS.md) and [MCP Server Preconfigurations](../features/MCP_SERVER_PRECONFIGURATIONS.md) for catalog authoring guidance.

## Technical Scope

| Files or area | Responsibility |
| --- | --- |
| `functions_mcp_operations.py`, `semantic_kernel_plugins\mcp_plugin_factory.py`, `semantic_kernel_plugins\mcp_plugin.py` | Remote-only normalization, connector selection, and invocation. |
| `functions_action_manifest.py`, `functions_mcp_destinations.py`, `functions_mcp_preconfigurations.py` | Consistent type/origin handling and current destination policy. |
| Scoped action helpers, action loaders, `functions_legacy_action_management.py`, `route_migration.py` | Trusted storage context, retained-record management, and per-record migration. |
| `route_backend_plugins.py`, `functions_action_connection_tests.py` | Save, discovery, and connection-test boundaries. |
| `route_backend_users.py` | Legacy settings import preflight and sanitized, management-only action views in user-settings responses. |
| MCP schemas and preset definitions, `functions_mcp_presets.py` | Remote-only configuration and older remote preset compatibility. |
| Shared action modal and workspace action/migration JavaScript | Unsupported-state presentation and explicit owner choices. |
| `application\single_app\config.py` | Application version update to `0.261.031`; no deployer version change. |

Application paths above are relative to `application\single_app` unless written in full. Semantic Kernel remains a dependency for remote MCP.

## Testing and Validation

Offline validation for version **0.261.029** passed: **147 tests and 259 subtests** across the retirement, request, runtime, legacy-management, bulk-save, and import-boundary suites. The six security/management suites also passed under optimized Python (**140 tests and 259 subtests**). The offline JavaScript suite passed **12 scenarios**, including explicit remote reconfiguration, retained migration outcomes, and ID-based deletion.

Route policy, Swagger security decorators, documentation coverage, and documentation quality checks passed. Five authenticated browser scenarios collect successfully, but were not executed against a configured app or Azure Playwright environment. No live MCP server or cloud-backed result is claimed.

| Suite | Coverage |
| --- | --- |
| `functional_tests\test_mcp_stdio_removal.py` | Universal retirement without credential/connector activity, remote transport preservation, non-retryable configuration failures, and payload equality independent of authorization provenance. |
| `functional_tests\test_mcp_action_route_security.py` | MCP authorization and retirement checks in selected actual route/helper bodies, using real Flask request dispatch with mocked I/O. |
| `functional_tests\test_mcp_user_settings_ingestion.py` | Safe settings responses, legacy action imports, and validation before preference or active-workspace writes. |
| `functional_tests\test_mcp_authorization_context.py` | Consistent MCP classification, trusted scope, current user/workflow identity and settings, cached use, and environment policy precedence. |
| `functional_tests\test_mcp_legacy_stdio_management.py` | Management-only legacy records, unchanged bulk pass-through, explicit deletion, scope boundaries, and non-destructive migration/reconfiguration. |
| Existing MCP manifest, destination/preconfiguration, and preset suites | Remote authentication, headers, timeouts, catalog compatibility, and destination decisions. |
| Existing action connection-test and bulk-ID-preservation suites | Endpoint behavior, safe error handling, modal wiring, and preservation of existing action identity. |
| `ui_tests\test_workspace_mcp_action_modal.py` and related workspace UI suites | Remote-only controls, unsupported states, non-mutating opening/cancellation, and explicit remote reconfiguration. |

Run the new offline suites from the repository root:

```powershell
python -m pytest .\functional_tests\test_mcp_stdio_removal.py .\functional_tests\test_mcp_action_route_security.py .\functional_tests\test_mcp_authorization_context.py .\functional_tests\test_mcp_legacy_stdio_management.py
python -m pytest .\functional_tests\test_mcp_user_settings_ingestion.py .\functional_tests\test_user_plugin_bulk_save_id_preservation.py
node --experimental-vm-modules --test .\functional_tests\test_mcp_stdio_removal_ui.js
```

Relevant existing regressions:

```powershell
python .\functional_tests\test_mcp_action_manifest_workflow.py
python .\functional_tests\test_mcp_destination_governance_and_preconfigurations.py
python .\functional_tests\test_mcp_server_presets.py
python .\functional_tests\test_user_plugin_bulk_save_id_preservation.py
python .\functional_tests\test_action_test_connection_endpoints.py
python .\functional_tests\test_action_connection_test_secret_redaction.py
python .\functional_tests\test_action_test_connection_modal_wiring.py
```

UI execution requires a configured test instance and authenticated storage state through `SIMPLECHAT_UI_BASE_URL` and `SIMPLECHAT_UI_STORAGE_STATE`. With that environment available:

```powershell
python -m pytest .\ui_tests\test_workspace_mcp_action_modal.py
```

Before this change, documentation offered stdio configuration for privileged/global actions. After this change, no role or scope can use it; users see an explicit unsupported state and retain control over reconfiguration or deletion. Remote actions keep their supported capabilities while authorization follows current context and the deployment policy floor.

## Review Follow-Up in 0.261.030

`ScopedActionManifest` now explicitly defines dictionary-style equality and inequality. Equal JSON payloads remain equal even when their server-only origins differ, preserving unchanged management-view round trips. Equality is not an authorization check: execution continues to require the independently stored origin returned by `get_action_origin`, which plain or JSON-decoded dictionaries cannot supply.

Personal action persistence uses module-qualified settings access consistently, including the object-level legacy-read authorization boundary. Global action creation explicitly handles an absent record while preserving existing creation metadata and disabled state on updates; other storage errors still propagate before credential or database writes. The preset regression uses a precise subset assertion for useful failure diagnostics.

Focused regressions cover both operand orders, distinct authorization origins, changed payloads, `NotImplemented` comparison dispatch, dictionary unhashability, global creation/update metadata, and non-not-found lookup failures. The existing legacy-management and settings-ingestion fixtures patch the settings module directly so their no-write and authorization checks continue to exercise the production boundary.

The eight selected retirement, preset, legacy-management, settings-ingestion, bulk-save, runtime-authorization, route-security, and fresh-process import suites passed in normal and optimized Python: **161 tests and 266 subtests in each run**.

## Regression Assertion Follow-Up in 0.261.031

The unhashability regression expresses the expected failure through `unittest`'s callable exception assertion. It still invokes `hash` on the real manifest and requires a `TypeError`, now also checking the unhashable-type diagnostic. Production manifest behavior and the authorization boundary are unchanged.
