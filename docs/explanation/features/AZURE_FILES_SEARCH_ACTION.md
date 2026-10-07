# Azure Files Search Action

Implemented in version: **0.261.293**

Related issue: [#1697](https://github.com/microsoft/simplechat/issues/1697)

## Overview

Many customers already index Azure file shares into Azure AI Search with the Azure Files indexer (preview). The Azure Files Search action lets SimpleChat agents search those existing indexes without re-ingesting the content.

The index carries file text and paths but no permissions, and Azure AI Search cannot ingest Azure Files ACLs. So the action checks each candidate file's NTFS permissions and the share's permissions against the signed-in user at query time. Only files the user is proven able to open reach the model.

Withheld files are never mentioned to users. They are recorded for administrators so problems can be found and fixed over time.

## Dependencies

- `azure-search-documents==11.5.3`: GA API `2024-07-01`, including `VectorizableTextQuery` for hybrid search through an index vectorizer.
- `azure-storage-file-share==12.25.0`: OAuth with `token_intent="backup"`, `get_file_properties().permission_key`, and `ShareClient.get_permission_for_share`.
- Microsoft Graph: the signed-in user's delegated token (`/me`, `/me/transitiveMemberOf/microsoft.graph.group`, and directory lookups for principals named in ACLs).
- Azure Resource Manager: the storage account's default share-level permission and the user's role assignments at the file share scope.
- Roles for SimpleChat's managed identity:
  - Search Index Data Reader on the search service.
  - Storage File Data Privileged Reader on each storage account or share.
  - Reader on each storage account.

## Technical Specifications

### Architecture

1. An agent or orchestration step calls `search_files(query, top_n)`. The model controls only the query text and a bounded result count.
2. `functions_azure_files_search_runtime.execute_azure_files_search` does the following, in order:
   1. Refuses unsigned users and any action not bound to global scope.
   2. Validates the configuration and refuses SimpleChat's own indexes.
   3. Resolves the user's SIDs through Graph.
   4. Runs `functions_azure_files_search.run_azure_files_search`.
3. The search over-fetches candidates (50 by default) and groups them by file. Then a bounded thread pool, inside a time budget, decides each file:
   1. Is the share on the action's allowlist?
   2. Share-level access, from the default permission or the user's role assignments, including through groups (`functions_azure_files_access.check_share_level_access`).
   3. The file's SDDL, read with backup intent and cached by permission key, then evaluated by `functions_azure_files_acl.evaluate_read_access`.
4. Only allowed results are returned, with file name, UNC path, folder, last modified, a clipped snippet, and score. At most three results come from one file.
5. `record_azure_files_search_review`:
   - always emits an `[AZURE_FILES_SEARCH]` telemetry event;
   - writes an `azure_files_search_access` activity log entry when files were withheld. The entry carries the conversation ID and the invoking agent's ID and name, read from the execution frame or `g` (`conversation_id`, `request_agent_info`); no other agent configuration is copied;
   - notifies administrators at most once per action per day when files could not be verified.

### Permission evaluation

`functions_azure_files_acl` parses SDDL and evaluates the DACL in order for `FILE_READ_DATA`, as Windows does:

- **Applies to the user:** the user's own SIDs, their groups' SIDs, Everyone, Authenticated Users, and Network. Domain Users applies when it's in the user's on-premises domain.
- **Never applies to the user:** built-in administrator, system, service, placeholder, and integrity principals.
- **BUILTIN\Users:** unknown unless the administrator opts in.
- **Other principals:** if Graph places the principal as a different directory object, it doesn't apply. Otherwise its membership is unknown.

An ACE whose membership is unknown, a conditional or object ACE, or a read right granted only through generic bits makes the answer **unverified**, but only when it could change the outcome. Inherit-only ACEs are skipped. A null DACL allows access. An empty DACL denies it.

Reason codes:

- **Denied:** `acl_explicit_deny`, `acl_no_allow`, `acl_empty`, `share_access_denied`.
- **Unverified:** `sid_unresolved`, `acl_unsupported`, `acl_parse_error`, `acl_missing`, `identity_unavailable`, `path_missing`, `storage_not_allowlisted`, `file_not_found`, `acl_read_failed`, `share_access_unknown`, `time_budget_exceeded`.

### Configuration

Action type `azure_files_index`; display name "Azure Files Search". It is global only (`GLOBAL_ONLY_ACTION_TYPES`):
- Personal and group type lists exclude it.
- The personal and group save paths, including the V2 editors, return 403 for it, and `prepare_scoped_action` rejects personal and group saves.
- `is_global_only_action_type` normalizes types the way the plugin loaders match them to plugin classes, so aliases such as `AzureFilesIndex` or `files_index` are refused too.
- The runtime runs only a manifest bound to a global origin by the authorized global-action lookup. Personal, group, and unbound manifests are refused, the same rule MCP actions follow.

Auth is `identity` (managed identity) or `key` (a query key stored like other action secrets). The full `additionalFields` schema is `static/json/schemas/azure_files_index_plugin.additional_settings.schema.json`:

- `index_name`, `index_layout`, and the field mapping, with defaults per layout.
- `query_mode`, `semantic_configuration`.
- `default_top_n`, `max_candidates`, `max_snippet_chars`, `time_budget_seconds`.
- `permission_mode` (`live_acl` or `none`), `permission_mode_none_acknowledged`.
- `share_access_check` (`rbac` or `skip`), `treat_builtin_users_as_member`.
- `storage_shares`.

### API

`POST /api/plugins/test-azure-files-index-connection`: admin only, global scope. It runs these checks:
- configuration
- search access
- file paths
- query mode
- identity
- share access and file permissions for each share
- allowlist coverage

Failures return role-specific guidance.

### File structure

- `functions_azure_files_acl.py`: SDDL parser, DACL evaluator, membership policy. No I/O.
- `functions_azure_files_access.py`: Graph principals and SID classification, ARM share-level checks, TTL caches.
- `functions_azure_files_search.py`: configuration, internal-index guard, path parsing, search request, permission pipeline, model response, review record.
- `functions_azure_files_search_runtime.py`: Azure clients, review recording and notifications, connection check.
- `semantic_kernel_plugins/azure_files_index_plugin.py`: the Semantic Kernel action.
- `functions_azure_endpoint_validation.py`: `validate_azure_search_endpoint`, `validate_azure_file_endpoint`.
- UI:
  - V1: `templates/_plugin_modal.html`, `static/js/plugin_modal_stepper.js`.
  - V2: the global action editor configuration component, registry entry, and test wiring.
  - Control Center V1: activity type filter, labels, details, and CSV.
  - Control Center V2: picks up the activity type through facets.

## Usage Instructions

1. Grant SimpleChat's managed identity the roles above. The deployers' optional `azureFilesStorageAccountResourceIds` and `externalSearchServiceResourceIds` inputs can do this.
2. In Admin Settings (V1) or the V2 global action editor, create an Azure Files Search action:
   - Enter the search endpoint, the index, and its layout.
   - Add every storage account and share the index was built from.
   - Run the connection test.
3. Assign the action to agents. Users reach it through those agents and orchestration.
4. Review **Azure Files Search Access** entries in the Control Center activity logs. Unverified entries usually mean a missing role, an Active Directory group that isn't synced to Entra ID, or a stale index.

## Testing and Validation

- `functional_tests/test_azure_files_acl_evaluator.py`: SDDL parsing and evaluation, including the test-environment scenarios.
- `functional_tests/test_azure_files_search_pipeline.py`:
  - configuration, endpoint validators, and the internal-index guard;
  - path parsing and search request shapes;
  - allowed, denied, and unverified pipeline outcomes, time budget, and limits;
  - the Graph and ARM helpers and global-only enforcement.
- `functional_tests/test_azure_files_search_integration.py`:
  - plugin discovery and loader matching, which doesn't capture the legacy `search` type;
  - health checker validation and runtime refusals;
  - dependency wiring and review and notification rules;
  - activity log shape, Control Center, routes, schemas, and notifications.
- V1 and V2 UI tests: `ui_tests/test_admin_azure_files_index_action_modal.py`, `ui_tests/test_v2_admin_azure_files_index_action.py`, and the V2 logic test `functional_tests/test_v2_azure_files_index_action_logic.mjs`.
- Live proof of concept on a test share. Eight files were set up with user, group, non-member group, explicit deny, unknown SID, Everyone, BUILTIN\Users, and .docx ACLs. All eight expected outcomes matched on both a one-document-per-file index (semantic) and a chunked integrated-vectorization index (hybrid).

### Performance

- Security descriptors are cached by permission key, because files with identical ACLs share one key.
- User principals, SID lookups, share decisions, and role definitions use TTL caches.
- Permission checks run in parallel within the time budget.

### Known Limitations

- Active Directory groups that aren't synced to Entra ID, and memberships that exist only in Active Directory, can't be resolved. Files whose answer depends on them are withheld as unverified.
- Deny assignments and conditional role assignments at the share aren't evaluated, so conditional grants make share access unknown.
- Fully background runs with no signed-in session can't resolve a user and return no results.
- The Azure Files indexer is a preview feature of Azure AI Search.
