# Admin settings post-merge regressions (0.261.125)

## Issue and root causes

Admin settings could fail to save after the Development/React V2 integration while a Key Vault connection test reported success. Personal, group, and public Search index checks also returned server errors.

The investigated save failures successfully read Cosmos, then failed while writing model credentials to Key Vault with `ForbiddenByRbac`. The selected application identity had Secrets User rather than secret-write permission. The administrator corrected that live assignment, and a subsequent settings save succeeded. The earlier Cosmos key-rotation authentication failures were a separate event.

Code-level regressions and diagnostic gaps were:

| Cause | Before | After |
| --- | --- | --- |
| Public-cloud configuration omitted `search_resource_manager` | The shared Search client factory failed during import, including key and APIM paths. | Public Azure exports `https://search.azure.com`; other cloud audiences are unchanged. |
| Index observations always replaced settings | Even unchanged checks advanced the ETag and invalidated the form that started them. | Identical observations do not write. Genuine metadata changes return a conditionally proven revision to the originating form. |
| Automatic field repair omitted the `log_index_auto_fix` import | A successful repair could fail while attempting its audit log. | The existing activity logger is explicitly imported and the real repair path is covered. |
| Key Vault testing only listed secret properties | Read-only access looked sufficient to save credentials. | Both admin interfaces require list, write, read-back, and cleanup to succeed. |
| Save diagnostics obscured a denied secret write | Administrators received a generic connection/settings failure. | Classic saves and V2 model writes report safe, actionable Key Vault errors. |
| Deployers granted read-only vault access | Runtime identities could not manage application secrets. | Application-permission setup grants vault-scoped Secrets Officer. |

## Version

Fixed in version: **0.261.125**, recorded by `VERSION` in `application\single_app\config.py`.

Deployment permission logic is separately versioned **1.0.32** in `deployers\version.txt`. No live Azure permissions, configuration, deployment, restart, or application data changes were performed by this code change.

## Technical details

### Search and settings revisions

`functions_embedding_compatibility.py` reads authoritative settings before recording an observed index schema. It validates the active embedding profile, skips an identical observation, and preserves conditional-write conflicts.

`route_backend_settings.py` accepts an optional `settings_etag` on index checks. Requests with a revision must match authoritative settings before maintenance and when metadata is committed. Successful responses can return `settings_etag`; conflicts return `settings_conflict` and `needsReload`, not a replacement revision.

The classic `admin_settings.js` workflow checks personal, group, and public indexes sequentially. A queued form submission resumes through `requestSubmit`, retaining browser and existing form validation. It never substitutes a revision fetched after someone else's edit. Errors remain visible and genuine conflicts keep unsaved values in the page.

Field repair, embedding dimension/provenance validation, and the distributed Search write fence remain active. An unexpected error reading an index does not justify attempting to recreate it.

### Key Vault permissions and cleanup

`functions_keyvault_test.py` is shared by the classic and V2 connection-test dispatcher:

1. Validate the draft vault name and optional managed identity client ID.
2. Build the runtime credential with those explicit draft settings and bounded SDK connection, read, retry, and credential-process limits.
3. List secret properties, then write a uniquely named `simplechat-connection-test-*` secret containing a synthetic random value.
4. Read it back and compare its value.
5. Delete only that generated secret and confirm completion within a bounded polling wait.

Cleanup is attempted after an uncertain write as well as after a successful write. A primary error remains the primary error if cleanup also fails. Responses expose stage/status information and, when needed, the owned cleanup name, but never the probe value or raw provider exception.

The probe expires after ten minutes as a fallback. Expiration is not deletion; a cleanup warning requires administrator attention. The probe never purges secrets, so soft-deleted metadata follows the vault's retention policy.

`functions_keyvault_errors.py` supplies stable error codes and public messages. `functions_keyvault.py` raises a typed secret-storage error, which the classic settings route and V2 model-write routes surface safely. Failed writes do not fall back to plaintext. Existing staged-secret and settings-commit ordering is preserved.

### Deployment and setup guidance

