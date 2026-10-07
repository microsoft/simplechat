# Action Configuration Pane Cleanup

## Overview

Version implemented: **0.261.276**

The V2 action editor now presents action settings by purpose instead of showing every stored key as a generic configuration field. Owners see identity, supported configuration controls, authentication, validation, and advanced JSON in clearer places, which reduces accidental edits to internal state and makes security-sensitive checks happen after credentials are entered.

## Dependencies

- V2 workspace action editor and action catalogue APIs.
- Existing action governance for personal, group, and global actions.
- Microsoft 365 cloud metadata for the read-only Graph endpoint.
- MCP discovery and notification infrastructure.
- OpenAPI parsing and operation registration.

## Technical specifications

### Catalogue and picker cleanup

The plugin catalogue de-duplicates entries by action type before it reaches the V2 picker. Legacy or internal-only types (`databricks_table`, `embedding_model`, `queue_storage`, `ui_test`, and `sql_schema`) are hidden from new-action creation while existing records continue to load through their current editor paths.

`sql_query` now displays as **SQL Database**. The stored type remains unchanged for compatibility, and schema discovery is included automatically when agents need table context.

### Editor layout

Custom field creation was removed from the V2 action editor. Unknown values are preserved in the draft and remain reviewable in **Advanced → JSON**, but schema-covered parent paths are not rendered again as removable fields. Empty Configuration sections are hidden, so types such as Azure Maps show only the sections they actually need.

Connection checks for native actions, MCP, and OpenAPI now live in **Authentication**. Type switching starts from the selected type's defaults and warns that current settings for the action type will be cleared.

### Per-action changes

- Azure Maps keeps the subscription key and connection check in Authentication.
- Blob Storage shows Markdown read/upload file types as ordinary switches.
- Document Search stores allowed scopes and optional group/public workspace allow-lists, enforces them at runtime, and normalizes page-based summary targets while preserving legacy custom values.
- Microsoft 365 Calendar, Email, OneDrive, and SharePoint use native V2 definitions with capability switches and a read-only Graph endpoint derived from the deployment cloud.
- Log Analytics hides the internal query-history cache from Configuration.
- MCP combines preconfigured servers and compatibility presets into one server template picker, stores approved tool and prompt fingerprints, filters unapproved drift at runtime, and surfaces drift badges and notifications.
- OpenAPI shows the selected spec filename, supports a read-only spec-derived base URL with an override switch, and stores per-operation enablement in `additionalFields.allowed_operations`.
- Yamcs reverse proxy Basic authentication moved into Authentication under its own switch.

## Usage instructions

Create or edit an action from My Workspace, a group workspace, or Admin Settings global actions. Configure only the fields shown for the selected type. Use **Authentication** for credentials and connection testing, and use **Advanced → JSON** for inspection of preserved legacy values rather than adding new custom fields.

For MCP actions, run **Discover Tools** after endpoint, transport, auth, prompt loading, or allowed tool selections change. Save only after reviewing the approved tool list. If a **Tools changed — review** badge appears later, open the action, review drift, and rediscover to approve the current server manifest.

For OpenAPI actions, upload or replace the spec, review the spec-derived base URL, enable only the operations the agent should call, and test from Authentication.

## Testing and validation

Functional coverage added in version **0.261.276**:

- `functional_tests/test_action_catalogue_dedupe_hidden_types.py`
- `functional_tests/test_action_editor_configuration_cleanup_static.py`
- `functional_tests/test_document_search_action_scope_enforcement.py`
- `functional_tests/test_mcp_tool_fingerprint_pinning.py`
- `functional_tests/test_openapi_allowed_operations_filter.py`

Documentation validation uses:

- `python .\scripts\build_docs_inventory.py`
- `python .\functional_tests\test_docs_app_surface_coverage.py`
- `python .\functional_tests\test_docs_site_quality.py`

## Known limitations

MCP drift persistence is best effort. Runtime drift metadata and owner notifications are written when the action origin can be resolved and backing storage is available; failures are logged and the unsafe changed tools remain blocked. Existing MCP actions without approved fingerprints run as unpinned legacy actions until they are saved with a connection-affecting change, when discovery and approval become mandatory.

The `ui_test` action type is hidden from new-action creation but has no standalone reference page because it is not a user-facing action. Existing records are still preserved by the editor path.

OpenAPI `allowed_operations` is backward compatible: a missing or empty list means every operation from the spec remains enabled.

Document Search still cannot broaden a user's personal, group, or public workspace permissions. Action scope settings only narrow what the current user can already access.
