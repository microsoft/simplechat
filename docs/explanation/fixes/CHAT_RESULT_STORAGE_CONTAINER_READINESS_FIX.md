# Chat result storage container readiness fix

**Fixed in version: 0.261.396**

Application version: `application/single_app/config.py`.
Deployment provisioning: deployer **1.0.36**, tracked separately in
`deployers/version.txt`.

## Issue and root cause

A chat could read its workspace documents and start analysis, then fail while
saving its first intermediate result. The plan displayed HTTP 404 rather than
explaining that Azure Blob Storage returned `ContainerNotFound`. A spreadsheet
step failing during input staging could instead report that its named results
were invalid.

The configured storage account could contain `user-documents` and
`group-documents` without containing `personal-chat`. The Bicep module created
only the former two containers, and the full CLI deployer did not ensure the
complete application container inventory. Startup correctly avoided network
checks, but analysis checkpoints and tabular staging bypassed the upload-time
container creation helper.

This is a shared backend initialization gap, not a V2 rendering defect. A
successful workspace upload does not prove that the private result container
exists.

## Changes

### Deployment provisioning

Bicep and the full Azure CLI deployment now provision the same five private
containers as the application: `user-documents`, `group-documents`,
`public-documents`, `personal-chat`, and `group-chat`. The CLI step also runs when
the storage account already exists. It uses management-plane operations rather
than retrieving account keys.

The code-only upgrade script remains code-only. Reprovision infrastructure or
use the application repair action to prepare an older environment explicitly.

### Write-triggered recovery

`blob_container_readiness.py` owns shared creation and bounded recovery without
importing configuration, settings, or logging bootstrap. Callers supply their
initialized clients and logging callback.

Result-store, tabular JSON staging/checkpoint, and generated-file/image writes
first attempt the normal upload. Only the structured Storage error code
`ContainerNotFound` can trigger container creation and one retry of the same
write. `BlobNotFound`, unrelated 404s, model failures, and source authorization
failures do not trigger creation.

Concurrent missing-container responses share a creation attempt per client and
container within each application worker. A failed creation has a 60-second
cooldown; subsequent real writes can still succeed if storage was repaired by
another worker or an administrator. The idle cache is bounded to 128 entries,
with active entries pinned until their operations finish.

Healthy writes add no existence checks or creation requests. There is no
scheduled probe, startup check, Redis readiness service, or fallback from
configured Blob storage to Cosmos. Recovery repeats a replayable Blob upload,
not the model call, source analysis, agent, or whole plan. Immutable writes,
digest verification, and lifecycle/authorization checks remain in force.

### Explicit admin repair

In either Admin Settings interface, open **Chat > Citations > Enhanced**, save
the storage configuration, then select **Create missing containers** beside the
read-only connection test.

The admin-protected
`POST /api/admin/settings/storage/repair-containers` accepts an empty JSON object.
It resolves the saved configuration server-side and operates only on the fixed
application inventory. It does not accept browser-supplied endpoints or container
names, change settings, grant permissions, alter existing container ACLs, or
delete files.

Each result is `created`, `already_exists`, or `failed`. Partial failure returns
an unsuccessful response with all container outcomes retained. Creation uses
bounded network timeouts and disables nested SDK retries. Only
`ContainerAlreadyExists` is accepted as an existing-container race; other
conflicts remain failures.

The UI disables duplicate requests while busy, requires connection drafts to be
saved before repair, and renders status and recovery guidance inline. Repair
never reruns the failed conversation.

### Actionable failures

Failed recovery uses the safe `result_storage_unavailable` code. Analysis failure
handling and the persisted native computation result preserve this category
instead of substituting generic HTTP 404 or `result_invalid`.

The browser receives an application-owned explanation that progress/results
could not be saved and that storage setup/access needs administrator attention.
Provider XML, credentials, endpoints, and exception messages are not returned.
Server-side diagnostics retain safe container/reason/status information and
existing hashed orchestration correlation.

## Files and coverage

The core changes are in:

- `application/single_app/blob_container_readiness.py`
- `application/single_app/functions_workflow_result_store.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/functions_native_analysis_results.py`
- `application/single_app/functions_orchestration_native_results.py`
- `application/single_app/functions_orchestration_schema.py`
- `application/single_app/functions_documents.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/route_backend_settings.py`
- Both existing admin storage diagnostic interfaces and deployment paths.

Regression coverage:

- `functional_tests/test_blob_container_readiness.py`: 100 healthy writes without
  additional storage checks, concurrent recovery, cooldown, explicit repair,
  re-deletion, conflict handling, authority changes, cache bounds, and real
  normal/optimized bootstrap-free imports.
- `functional_tests/test_storage_container_result_writers.py`: real analysis
  checkpoints and native tabular staging, complete retained results, no extra
  model calls during recovery, and stable storage failure propagation.
- `functional_tests/test_admin_storage_container_repair_routes.py`: real routes
  and security decorators in normal/optimized processes, saved settings,
  idempotence, partial failure, privacy, and read-only testing.
- `functional_tests/test_storage_container_provisioning.py`: inventory parity,
  private defaults, and execution of the actual CLI provisioning block over
  mocked Azure commands for fresh/reused accounts.
- `functional_tests/route_tests/test_storage_container_repair_policy.py`:
  Blueprint, Swagger, login, and admin policy.
- `ui_tests/test_admin_storage_container_repair.py`: built V2 SPA and classic
  handler interaction, keyboard activation, busy state, saved-setting drafts,
  responsive/light/dark coverage, and inline partial-failure guidance.

## Operational validation

Before: an absent result container surfaced as a generic 404 or invalid-output
message even though the source document was readable.

After: deployments prepare the container inventory; first-use result writes
recover missing containers when the app has permission; admins can explicitly
repair and inspect outcomes without rerunning work. If creation is denied, the
request remains failed with a storage-specific explanation.

No automatic provisioning can overcome a denied identity or blocked network.
Fix those conditions before retrying. Historical failed messages are not
rewritten; deploying this change does not itself rerun or verify an earlier
conversation.