Bicep's container and native permission modules, regenerated ARM, Azure CLI, and Terraform grant **Key Vault Secrets Officer at vault scope** when configuring application permissions. The CLI also reconciles existing identities and legacy access policies. The supported default system-assigned and user-assigned runtime identities are covered.

The Bicep permissions-disabled option is preserved. Existing grants are not revoked. Existing manually assigned Officer roles require the adoption/reconciliation steps in the corresponding deployer README; ARM role definitions must not be changed in place on the old Secrets User assignment GUID.

Classic templates and the V2 field schema explain the actual test, role, identity, scope, and cleanup side effects. Browser diagnostic text is rendered as text rather than interpolated HTML.

## Impact and boundaries

The changes do not remove model APIs, suppress model compatibility warnings, rotate credentials, rebuild vector indexes, or bypass Redis publication fencing. A genuine concurrent settings edit still fails safely. No new setting or capability toggle is introduced.

## Validation

Behavioral coverage includes real configuration and route imports in fresh normal and optimized Python processes with networking blocked. Real settings-store compare-and-swap behavior and Search maintenance fencing are retained; external Azure services are replaced with isolated test doubles.

The focused regressions are:

- `functional_tests\test_ai_search_client_configuration.py`: public, government, custom, key, managed identity, APIM, and unconfigured clients.
- `functional_tests\test_ai_connection_embedding_compatibility.py`: unchanged observations, initial metadata, stale forms, and concurrent writes.
- `functional_tests\test_admin_settings_diagnostics_routes.py`: all three index scopes, repair, shared classic/V2 probe routes, safe errors, and conditional save revisions.
- `functional_tests\test_key_vault_connection_permissions.py`: every failed stage, uncertain writes, read-back mismatch, cleanup timeout, validation, and isolation from existing secrets.
- `functional_tests\test_model_endpoints_key_vault_secret_storage.py`: safe denied-write errors, no plaintext fallback, and explicit credential selection.
- `functional_tests\test_deployer_key_vault_secret_permissions.py`: role, scope, identities, generated ARM, CLI reconciliation, and version contracts.
- `ui_tests\test_admin_key_vault_connection_permissions.py`: classic/V2 draft values, busy states, success, denied writes/cleanup, and safe rendering.
- `ui_tests\test_admin_settings_save_consistency.py`: sequential revisions, queued submission, retained validation, visible Search failures, and concurrent-edit protection.
- `ui_tests\test_playwright_connection_auth.py`: the Azure Playwright SDK's Entra audience and prevention of token delivery to an unrelated browser host.

The UI fixtures serve actual local assets and production templates/schema with synthetic API outcomes. They reuse the Azure Playwright connection fixture and do not touch live application settings or vault secrets. That fixture now requests `https://management.core.windows.net/.default`, the audience used by the official Azure Playwright SDK; an ARM-audience token was rejected by the browser service.

At implementation, the focused application run passed **181 tests and 528 subtests**; route-policy coverage passed **14 tests**; the UI/fixture run passed **18 checks**, including **14 Azure-hosted browser scenarios**; documentation coverage and quality passed **13 tests**; deployment contracts passed **7 tests and 33 subtests**. The V2 build, JavaScript syntax, Bicep compilation, PowerShell parsing, and Terraform formatting/validation also completed.

This is not an all-repository green-suite claim. Three unchanged SQL/MCP fixture cases were isolated because their incomplete imports or AST namespaces fail before exercising the changed behavior. A legacy manual-model-alias browser test also failed when served the unmodified baseline JavaScript. Four older deployer tests reproduced their failures against deployer 1.0.31: two exact-version assertions, an obsolete Azure CLI command-string assertion, and an outdated documentation path. Those unrelated tests were not rewritten to conceal their failures.

## Operational guidance

See [Security settings]({{ '/admin/security/#keyvault-section' | relative_url }}), [Knowledge settings]({{ '/admin/knowledge/#azure-ai-search-section' | relative_url }}), and [Admin settings troubleshooting]({{ '/troubleshooting/#admin-settings-saves-and-connection-tests' | relative_url }}).
