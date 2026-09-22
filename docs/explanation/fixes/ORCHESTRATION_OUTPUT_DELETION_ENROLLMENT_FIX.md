# Orchestration Output Deletion Enrollment

**Version: 0.261.127**

Fixed in version: **0.261.127**, tracked by
`application/single_app/config.py`. Refs #1509.

## Issue and root cause

Checkpoint cleanup could mark a run deleted and start removing source payloads
without enrolling its generated files. Completed files normally have
`cleanup_pending=false`, so an interrupted deletion could leave them outside
the scheduler's due-output scan. A parent deletion acknowledgment could also be
lost before the real checkpoint lifecycle deletion guard existed.

## Lifecycle integration

`functions_orchestration_recovery.cleanup_conversation_checkpoints` now accepts
two optional keywords in addition to its existing dependencies:

```python
cleanup_conversation_checkpoints(
    conversation_id,
    user_id,
    authorize,
    message_container=messages,
    conversation_container=conversations,
    output_cleanup=lambda run_id: build_orchestration_cleanup_service(
        user_id, conversation_id,
    ).enroll_run_cleanup(run_id),
    retain_committed=archiving_enabled,
)
```

The callback takes one owned run ID and returns the existing cleanup service's
`run_id`, `enrollment_status`, `output_count`, and `retain_committed` result.
It is called only for nonempty plan-contract v2 admissions. Legacy runs and
empty admission indexes do not initialize output cleanup.

The helper first uses the existing
`CheckpointStore.fence(deleted=True, allow_missing=True)` to establish genuine,
irreversible deletion proof, and revokes the existing assistant publication
guard. It then includes
`build_output_cleanup_intent(current_run, retain_committed=...)` in the same
fresh parent compare-and-swap as `checkpoints_deleted=True` and lease removal.
The exact admission index and retention policy remain frozen on retries.

All owned runs receive this durable enrollment before any per-run enrollment
callback or source-payload sweep. All nonempty enrollments must then complete
before native retained results or checkpoint payloads are removed. Both the
callback acknowledgment and the parent's persisted completed intent are
checked. Missing dependencies, missing checkpoint-version proof, invalid
acknowledgments, and partial enrollment raise rather than authorize a purge.
An existing retained-output index on a legacy plan is rejected rather than
silently skipped. Conversation ownership is rechecked after enrollment and
again before removing retained source payloads.

The existing successful return remains `None`. Success means enrollment is
durable, not that file bytes have been deleted. Callers must finish this helper
before their own message/conversation purge, and must not pass retained output
artifacts through unconditional legacy message or Blob deletion.

## Retention and interrupted work

`retain_committed=True` is the explicit archival policy: current successful
files remain retained while staging work is fenced. False withdraws both
committed and uncommitted files. Changing that decision on a retry is rejected.

The scheduler already enumerates pending parent enrollments independently of
ordinary run execution and due output rows. It replays the existing deletion-only
service, then performs conditional per-intent cleanup after lease grace.
Checkpoint lifecycle, parent admission, and output rows remain available for
ownership checks and late-writer reconciliation. A missing conversation alone
is not cleanup authority.

No new store, recovery protocol, service factory, execution lease, source read,
renderer call, or production activation is introduced.

## Validation

`functional_tests/test_orchestration_deletion_enrollment.py` executes the real
lifecycle helper, checkpoint/output stores, initialized cleanup service, and
scheduler with local storage boundaries. It covers completed and interrupted
uploads, both retention policies, missing dependencies and version proof,
unconfirmed enrollment, frozen-policy replay, failed checkpoint/output fences,
fresh admission indexes after a parent CAS conflict, and revoked ownership
after enrollment. It also covers parent acknowledgment loss with a genuinely
missing conversation and multiple owned runs interrupted before enrollment or
source cleanup.

The existing checkpoint recovery suite covers legacy deletion, late checkpoint
writers, and native-result fences. The authenticated caller integration is
covered by `functional_tests/test_orchestration_output_deletion_pipeline.py`;
that suite also exercises single/bulk route ordering and conditional artifact
deletion.

The helper and legacy checkpoint selection passes **65 tests and 37 subtests**
in both normal and optimized Python: 26 deletion-enrollment cases and 39
checkpoint-recovery cases. These results verify the callable lifecycle seam;
they do not substitute for wiring and verifying the route callers.

With the caller integration in place, the complete authenticated deletion
pipeline also passes **28 tests in both normal and optimized Python**. That
separate run covers both actual routes, archive-policy siblings, conditional
message cleanup, persisted lease grace, lost acknowledgments, source-cleanup
interruption, missing admissions, and uploads completing after cleanup.

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -B -m pytest .\functional_tests\test_orchestration_deletion_enrollment.py .\functional_tests\test_orchestration_checkpoint_recovery.py -q
python -B -O -m pytest .\functional_tests\test_orchestration_deletion_enrollment.py .\functional_tests\test_orchestration_checkpoint_recovery.py -q
```
