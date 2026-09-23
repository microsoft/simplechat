# Orchestration runtime boundary hardening

**Version: 0.261.129**

Fixed/Implemented in version: **0.261.129**, recorded in
`application/single_app/config.py`. Refs #1509.

## Issue and root cause

The opt-in harness had several boundary cases in which an earlier valid read
was not enough to justify the next operation. A cached planner callable could
outlive its verified construction binding. Active execution could use a stale
export catalog. Delivery could reuse incidental saved citation metadata rather
than the selected answer's exact lineage.

Two result-state gaps also affected recovery: an untyped pending Gather preview
could be retained as complete, and an output acknowledgement outage could turn
an already admitted Render wait into an invalid-result failure. Rejecting a
continuation before checkpoint restoration could overwrite its retained maps
with the new context's empty maps.

An interruption immediately after approval exposed a separate recovery gap.
The claim saved `started_at` and its lease, but the deadline was not saved until
checkpoint initialization, after preparation and source acquisition. Scheduler
recovery therefore had no authoritative execution budget. Once that timing gap
was corrected, the continuation checkpoint owner still rejected an absent first
binding, and its lease could not adopt that initial binding without invalidating
its own immutable reads.

## Changes

| Boundary | Correction |
| --- | --- |
| Planner invocation | Constructed planner adapters recheck their original model, client, wrapper, and configuration binding on every call, including cached callables. Detached proof objects cannot mutate that binding. |
| Acquisition setup | Agent and action adapters perform acquisition-support preparation before engine imports, logger initialization, or budget setup. The separate fresh-authorization preflight and actual engine evidence remain required. |
| Current export admission | Active discovery and step revalidation use the current canonical server catalog, including empty, format-only, and profile-specific restrictions. Model-free delivery does not require admission to create new files. |
| Retained state | A pre-restoration validation failure preserves the owning lease's saved task and pending maps rather than replacing them with an empty context. |
| Answer citations | Model-free delivery reconstructs citations from the exact selected final result, rechecks current source access, and persists the same safe projection with the assistant message. Sibling task metadata and stale citation lists cannot supply provenance. |
| Pending Gather | Untyped adapter envelopes can be retained only after completed or partial invocation. Pending work requires its typed pending task and wait identity and cannot feed a downstream consumer as complete data. |
| Uncertain Render acknowledgement | A canonical admitted output ID with a consistent retryable error can remain waiting without a public output DTO. It supplies neither an artifact nor a completion claim; later authorized reads recover the same committed file. |
| Initial execution timing | A v2 approval claim atomically saves its start, deadline, and lease from server settings. Claims and executors share the existing timeout policy through a bootstrap-independent module. Preparation consumes that budget; continuation and finalization do not renew it. |
| First checkpoint after interruption | An owning execution claim can establish its first binding through the existing conditional-write owner, only without prior progress or private checkpoint manifests. Preconditions run again after a CAS conflict. Exact acknowledged writes can be adopted once; takeover, Stop, deletion, changed timing, and later binding changes remain fenced. |
| Default deletion enrollment | Omitting the internal cleanup callback now binds the initialized deletion-only service after all run fences and cleanup intents are durable. Explicit callbacks remain supported. Initialization failure preserves pending enrollment and prevents payload purge; enrollment itself performs no Blob I/O. |

The production changes are limited to
`functions_orchestration_adapters.py`,
`functions_orchestration_execution.py`,
`functions_orchestration_executor.py`,
`functions_orchestration_models.py`,
`functions_orchestration_result_runtime.py`,
`functions_orchestration_plan_revisions.py`,
`functions_orchestration_timing.py`,
`functions_orchestration_recovery.py`,
`functions_orchestration_continuation.py`,
`functions_orchestration_scheduler.py`, and
`route_backend_orchestration.py`, plus the application version.

The four external callbacks, concrete actor-bound rendering service, shared
read-only Render resumer, native job identity, and result-store claim protocol
are unchanged. Checkpoint payload versions and legacy plan fingerprints are
unchanged. The initial-binding transition uses the existing lease and
checkpoint initializer, not a second continuation implementation.

## Validation

The final 36-suite selection passed **2,378 cases and 276 subtests** in both
normal and optimized Python. The same two documented baseline startup cases
remain expected failures. Hashes for all 49 production/test source files
matched before and after both runs. Full-file access-control and XSS checks
passed for all 11 changed runtime modules; documentation coverage, source
quality, route policies, and the standalone legacy plan-schema runner passed.

The original timing failure was reproduced through real initial claims and
scheduler ticks, both before preparation and after preparation but before
execution. The regression does not insert a deadline or replace the checkpoint
factory to make recovery pass. The actual HTTP planning and execution path also
checks the configured budget in durable storage before preparation begins.

The focused suites execute real adapters, initialized services, headless
execution, durable readers, private publication, and current authority checks
with external storage and provider I/O doubled:

- `test_orchestration_harness_execution.py` covers cached planner calls, narrowed
  catalogs, retained maps, exact selected-result citations, and model-free
  delivery without producer or publication replay.
- `test_orchestration_external_preflight_adapter.py`,
  `test_orchestration_external_configuration_capture.py`, and
  `test_orchestration_capture_metadata_errors.py` cover before-effect checks,
  incomplete acquisition proof, and preserved typed failures.
- `test_orchestration_dependency_runtime.py` and
  `test_orchestration_external_gather_runtime.py` cover pending previews and
  complete or partial empty results retaining their actual grounded lineage.
- `test_orchestration_render_waiting_runtime.py` covers acknowledgement failure
  before an attempt and after commit, exact same-file recovery, and malformed
  empty-output controls.
- `test_orchestration_result_claim_fencing.py` covers cached-token writes and
  takeover between lifecycle read and transactional submission for both storage
  backends, preserving existing receipts and pending data.
- `test_orchestration_initial_claim_recovery.py` covers atomic timing, restart
  before the first checkpoint, both real checkpoint owners, lost acknowledgements
  before and after takeover, Stop/deletion races, immutable reads, and malformed
  initialization. It verifies that changed settings cannot renew the original
  budget, expired runs perform no model work, and invalid saved timing is not
  reconstructed. Fresh normal/optimized subprocesses verify the shared policy
  without initialized application owners or network access.
- `test_orchestration_deletion_enrollment.py` covers the initialized default
  cleanup path, multiple fenced runs, unavailable services, invalid admission
  proofs, and unchanged committed-file intent during enrollment.

Before these fixes, uncertainty could discard reusable state, lose or misstate
citations, or permit an operation under an outdated binding. Afterward, the
runtime preserves durable data, refuses unsupported or stale execution before
effects, and recovers existing authorized files without repeating work.
An interruption before execution can now resume the original attempt rather
than fail for missing timing or a never-initialized checkpoint binding.

## Scope and limitations

Both administrator opt-ins remain off by default. Legacy standalone behavior
and the distinction between automatic file attempts and manual plan recovery
are preserved. This change does not integrate workflows, enable unsupported
external configurations, deploy the application, or claim live-provider or
cloud-throughput validation.

Historical started records without valid saved timing remain unavailable for
automatic continuation; the application does not invent a fresh timeout for
them. A separately approved manual plan attempt has its own initial claim and
budget. Two pre-existing scheduler-first mixed-bootstrap failures remain
documented separately from the supported web and scheduler entrypoints.

See [the harness contract](../features/ORCHESTRATION_RENDERING_HARNESS.md) and
[checkpoint recovery](../features/ORCHESTRATION_CHECKPOINT_RECOVERY.md).
