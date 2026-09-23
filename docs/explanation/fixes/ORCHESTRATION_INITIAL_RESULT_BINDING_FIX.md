# Orchestration claim and retained-read recovery

**Version: 0.261.130**

Fixed/Implemented in version: **0.261.130**, recorded in
`application/single_app/config.py`. Refs #1509.

## Issue and root cause

Initial headless preparation used the continuation module solely to bind the
initialized result store. That made the initial execution path depend on a
continuation owner it did not otherwise need at this boundary.

Calling the store's existing `bind_orchestration_execution` method directly
removes that dependency, but must not remove the wrapper's current-claim check.
The store binds the attempt observed when it is called; the runner must also
confirm that this is still the attempt it was approved to prepare. Without that
check, an attempt changed during service construction could acquire lifecycle
state before the mismatch was noticed.

## Implementation

`functions_orchestration_execution.py` rechecks the owning lease's run, actor,
conversation, and attempt against its claimed record immediately after service
construction. Only then does it install the view returned by
`WorkflowResultStore.bind_orchestration_execution`, before capability discovery
or retained-result access.

The lower store method still owns lifecycle initialization, epoch adoption, and
immutable binding. No second claim engine, new token, storage protocol, or
checkpoint factory is introduced. The original unbound store remains a separate
view. Existing continuation helpers and native producer identities are unchanged.
Model-free publication never invokes either binding path.

## Related recovery boundaries

The same version closes three coupled recovery gaps:

- Execution-bound preflight, capture, and admission callbacks freeze their
  original run, actor, conversation, token, and claim ID. Mutating or replacing
  the lease object cannot let an old callback borrow a successor's ownership.
  Both successful and failed calls recheck the original claim afterward.
- The existing invocation-control marker carries safe headless and checkpoint
  control codes through initial and sticky capture failures. Dependency dispatch
  preserves those controls before ordinary step-error mapping. Typed authority
  and output-read configuration failures preserve retained work during initial
  finalization as well as model-free refresh. A cause-free, exact
  `PermissionError` escaping current-file observation is an uncertain read,
  not the renderer's verified denied-file projection; typed denials, holds, and
  explicit causes retain their separate handling.
- Waiting Render recovery forwards the complete saved StepResult to the one
  public read-only resumer, rather than rebuilding an ID-only result. Optional
  wait error codes and output diagnostics survive checkpointing. Missing or
  mismatched saved identities fail before the output reader; old two-field
  waits remain supported. Completed Render checkpoints use the same helper.

The published four-callback contract remains intact. Invocation preflight uses
the actual provider authorization operation; configuration capture separately
performs current/actual acquisition-support checks. Neither is a no-op, an
authorization cache, or permission to skip the other.

## Validation

The final nine-suite headless/HTTP/scheduler/import selection passed **1,145
cases and 63 subtests** in both normal and optimized Python. It uses the exact
ordering that previously exposed the fixture error. The 17-suite
core/native/Render selection separately passed **782 cases in each mode**.
Both commands verified unchanged source hashes across their runs. Two known
scheduler-first bootstrap cases remain expected failures; they were not changed
or hidden by this fix.

`functional_tests/test_orchestration_harness_execution.py` exercises the real
initialized preparation path while forbidding a continuation-module import. It
verifies one lower-store binding call, guards installed before discovery, and an
independently unbound original store.

A second regression changes the saved attempt during actual service
construction. The direct-call-only proposal failed this regression; the runner's
restored current-claim check refuses it before lifecycle creation, model setup,
content generation, or upload.

The existing storage-outage, native continuation, early-interruption, immutable
claim, and publication-only cases cover the adjacent boundaries with external
I/O doubled. `test_support/orchestration_harness_execution.py` forbids the direct
store method during publication-only checks as well as the compatibility wrapper.

The callback tests use real claim takeover, lease retagging, provider checks,
and fresh store views. The source-authority and Render read-failure suites
check typed errors, unchanged retained checkpoints, and absence of independent
model or file work after an uncertain read. Saved Render tests observe the
actual shared helper once for both waiting and completed checkpoints, without
admission, rendering, upload, or target/sibling expiry inside that read boundary.
CSV and JSON download assertions verify the final retained row, not only file
metadata or a preview.

Combined validation also exposed a fixture-lifecycle issue: loading a reused
catalog test module inside an already-scoped offline bootstrap left an old
transport class cached after that bootstrap unloaded its application modules.
A later scheduler fixture correctly failed the real service's type guard.
The helper is now imported during collection, before the scoped bootstrap.
Fresh normal and optimized subprocesses run the catalog and scheduler cases in
that exact order; no production type check or fixture assertion is bypassed.

The change does not alter legacy execution, shared file formats, administrator
defaults, or the separately recorded target-branch integration blocker.
