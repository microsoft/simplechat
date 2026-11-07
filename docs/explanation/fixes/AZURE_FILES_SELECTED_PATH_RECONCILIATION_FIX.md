# Azure Files selected-path reconciliation fix

Fixed in version: **0.261.369**

Application version: `application/single_app/config.py`.

## Issue and root cause

An explicitly selected Azure Files path that disappeared caused sync to fail
before applying the source's saved retain/delete policy. The connector first
probed the selection as a file. After a 404 it attempted to list that same path
as a directory; the second 404 failed the run. Whole-root sync could already
reconcile the same deletion.

Read-only Azure telemetry for the reported retain/delete runs showed this exact
sequence, followed by `azure_files_resource_not_found` in `azure_files_list`.
The baseline document import and citation checks had succeeded. An offline
reproduction using the pinned SDK and production run/policy functions reproduced
the difference between whole-root and explicit-file selections.

## Technical changes

`application/single_app/functions_file_sync.py` now resolves Azure Files selections
through complete parent directory inventories anchored at the configured root.
Actual entry types distinguish files from directories. Directory inventories
are cached within a run; overlapping selections deduplicate files and traversal.
File properties, canonical remote paths, change tokens, filters, recursion,
identity resolution, and downstream ingestion retain their existing contracts.

An absent child in a successfully exhausted parent listing is confirmed absence.
The existing reconciliation code retains its imported document under `ignore`,
or invokes the existing source-scoped deletion path under `hard_delete`.
Selections remain saved for future runs, including when a selected folder or an
intermediate folder disappears.

Missing configured roots/shares, authentication/authorization failures, transport
failures, failed pagination, and entries disappearing during enumeration still
fail the run before deletion reconciliation. A 404 alone is not interpreted as
successful emptiness. The SDK's normal directory URL serialization is unchanged.

The existing Azure enumeration budget of twice `file_sync_max_files_per_run`
is enforced for distinct files in the selected scope. Exceeding it now logs
`azure_files_inventory_limit_exceeded` and fails safely rather than returning a
partial successful inventory. Filters apply after enumeration; the ingestion
and byte budgets remain unchanged. Exactly reaching the inventory limit is
allowed when coverage is complete.

The fix applies to personal, group, and public workspaces and all existing
classic/V2 callers of the shared connector. No API, stored-source schema,
authorization policy, or deployment configuration changes are required.
Credentials must permit directory listings at the configured root and along
selected paths; file-read-only access cannot prove absence safely.

## Regression coverage

`functional_tests/test_file_sync_azure_files_selection_lifecycle.py` uses the real
`azure-storage-file-share==12.25.0` SDK with a path-aware paginated offline HTTP
transport. It reuses existing SDK-shaped Cosmos containers and executes the
production run, staging, persistence, and deletion-policy functions. Only
external HTTP, logging, document ingestion/deletion, and unrelated application
dependencies are isolated.

Coverage includes:

- Selected files/folders and missing descendants, both saved policies, all
  workspace scopes, saved identities and direct credentials.
- Present, unchanged, and changed selected files; overlapping/mixed selections;
  retained document IDs, saved run results, ignored items, and source isolation.
- Nested paths, share-root selection, canonical escaping, recursion, filters,
  byte limits, supported credential dispatch, and exact inventory-limit boundaries.
- Missing roots/shares, 401/403, transport errors, late-page failures, entries
  disappearing during enumeration, and inventory exhaustion without deletion.
- Fresh-process normal and optimized Python probes with blocked network access
  and explicit checks that required selection operations execute.

The existing diagnostic test now expects parent-based directory resolution,
not the removed HEAD/404 fallback.

## Validation

Before the fix, the new disappeared-file regression failed because the saved
second run was `failed` instead of `completed`. After the fix, confirmed absence
reaches the existing policy handler, while uncertain inventories preserve
tracked documents and save a failed run.

Commands below used the session-isolated interpreter with the application's
pinned Azure Files, Cosmos, Flask, and Werkzeug dependencies:

```powershell
python -m pytest functional_tests\test_file_sync_azure_files_selection_lifecycle.py functional_tests\test_file_sync_azure_files_runtime.py functional_tests\test_file_sync_azure_files_diagnostics.py functional_tests\test_file_sync_azure_files_identity.py functional_tests\test_file_sync_concurrent_write_safety.py functional_tests\test_file_sync_cosmos_response_contract.py functional_tests\test_file_sync_ssrf_validation.py -q --tb=short
```

Result: **355 passed**, including the normal/optimized fresh-process probes.

```powershell
python functional_tests\test_docs_app_surface_coverage.py
python functional_tests\test_docs_site_quality.py
```

Results: **7/7** coverage checks and **6/6** site-quality checks passed. The
application surface inventory is current; this fix introduces no new controls,
settings, or routes.

### Cosmos review and full runtime contracts

The module fingerprint invalidated the 14 existing File Sync storage-owner
reviews. Their function bodies, response consumers, and runtime evidence are
unchanged. After reviewing each contract and rerunning the owner tests,
`functional_tests/cosmos_response_boundaries.json` was refreshed; only those
14 module fingerprints changed.

```powershell
python scripts\check_cosmos_response_boundaries.py --run-contracts
```

Inventory result: **1,067 owners, 413 doubles, zero review gaps**.
The initial runtime invocation could not collect unrelated tests because the
local environment had incompatible OpenSSL dependencies. Restoring the
application-pinned Semantic Kernel/OpenAI dependencies and compatible OpenSSL
resolved collection. Subsequent runs exposed a missing pinned Yamcs client and
an inherited Cosmos SDK that differed from the application's pin; these were
also corrected only in the session environment.

All 115 reviewed runtime selectors were then executed with the gate's
`test_support.cosmos_network_guard` plugin, in two batches to avoid rerunning
successful bootstrap tests while diagnosing dependency failures:

```powershell
python -m pytest -p test_support.cosmos_network_guard functional_tests\test_action_credentials_bootstrap.py functional_tests\test_action_credentials_chat_reconstruction.py::test_shared_chat_private_prompt_and_exact_continuation -q --disable-warnings --tb=short --maxfail=1
```

Result: **17 passed** with the pinned Cosmos SDK.

The remaining 113 selectors were obtained directly from
`check_cosmos_response_boundaries.runtime_test_targets(inventory)[2:]` and passed
to `python -m pytest -p test_support.cosmos_network_guard` with the same
`-q --disable-warnings --tb=short --maxfail=1` flags.
Result: **1,221 passed, 144 subtests passed**. Together these batches cover the
full reviewed runtime selector set; the original monolithic invocation is not
reported as passing.

Python compilation of the changed application/tests and `git diff --check`
also passed. No dependency manifest or unrelated application code was changed
to repair the local test environment.

These tests do not establish a deployed fix, live Azure RBAC/network availability,
real document indexing, or new live chat/citation results. Live investigation
was read-only; no live fixtures, syncs, chats, settings, or deployments were
changed. External harness findings are a separate session artifact, not part of
this product fix.

## Related documentation

- [Azure Files File Sync](../features/v0.241.127/AZURE_FILES_FILE_SYNC.md)
- [Create a file sync](../../guides/create-a-file-sync.md)
- [Connector diagnostics](../../reference/logging-tags.md#azure-files-connector-diagnostics)
