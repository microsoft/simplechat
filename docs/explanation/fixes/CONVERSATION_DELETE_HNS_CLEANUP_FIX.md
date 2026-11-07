# Conversation deletion and HNS cleanup (v0.261.306)

Fixed in version: **0.261.306**

Application version tracking: `application/single_app/config.py`.
Depends on the shared HNS cleanup introduced in **0.261.305** and merged in
[#1726](https://github.com/microsoft/simplechat/pull/1726).

## Issue and root cause

Deleting a conversation could return HTTP 503 with
"Execution data could not be removed. Please retry deletion."
Production telemetry identified `WorkflowResultIntegrityError` in all 11
investigated single-conversation failures. The latest correlated request listed
Blob Storage successfully, then failed before any Blob deletion. This was not
evidence of a Microsoft 365 sign-in failure.

The storage account uses hierarchical namespace (HNS). Flat Blob listings can
contain explicitly marked directory objects alongside private execution-result
files. The old result-file-only validation rejected these legitimate directories.
Conversation deletion and workflow deletion both use
`WorkflowResultStore._delete_scoped_blobs()`, so the shared fix also repairs
conversation cleanup.

The [workflow deletion fix](WORKFLOW_DELETE_HNS_DIRECTORY_FIX.md) documents
read-only verification of the HNS directory markers and the storage safeguards.
No production conversation, workflow, or Blob was manually deleted during this
investigation.

## Technical changes

### Scoped result cleanup

The integrated storage fix handles both orchestration results and chat-analysis
results. Explicit directory identity, a known zero size, and the allowed hashed
path depth are required. A trailing slash alone is not proof of a directory.
Result files retain their path and identity-metadata validation.

Files are deleted before directories. Directories are freshly verified and
deleted deepest-first with their current ETag and a non-recursive conditional
delete. Missing objects are retryable; unexpected objects, changed types,
conditional-delete races, and storage failures still block completion.
Scope-root and ancestor directories are not swept.

Current-plan results are cleaned for every retained producer step, not only an
Analyze step. Cleanup does not rerun a workflow, retrieve original sources, or
require a fresh Microsoft 365 sign-in. The application still needs access to its
Cosmos DB and storage resources.

### Safe diagnostics and browser responses

`application/single_app/functions_orchestration_recovery.py` adds scoped failure
logging around conversation fencing, run discovery, run fencing, generated-output
enrollment, retained-result cleanup, and checkpoint-payload cleanup. It rethrows
the original exception.

Diagnostics retain the exception class, controlled stage, hashed conversation
and run correlations, recognized application failure codes, and valid HTTP error
statuses. They exclude exception text, provider payloads, raw identifiers, and
tracebacks. Provider-specific codes, malformed application codes, boolean
statuses, and statuses outside 400-599 are omitted.

`application/single_app/route_backend_conversations.py` returns trusted static
messages instead of provider errors:

| Failure | Client code | Status |
| --- | --- | --- |
| Private execution-result integrity validation | `conversation_execution_integrity_failed` | 503 |
| Execution-data storage failure | `conversation_execution_storage_unavailable` | 503 |
| Other required execution cleanup | `conversation_execution_cleanup_failed` | 503 |
| Pending Microsoft 365 action cancellation | `conversation_pending_actions_cleanup_failed` | 503 |
| Other caught conversation deletion failure | `conversation_delete_failed` | 500 |

Single deletion now also handles chat-analysis cleanup failures as safe JSON
errors. Bulk deletion preserves `success`, `deleted_count`, and `failed_ids`,
and adds a parallel `failures` array:

```json
{
    "conversation_id": "requested-conversation",
    "error": "Execution data storage is unavailable. Please retry deletion. If this continues, ask your administrator to check storage access.",
    "code": "conversation_execution_storage_unavailable",
    "status_code": 503
}
```

The bulk endpoint still returns HTTP 200 for its aggregate result; each failure
contains its own status. Missing and foreign conversations receive identical
`conversation_unavailable` details with status 404, without starting cleanup.

No routes, settings, authentication policies, or browser assets are added.

### Cleanup boundaries and retries

Conversation history is not purged while required execution-data cleanup remains
unconfirmed. Deletion fences and cleared execution leases intentionally persist
after a failure so late workers cannot republish results. A hidden
`assistant_artifact` publication tombstone may also be created; it is a fence, not
a new user-visible reply.

Cleanup is not an atomic transaction across every storage object. Verified result
files or checkpoint payloads may already have been removed before a later failure.
The conversation and ordinary history remain available for a deletion retry.
Retained generated files keep their existing enrollment, conditional cleanup,
grace period, and archiving rules; direct message cleanup does not bypass them.

## Recovery after deployment

Deploy **0.261.306** or later for the shared storage fix and conversation-specific
diagnostics. The underlying valid-directory deletion repair is already present
in **0.261.305**.

Retry **Delete** on the stuck conversation. A valid HNS-directory case requires
no manual data repair and no workflow restart. Failed cleanup fences remain in
effect while the retry finishes.

If deletion still fails, correlate the failed request with
`[ORCHESTRATION_RUNS] Conversation cleanup stage failed.` and the route's cleanup
event. Inspect `sc_stage`, `sc_error_type`, `sc_failure_code` when present, and
the hashed conversation/run fields. Check application storage access for a
storage error; investigate unexpected objects for an integrity error.

Do not bypass integrity validation, recursively delete broad prefixes, or remove
conversation history before cleanup is confirmed.

This follow-up has not been deployed as part of the investigation.

## Testing and validation

`functional_tests/test_conversation_delete_hns_directory_cleanup.py` exercises
real authenticated single and bulk routes, recovery, and private result cleanup
with deterministic external storage doubles. Its 42 cases cover ordinary and
HNS listings, non-Analyze retained producers, committed and interrupted chat
analysis, invalid objects, storage failures, retry, ownership, partial bulk
results, generated-output enrollment, and telemetry sanitization.

`functional_tests/test_conversations_read_ownership_authorization.py` now restores
its fake import dependencies after requests, import errors, and app setup errors.
This prevents the lightweight read fixture from replacing authentication modules
used by subsequent real cleanup tests.

The combined result-store, deletion enrollment/bootstrap/output lifecycle,
initial-claim recovery, conversation ownership/deletion, saved-analysis, and
Microsoft 365 lifecycle selection passed **541 tests and 112 subtests**.
The reverse-order conversation selection passed **52 tests**. All three route
policy scripts passed **26 checks**.

Local validation uses an ignored virtual environment with repository-pinned
Flask/Werkzeug and a compatible OpenSSL package. No global Python installation
or application dependency manifest was changed. Tests do not mutate production
data.

## Before and after

Before, legitimate HNS directories blocked conversation deletion and the generic
toast concealed the failing cleanup stage. After, verified directories are
removed safely, failed cleanup remains retryable without purging history, and
administrators can distinguish integrity, storage, and enrollment failures
without exposing private error details.

See [Operate SimpleChat day to day](../../guides/admin-operate-simplechat.md)
for operational troubleshooting.
